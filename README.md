# Face Attendance System

A simple, self-hosted attendance system where employees **log in and out with their face**.
Built with Flask, SQLite and [face-api.js](https://github.com/vladmandic/face-api) — no dlib or OpenCV install needed.

## Features

- **Kiosk page** – employees tap Login / Logout; a green box tracks the detected face and a big success screen confirms the result
- **Liveness check** – the person must blink or turn their head slightly before the face is read
- **Admin panel** (password protected)
  - Today view: present, late, absent and still-in counts
  - Employees: register with face, re-enroll a face, deactivate / activate, delete
  - Reports: date range + employee filter, CSV export
  - Settings: shift start, grace minutes, full-day / half-day hours
- **Rules** – one login and one logout per day; no logout without a login; duplicate faces are rejected
- **Status logic** – Late, Present, Half Day, Short, Working, No Logout, Absent

## Tech stack

Python · Flask · SQLite · JavaScript · face-api.js (runs in the browser)

## Quick start

```bash
git clone https://github.com/<your-username>/face-attendance-system.git
cd face-attendance-system
pip install -r requirements.txt
python app.py
```

Open:

- Kiosk: http://localhost:5000
- Admin: http://localhost:5000/admin

The camera only works on `localhost` or over HTTPS. The face-api.js library and models load from a CDN, so the first load needs internet.

### Set the admin password

The default password is `admin123`. Change it before real use.

PowerShell:
```powershell
$env:ADMIN_PASSWORD="your-strong-password"
$env:SECRET_KEY="a-long-random-string"
python app.py
```

macOS / Linux:
```bash
ADMIN_PASSWORD="your-strong-password" SECRET_KEY="a-long-random-string" python app.py
```

## Configuration

| Variable         | Default      | Purpose                                                        |
|------------------|--------------|----------------------------------------------------------------|
| `ADMIN_PASSWORD` | `admin123`   | Admin panel password                                           |
| `SECRET_KEY`     | random       | Signs login sessions (set it so sessions survive restarts)     |
| `FLASK_DEBUG`    | off          | Set to `1` for auto-reload while developing                    |

Face matching strictness is `MATCH_THRESHOLD` in `app.py` (lower = stricter, 0.45 – 0.55 is a sensible range).

## How to use

1. Log in to the admin panel and open the **Employees** tab.
2. Enter name, employee code and department, face the camera and click **Capture & Register**.
3. Employees open the kiosk page, tap **Login** or **Logout**, then blink or turn their head slightly.
4. Review attendance in **Today** and **Reports**, or download a CSV.

## Project structure

```
face-attendance/
├── app.py              # Flask backend + SQLite (API, rules, reports)
├── requirements.txt
├── LICENSE
└── static/
    ├── kiosk.html      # employee login / logout page
    ├── admin.html      # admin panel
    ├── face.js         # face-api.js helpers, face box, liveness check
    └── style.css
```

`attendance.db` is created on first run and is ignored by git.

## API overview

Public:

| Method | Endpoint     | Purpose                                  |
|--------|--------------|------------------------------------------|
| POST   | `/api/mark`  | Login / logout with a face descriptor    |

Admin (session required):

| Method | Endpoint                               | Purpose                         |
|--------|----------------------------------------|---------------------------------|
| POST   | `/api/admin/login`, `/api/admin/logout`| Admin session                   |
| GET/POST | `/api/admin/employees`               | List / register employees       |
| POST   | `/api/admin/employees/<id>/face`       | Re-enroll a face                |
| POST   | `/api/admin/employees/<id>/toggle`     | Activate / deactivate           |
| DELETE | `/api/admin/employees/<id>`            | Delete employee and records     |
| GET    | `/api/admin/summary?date=`             | Daily summary incl. absentees   |
| GET    | `/api/admin/report?from=&to=&code=`    | Attendance report               |
| GET    | `/api/admin/export.csv?from=&to=&code=`| CSV export                      |
| GET/POST | `/api/admin/settings`                | Shift and hours settings        |

## Security and privacy notes

- Face descriptors are **biometric data**. Never commit `attendance.db`, and get employees' consent before storing their faces.
- Face matching runs in the browser and the server trusts the descriptor it receives. This is fine for a trusted office kiosk, not for employees marking attendance from their own devices.
- The liveness check stops simple photo attempts but not video replays. Use a stronger method for high-security use.
- Use HTTPS, a strong `ADMIN_PASSWORD` and a fixed `SECRET_KEY` in any real deployment. Do not run with `FLASK_DEBUG=1` on a public server.

## Limitations and ideas

- One login and one logout per day (no multiple punches)
- No manual correction of punches, per-employee shifts or holidays
- Possible next steps: manual edits, multiple shifts, self-hosted models, email reports

## License
