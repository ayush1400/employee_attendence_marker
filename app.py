import csv
import hmac
import io
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, g, jsonify, request, send_from_directory, session

DB_PATH = "attendance.db"
MATCH_THRESHOLD = 0.5  # lower = stricter
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # change this!

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DEFAULT_SETTINGS = {
    "shift_start": "09:30",   # HH:MM
    "grace_min": "15",        # minutes allowed after shift start
    "full_day_hours": "8",    # >= this -> Present
    "half_day_hours": "4",    # >= this -> Half Day, below -> Short
}


# ---------- database ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_e):
    con = g.pop("db", None)
    if con:
        con.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            department TEXT DEFAULT '',
            descriptor TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            work_date TEXT NOT NULL,
            check_in TEXT,
            check_out TEXT,
            UNIQUE(employee_id, work_date)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
    con.commit()
    con.close()


def get_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------- helpers ----------
def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def valid_descriptor(d):
    return isinstance(d, list) and len(d) == 128 and all(isinstance(x, (int, float)) for x in d)


def find_match(descriptor, exclude_id=None):
    best, best_dist = None, None
    for e in get_db().execute("SELECT * FROM employees WHERE active=1"):
        if e["id"] == exclude_id:
            continue
        d = distance(descriptor, json.loads(e["descriptor"]))
        if best_dist is None or d < best_dist:
            best, best_dist = e, d
    return (best, best_dist) if best is not None and best_dist <= MATCH_THRESHOLD else (None, best_dist)


def to_time(s):
    return datetime.strptime(s, "%H:%M:%S")


def decorate(row, s):
    """Add late flag, worked hours and status to an attendance row."""
    r = dict(row)
    limit = (datetime.strptime(s["shift_start"], "%H:%M") + timedelta(minutes=int(s["grace_min"]))).time()
    r["late"] = bool(r["check_in"]) and to_time(r["check_in"]).time() > limit
    if r["check_out"]:
        h = (to_time(r["check_out"]) - to_time(r["check_in"])).total_seconds() / 3600
        r["hours"] = round(h, 2)
        r["status"] = (
            "Present" if h >= float(s["full_day_hours"])
            else "Half Day" if h >= float(s["half_day_hours"])
            else "Short"
        )
    else:
        r["hours"] = None
        r["status"] = "Working" if r["work_date"] == datetime.now().strftime("%Y-%m-%d") else "No Logout"
    return r


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return jsonify(error="Admin login required"), 401
        return fn(*a, **kw)
    return wrapper


def report_rows(frm, to, code=None):
    s = get_settings()
    sql = """SELECT e.emp_code, e.name, e.department, a.work_date, a.check_in, a.check_out
             FROM attendance a JOIN employees e ON e.id = a.employee_id
             WHERE a.work_date BETWEEN ? AND ?"""
    args = [frm, to]
    if code:
        sql += " AND e.emp_code = ?"
        args.append(code)
    sql += " ORDER BY a.work_date DESC, e.name"
    return [decorate(r, s) for r in get_db().execute(sql, args)]


# ---------- pages ----------
@app.route("/")
def kiosk():
    return send_from_directory("static", "kiosk.html")


@app.route("/admin")
def admin_page():
    return send_from_directory("static", "admin.html")


# ---------- kiosk API (public) ----------
@app.post("/api/mark")
def mark():
    data = request.get_json(force=True)
    action, desc = data.get("action"), data.get("descriptor")
    if action not in ("login", "logout"):
        return jsonify(error="Invalid action"), 400
    if not valid_descriptor(desc):
        return jsonify(error="Invalid face data"), 400

    emp, _ = find_match(desc)
    if emp is None:
        return jsonify(error="Face not recognised. Contact admin to register."), 404

    n = datetime.now()
    today, stamp = n.strftime("%Y-%m-%d"), n.strftime("%H:%M:%S")
    con = get_db()
    row = con.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (emp["id"], today)
    ).fetchone()

    if action == "login":
        if row:
            return jsonify(error=f"{emp['name']} already logged in at {row['check_in']}"), 409
        con.execute("INSERT INTO attendance (employee_id, work_date, check_in) VALUES (?,?,?)",
                    (emp["id"], today, stamp))
        con.commit()
        late = decorate({"work_date": today, "check_in": stamp, "check_out": None}, get_settings())["late"]
        note = " (late)" if late else ""
        return jsonify(message=f"Welcome {emp['name']}! Logged in at {stamp}{note}",
                       name=emp["name"], emp_code=emp["emp_code"], time=stamp, late=late)

    if not row:
        return jsonify(error=f"{emp['name']} has not logged in today"), 409
    if row["check_out"]:
        return jsonify(error=f"{emp['name']} already logged out at {row['check_out']}"), 409
    con.execute("UPDATE attendance SET check_out=? WHERE id=?", (stamp, row["id"]))
    con.commit()
    hours = round((to_time(stamp) - to_time(row["check_in"])).total_seconds() / 3600, 2)
    return jsonify(message=f"Goodbye {emp['name']}! Logged out at {stamp}",
                   name=emp["name"], emp_code=emp["emp_code"], time=stamp, hours=hours)


