const state = {
  stream: null,
  socket: null,
  session: null,
  students: [],
  alerts: [],
  waitingFrame: false,
  cameraTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const camera = $("#camera");
const canvas = $("#capture-canvas");
const frame = $("#processed-frame");

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.headers || {}) },
  });
  if (response.status === 401) {
    $("#login-modal").classList.add("visible");
    throw new Error("Phiên đăng nhập đã hết hạn");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Yêu cầu không thành công");
  }
  return response.json();
}

function toast(message, error = false) {
  const item = document.createElement("div");
  item.className = `toast${error ? " error" : ""}`;
  item.textContent = message;
  $("#toast-container").append(item);
  setTimeout(() => item.remove(), 4200);
}

async function login(event) {
  event.preventDefault();
  const password = new FormData(event.target).get("password");
  try {
    await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    $("#login-modal").classList.remove("visible");
    $("#login-error").textContent = "";
    event.target.reset();
    await refreshDashboard();
  } catch (error) {
    $("#login-error").textContent = error.message;
  }
}

async function startCamera() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    camera.srcObject = state.stream;
    await camera.play();
    $("#camera-placeholder").style.display = "none";
    $("#start-camera-button").textContent = "Camera đang bật";
    $("#start-camera-button").disabled = true;
    connectSocket();
  } catch (error) {
    toast(`Không thể mở camera: ${error.message}`, true);
  }
}

function connectSocket() {
  if (!state.stream) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws`);
  state.socket.binaryType = "arraybuffer";
  state.socket.onopen = () => {
    setSocketStatus(true);
    state.cameraTimer = setInterval(sendFrame, 100);
  };
  state.socket.onmessage = ({ data }) => {
    state.waitingFrame = false;
    const payload = JSON.parse(data);
    if (payload.type === "error") {
      toast(payload.message, true);
      return;
    }
    frame.src = `data:image/jpeg;base64,${payload.image}`;
    frame.style.display = "block";
    const errors = [...new Set(payload.errors || [])];
    $("#engine-message").textContent = errors.join(" ");
    for (const alert of payload.alerts || []) addAlert(alert);
    if ((payload.faces || []).some((face) => face.student_id)) refreshSession();
  };
  state.socket.onclose = () => {
    setSocketStatus(false);
    clearInterval(state.cameraTimer);
    state.waitingFrame = false;
    if (state.stream) setTimeout(connectSocket, 1800);
  };
}

function sendFrame() {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN || state.waitingFrame) return;
  if (!camera.videoWidth) return;
  canvas.width = camera.videoWidth;
  canvas.height = camera.videoHeight;
  canvas.getContext("2d").drawImage(camera, 0, 0);
  state.waitingFrame = true;
  canvas.toBlob((blob) => {
    if (!blob || state.socket.readyState !== WebSocket.OPEN) {
      state.waitingFrame = false;
      return;
    }
    state.socket.send(blob);
  }, "image/jpeg", 0.76);
}

function setSocketStatus(online) {
  const item = $("#socket-status");
  item.textContent = online ? "Camera online" : "Camera offline";
  item.className = `status-pill ${online ? "online" : "offline"}`;
}

async function refreshDashboard() {
  await Promise.all([refreshSession(), refreshAlerts()]);
}

async function refreshSession() {
  try {
    state.session = await api("/api/sessions/active");
    state.students = state.session ? state.session.students : await api("/api/students");
    renderSession();
  } catch (error) {
    if (!error.message.includes("hết hạn")) toast(error.message, true);
  }
}

function renderSession() {
  const active = Boolean(state.session);
  const present = state.students.filter((student) => student.is_present).length;
  const called = state.students.filter((student) => student.is_called).length;
  $("#session-stat").textContent = active ? `#${state.session.id} Active` : "Chưa bắt đầu";
  $("#present-stat").textContent = `${present} / ${state.students.length}`;
  $("#called-stat").textContent = String(called);
  $("#start-session-button").disabled = active;
  $("#finish-session-button").disabled = !active;
  $("#pick-button").disabled = !active || !present;
  $("#reset-called-button").disabled = !active || !called;
  $("#student-list").innerHTML = state.students.map((student) => `
    <tr>
      <td><div class="student-cell"><span class="mini-avatar">${initials(student.fullname)}</span>${escapeHtml(student.fullname)}</div></td>
      <td>${escapeHtml(student.student_code)}</td>
      <td><span class="badge ${student.is_present ? "present" : "absent"}">${student.is_present ? "Có mặt" : "Chưa thấy"}</span></td>
      <td>${student.is_called ? '<span class="badge called">Đã gọi</span>' : "-"}</td>
    </tr>
  `).join("") || '<tr><td colspan="4">Chưa có học sinh đăng ký.</td></tr>';
}

