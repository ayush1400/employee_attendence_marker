const MODEL_URL = "https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/model/";
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const detOpts = () => new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 });

async function loadModels() {
  await Promise.all([
    faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
    faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
    faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
  ]);
}

async function startCamera(video) {
  video.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
}

async function getDescriptor(video) {
  const d = await faceapi.detectSingleFace(video, detOpts()).withFaceLandmarks().withFaceDescriptor();
  return d ? Array.from(d.descriptor) : null;
}

// average several samples for a steadier stored descriptor (used when enrolling)
async function captureAveraged(video, n = 3) {
  const samples = [];
  for (let i = 0; i < n * 3 && samples.length < n; i++) {
    const d = await getDescriptor(video);
    if (d) samples.push(d);
    await sleep(350);
  }
  if (samples.length < n) return null;
  return samples[0].map((_, i) => samples.reduce((s, d) => s + d[i], 0) / samples.length);
}

// Eye Aspect Ratio: drops sharply when the eye closes
function ear(eye) {
  const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  return (d(eye[1], eye[5]) + d(eye[2], eye[4])) / (2 * d(eye[0], eye[3]));
}

// liveness: passes when the person blinks OR turns their head slightly to a side
async function waitForLiveness(video, timeout = 10000, onFace) {
  const end = Date.now() + timeout;
  let maxEar = 0, minYaw = 1, maxYaw = 0;
  while (Date.now() < end) {
    const d = await faceapi.detectSingleFace(video, detOpts()).withFaceLandmarks();
    if (onFace) onFace(d ? d.detection.box : null);
    if (d) {
      const lm = d.landmarks, p = lm.positions;
      // blink: eyes clearly more closed than their open-eye level
      const e = (ear(lm.getLeftEye()) + ear(lm.getRightEye())) / 2;
      maxEar = Math.max(maxEar, e);
      if (maxEar > 0.2 && e < maxEar * 0.8) return true;
      // head turn: nose position between the jaw edges (about 0.5 when facing the camera)
      const yaw = (p[30].x - p[0].x) / (p[16].x - p[0].x);
      minYaw = Math.min(minYaw, yaw);
      maxYaw = Math.max(maxYaw, yaw);
      if (maxYaw - minYaw > 0.12) return true;
    }
    await sleep(30);
  }
  return false;
}

// ---- live face box drawn on a canvas that sits over the video ----
function drawBox(canvas, video, box, color = "#22c55e") {
  if (canvas.width !== video.videoWidth) { canvas.width = video.videoWidth; canvas.height = video.videoHeight; }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!box) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(3, canvas.width / 180);
  ctx.lineJoin = "round";
  ctx.strokeRect(box.x, box.y, box.width, box.height);
}

// keeps the box following the face; isPaused() stops it (e.g. while a scan is running)
function startFaceBox(video, canvas, isPaused = () => false, onChange) {
  let last = false;
  (async function loop() {
    try {
      if (video.videoWidth && !isPaused()) {
        const det = await faceapi.detectSingleFace(video, detOpts());
        drawBox(canvas, video, det && det.box);
        if (onChange && !!det !== last) { last = !!det; onChange(last); }
      }
    } catch (e) { /* keep looping */ }
    setTimeout(loop, 150);
  })();
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

function setMsg(text, type) {
  const m = $("msg");
  m.textContent = text || "";
  m.className = type || "";
}