# ---------- admin auth ----------
@app.post("/api/admin/login")
def admin_login():
    pw = (request.get_json(force=True).get("password") or "")
    if hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
        session["admin"] = True
        return jsonify(message="ok")
    return jsonify(error="Wrong password"), 401


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify(message="ok")


@app.get("/api/admin/me")
def admin_me():
    return jsonify(admin=bool(session.get("admin")))


# ---------- admin: employees ----------
@app.get("/api/admin/employees")
@admin_required
def list_employees():
    rows = get_db().execute(
        "SELECT id, emp_code, name, department, active FROM employees ORDER BY active DESC, name"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/admin/employees")
@admin_required
def add_employee():
    d = request.get_json(force=True)
    name, code, dept = (d.get("name") or "").strip(), (d.get("emp_code") or "").strip(), (d.get("department") or "").strip()
    if not name or not code:
        return jsonify(error="Name and employee code are required"), 400
    if not valid_descriptor(d.get("descriptor")):
        return jsonify(error="Invalid face data"), 400
    dup, _ = find_match(d["descriptor"])
    if dup:
        return jsonify(error=f"This face is already registered as {dup['name']}"), 409
    try:
        con = get_db()
        con.execute(
            "INSERT INTO employees (emp_code, name, department, descriptor, created_at) VALUES (?,?,?,?,?)",
            (code, name, dept, json.dumps(d["descriptor"]), datetime.now().isoformat(timespec="seconds")),
        )
        con.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="Employee code already exists"), 409
    return jsonify(message=f"{name} registered")


@app.post("/api/admin/employees/<int:eid>/face")
@admin_required
def re_enroll(eid):
    desc = request.get_json(force=True).get("descriptor")
    if not valid_descriptor(desc):
        return jsonify(error="Invalid face data"), 400
    dup, _ = find_match(desc, exclude_id=eid)
    if dup:
        return jsonify(error=f"This face already belongs to {dup['name']}"), 409
    con = get_db()
    con.execute("UPDATE employees SET descriptor=? WHERE id=?", (json.dumps(desc), eid))
    con.commit()
    return jsonify(message="Face updated")


@app.post("/api/admin/employees/<int:eid>/toggle")
@admin_required
def toggle_employee(eid):
    con = get_db()
    con.execute("UPDATE employees SET active = 1 - active WHERE id=?", (eid,))
    con.commit()
    return jsonify(message="ok")


@app.delete("/api/admin/employees/<int:eid>")
@admin_required
def delete_employee(eid):
    con = get_db()
    con.execute("DELETE FROM attendance WHERE employee_id=?", (eid,))
    cur = con.execute("DELETE FROM employees WHERE id=?", (eid,))
    con.commit()
    if cur.rowcount == 0:
        return jsonify(error="Employee not found"), 404
    return jsonify(message="Employee deleted")


# ---------- admin: attendance ----------
@app.get("/api/admin/summary")
@admin_required
def summary():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    con, s = get_db(), get_settings()
    recs = {r["employee_id"]: r for r in con.execute("SELECT * FROM attendance WHERE work_date=?", (date,))}
    out = []
    for e in con.execute("SELECT * FROM employees WHERE active=1 ORDER BY name"):
        item = {"emp_code": e["emp_code"], "name": e["name"], "department": e["department"]}
        r = recs.get(e["id"])
        if r:
            item.update(decorate(r, s))
        else:
            item.update(status="Absent", check_in=None, check_out=None, hours=None, late=False)
        out.append(item)
    return jsonify(out)


@app.get("/api/admin/report")
@admin_required
def report():
    today = datetime.now().strftime("%Y-%m-%d")
    return jsonify(report_rows(request.args.get("from") or today, request.args.get("to") or today,
                               request.args.get("code")))


@app.get("/api/admin/export.csv")
@admin_required
def export_csv():
    today = datetime.now().strftime("%Y-%m-%d")
    frm, to = request.args.get("from") or today, request.args.get("to") or today
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Code", "Name", "Department", "Login", "Logout", "Hours", "Status", "Late"])
    for r in report_rows(frm, to, request.args.get("code")):
        w.writerow([r["work_date"], r["emp_code"], r["name"], r["department"], r["check_in"] or "",
                    r["check_out"] or "", r["hours"] if r["hours"] is not None else "",
                    r["status"], "Yes" if r["late"] else "No"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=attendance_{frm}_to_{to}.csv"})


# ---------- admin: settings ----------
@app.get("/api/admin/settings")
@admin_required
def read_settings():
    return jsonify(get_settings())


@app.post("/api/admin/settings")
@admin_required
def save_settings():
    d = request.get_json(force=True)
    try:
        datetime.strptime(d["shift_start"], "%H:%M")
        vals = {"shift_start": d["shift_start"], "grace_min": str(int(d["grace_min"])),
                "full_day_hours": str(float(d["full_day_hours"])), "half_day_hours": str(float(d["half_day_hours"]))}
    except (KeyError, ValueError):
        return jsonify(error="Invalid settings values"), 400
    con = get_db()
    for k, v in vals.items():
        con.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
    con.commit()
    return jsonify(message="Settings saved")


init_db()

if __name__ == "__main__":
    app.run(debug=True)