async function startSession() {
  try {
    state.session = await api("/api/sessions", { method: "POST" });
    state.students = state.session.students;
    renderSession();
    toast("Đã bắt đầu phiên học");
  } catch (error) { toast(error.message, true); }
}

async function finishSession() {
  if (!state.session) return;
  try {
    await api(`/api/sessions/${state.session.id}/finish`, { method: "POST" });
    state.session = null;
    await refreshSession();
    toast("Đã kết thúc phiên học");
  } catch (error) { toast(error.message, true); }
}

async function pickStudent() {
  if (!state.session) return;
  $("#picker-modal").classList.add("visible");
  $("#picked-name").textContent = "Đang xáo trộn...";
  $("#picked-code").textContent = "";
  try {
    const student = await api(`/api/sessions/${state.session.id}/pick`, { method: "POST" });
    const names = state.students.filter((item) => item.is_present).map((item) => item.fullname);
    let tick = 0;
    const animation = setInterval(() => {
      $("#picked-name").textContent = names[tick++ % names.length] || "Đang chọn...";
    }, 90);
    setTimeout(async () => {
      clearInterval(animation);
      showPickedStudent(student);
      await refreshSession();
    }, 1000);
  } catch (error) {
    $("#picker-modal").classList.remove("visible");
    toast(`${error.message}. Có thể reset lượt gọi để bắt đầu vòng mới.`, true);
  }
}

function showPickedStudent(student) {
  $("#picked-name").textContent = student.fullname;
  $("#picked-code").textContent = student.student_code;
  $("#picked-initials").textContent = initials(student.fullname);
  const image = $("#picked-avatar");
  if (student.avatar_url) {
    image.src = student.avatar_url;
    image.style.display = "block";
  } else {
    image.style.display = "none";
  }
}

async function resetCalled() {
  if (!state.session) return;
  try {
    await api(`/api/sessions/${state.session.id}/reset-called`, { method: "POST" });
    await refreshSession();
    toast("Đã reset lượt gọi");
  } catch (error) { toast(error.message, true); }
}

async function registerStudent(event) {
  event.preventDefault();
  const data = new FormData(event.target);
  if (!data.get("image").size) {
    if (!camera.videoWidth) {
      toast("Hãy bật camera hoặc chọn một ảnh đăng ký", true);
      return;
    }
    canvas.width = camera.videoWidth;
    canvas.height = camera.videoHeight;
    canvas.getContext("2d").drawImage(camera, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    data.set("image", blob, "webcam.jpg");
  }
  try {
    await api("/api/students/register", { method: "POST", body: data });
    event.target.reset();
    $("#register-form").classList.add("hidden");
    await refreshSession();
    toast("Đã đăng ký học sinh");
  } catch (error) { toast(error.message, true); }
}

async function refreshAlerts() {
  try {
    state.alerts = await api("/api/behaviors");
    renderAlerts();
  } catch (error) {
    if (!error.message.includes("hết hạn")) toast(error.message, true);
  }
}

function addAlert(alert) {
  state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 30);
  renderAlerts();
  toast(`${alert.label}: ${alert.fullname}`, true);
}

function renderAlerts() {
  $("#alert-stat").textContent = String(state.alerts.length);
  $("#alert-list").innerHTML = state.alerts.map((alert) => `
    <div class="alert-item">
      <strong>${escapeHtml(alert.label || alert.behavior_type)} · ${escapeHtml(alert.fullname)}</strong>
      <span>${alert.timestamp ? new Date(alert.timestamp).toLocaleString("vi-VN") : "Vừa phát hiện"}</span>
    </div>
  `).join("") || '<span class="badge absent">Chưa có cảnh báo</span>';
}

function initials(name) {
  return name.split(/\s+/).slice(-2).map((part) => part[0]).join("").toUpperCase();
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value || "";
  return span.innerHTML;
}

$("#login-form").addEventListener("submit", login);
$("#start-camera-button").addEventListener("click", startCamera);
$("#start-session-button").addEventListener("click", startSession);
$("#finish-session-button").addEventListener("click", finishSession);
$("#pick-button").addEventListener("click", pickStudent);
$("#reset-called-button").addEventListener("click", resetCalled);
$("#close-picker-button").addEventListener("click", () => $("#picker-modal").classList.remove("visible"));
$("#toggle-register-button").addEventListener("click", () => $("#register-form").classList.toggle("hidden"));
$("#register-form").addEventListener("submit", registerStudent);
$("#logout-button").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

api("/api/auth/status")
  .then(() => {
    $("#login-modal").classList.remove("visible");
    refreshDashboard();
  })
  .catch(() => $("#login-modal").classList.add("visible"));
