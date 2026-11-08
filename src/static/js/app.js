const state = {
  stream: null,
  socket: null,
  session: null,
  students: [],
  classes: [],
  classId: null,
  serverSpeech: false,
  alerts: [],
  waitingFrame: false,
  cameraTimer: null,
  enabledBehaviors: new Set(["SLEEPING", "HAND_ON_FACE", "CHEATING", "TALKING"]),
  videoDevices: [],
  // Adaptive sending: round-trip time drives the upload resolution.
  sentAt: 0,
  rttEma: null,
  maxDim: 640,
  framesSinceAdapt: 0,
  // Client-side overlay drawn over the live <video>.
  lastPayload: null,
  lastPayloadAt: 0,
  alertLabels: new Map(),
};

const $ = (selector) => document.querySelector(selector);
const camera = $("#camera");
const canvas = $("#capture-canvas");
const frame = $("#processed-frame");
const overlay = $("#overlay-canvas");
const THEME_STORAGE_KEY = "smart-classroom-theme";
// ?overlay=server keeps the legacy mode where the server returns an annotated JPEG.
const SERVER_OVERLAY = new URLSearchParams(location.search).get("overlay") === "server";
const UPLOAD_SIZES = [640, 480, 360];
const OVERLAY_STALE_MS = 1500;
const ALERT_LABEL_MS = 3000;
const FRAME_TIMEOUT_MS = 5000;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.headers || {}) },
  });
  if (response.status === 401) {
    const body = await response.json().catch(() => ({}));
    $("#login-modal").classList.add("visible");
    // A wrong password is not an expired session: show the server's reason.
    if (path === "/api/auth/login") throw new Error(body.detail || "Mật khẩu không chính xác");
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

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  overlayColors = null; // re-read palette tokens for the canvas overlay
  localStorage.setItem(THEME_STORAGE_KEY, theme);
  const select = $("#theme-select-modal");
  if (select) {
    select.value = theme;
  }
}

async function login(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
    });
    $("#login-modal").classList.remove("visible");
    $("#login-error").textContent = "";
    event.target.reset();
    await loadCurrentUser();
    await refreshDashboard();
  } catch (error) {
    $("#login-error").textContent = error.message;
  }
}

async function loadCurrentUser() {
  const { user } = await api("/api/auth/status");
  state.user = user;
  $("#current-user").textContent = user.fullname;
  $("#admin-button").classList.toggle("hidden", user.role !== "ADMIN");
}

const ROLE_TEXT = { ADMIN: "Quản trị", TEACHER: "Giáo viên" };

async function refreshUsers() {
  const users = await api("/api/users");
  state.users = users;
  $("#admin-users").innerHTML = users.map((user) => `
    <tr>
      <td>${escapeHtml(user.username)}</td>
      <td>${escapeHtml(user.fullname)}</td>
      <td>${ROLE_TEXT[user.role] || escapeHtml(user.role)}</td>
      <td><span class="badge ${user.is_active ? "present" : "warn"}">${user.is_active ? "Hoạt động" : "Đã khóa"}</span></td>
      <td><div class="row-actions">
        <button type="button" class="button ghost" data-user-password="${user.id}">Đặt lại mật khẩu</button>
        <button type="button" class="button ${user.is_active ? "danger" : "ghost"}" data-user-toggle="${user.id}" data-active="${user.is_active ? "1" : "0"}">${user.is_active ? "Khóa" : "Mở khóa"}</button>
      </div></td>
    </tr>
  `).join("");
}

async function openAdmin() {
  try {
    await refreshAdmin();
    $("#admin-modal").classList.add("visible");
  } catch (error) { toast(error.message, true); }
}

async function refreshAdmin() {
  await refreshUsers();
  await refreshClasses();
  const entries = await api("/api/access-logs");
  $("#admin-access-list").innerHTML = entries.map((entry) => `
    <tr>
      <td>${formatDateTime(entry.created_at)}</td>
      <td>${escapeHtml(entry.username)}</td>
      <td>${entry.action === "VIEW_SNAPSHOT" ? "Xem ảnh bằng chứng" : "Xem ảnh đại diện"}</td>
    </tr>
  `).join("") || '<tr><td colspan="3" class="empty-row">Chưa có lượt xem ảnh nào.</td></tr>';
  const teachers = state.users.filter((user) => user.role === "TEACHER" && user.is_active);
  $("#admin-class-list").innerHTML = state.classes.map((item) => `
    <article class="admin-class" data-class-row="${item.id}">
      <header>
        <span>${escapeHtml(item.name)}${item.school_year ? ` · ${escapeHtml(item.school_year)}` : ""}</span>
        <span>${item.student_count} học sinh</span>
      </header>
      <div class="admin-class-teachers">
        ${teachers.map((teacher) => `
          <label class="checkbox-label">
            <input type="checkbox" data-class-teacher="${item.id}" value="${teacher.id}" ${item.teacher_ids.includes(teacher.id) ? "checked" : ""} />
            <span>${escapeHtml(teacher.fullname)}</span>
          </label>
        `).join("") || "<span>Chưa có tài khoản giáo viên.</span>"}
      </div>
      <form class="add-student-form" data-class-add="${item.id}">
        <input aria-label="Mã học sinh" placeholder="Mã học sinh có sẵn" maxlength="20" required />
        <button class="button ghost" type="submit">Thêm vào lớp</button>
      </form>
    </article>
  `).join("");
}

async function createClass(event) {
  event.preventDefault();
  try {
    await api("/api/classes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#new-class-name").value,
        school_year: $("#new-class-year").value || null,
      }),
    });
    event.target.reset();
    await refreshAdmin();
    toast("Đã thêm lớp");
  } catch (error) { toast(error.message, true); }
}

async function onClassTeacherChange(event) {
  const box = event.target.closest("[data-class-teacher]");
  if (!box) return;
  try {
    await api(`/api/classes/${box.dataset.classTeacher}/teachers/${box.value}`, {
      method: box.checked ? "PUT" : "DELETE",
    });
  } catch (error) {
    box.checked = !box.checked;
    toast(error.message, true);
  }
}

async function onAddStudentToClass(event) {
  const form = event.target.closest("[data-class-add]");
  if (!form) return;
  event.preventDefault();
  try {
    await api(`/api/classes/${form.dataset.classAdd}/students`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_code: form.querySelector("input").value }),
    });
    await refreshAdmin();
    await refreshSession();
    toast("Đã thêm học sinh vào lớp");
  } catch (error) { toast(error.message, true); }
}

async function createUser(event) {
  event.preventDefault();
  try {
    await api("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("#new-user-username").value,
        fullname: $("#new-user-fullname").value,
        password: $("#new-user-password").value,
        role: $("#new-user-role").value,
      }),
    });
    event.target.reset();
    await refreshAdmin();
    toast("Đã thêm tài khoản");
  } catch (error) { toast(error.message, true); }
}

async function updateUser(userId, changes) {
  await api(`/api/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

async function onAdminUsersClick(event) {
  const toggle = event.target.closest("[data-user-toggle]");
  const reset = event.target.closest("[data-user-password]");
  try {
    if (toggle) {
      await updateUser(Number(toggle.dataset.userToggle), { is_active: toggle.dataset.active !== "1" });
      await refreshAdmin();
    } else if (reset) {
      const password = window.prompt("Mật khẩu mới (từ 8 ký tự):", "");
      if (!password) return;
      await updateUser(Number(reset.dataset.userPassword), { password });
      toast("Đã đặt lại mật khẩu");
    }
  } catch (error) { toast(error.message, true); }
}

async function refreshVideoDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    state.videoDevices = devices.filter(device => device.kind === "videoinput");
    
    const select = $("#video-source-select-modal");
    if (!select) return;
    const currentSelected = select.value;
    
    select.innerHTML = state.videoDevices.map((device, index) => `
      <option value="${device.deviceId}" ${device.deviceId === currentSelected ? "selected" : ""}>
        ${device.label || `Camera ${index + 1}`}
      </option>
    `).join("") || '<option value="">Không tìm thấy camera</option>';
  } catch (error) {
    console.warn("Lỗi tải danh sách camera:", error);
  }
}

async function onVideoSourceChange() {
  if (state.stream) {
    stopCamera();
    await startCamera();
  }
}

async function startCamera() {
  if (state.stream) return;
  if (!state.classId) {
    toast("Hãy chọn lớp trước khi bật camera", true);
    return;
  }
  try {
    const select = $("#video-source-select-modal");
    const deviceId = select ? select.value : "";
    const constraints = {
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        ...(deviceId ? { deviceId: { exact: deviceId } } : {})
      },
      audio: false,
    };
    state.stream = await navigator.mediaDevices.getUserMedia(constraints);
    camera.srcObject = state.stream;
    await camera.play();
    $("#camera-placeholder").style.display = "none";
    $("#start-camera-button .label").textContent = "Camera đang bật";
    $("#start-camera-button").disabled = true;
    $("#stop-camera-button").disabled = false;
    
    await refreshVideoDevices();
    connectSocket();
  } catch (error) {
    toast(`Không thể mở camera: ${error.message}`, true);
  }
}

function stopCamera() {
  clearInterval(state.cameraTimer);
  state.cameraTimer = null;
  if (state.socket) {
    state.socket.onclose = null;
    state.socket.close();
    state.socket = null;
  }
  if (state.stream) {
    for (const track of state.stream.getTracks()) track.stop();
    state.stream = null;
  }
  camera.srcObject = null;
  state.waitingFrame = false;
  state.rttEma = null;
  state.lastPayload = null;
  state.alertLabels.clear();
  clearOverlay();
  frame.removeAttribute("src");
  frame.style.display = "none";
  $("#camera-placeholder").style.display = "grid";
  $("#start-camera-button .label").textContent = "Bật camera";
  $("#start-camera-button").disabled = false;
  $("#stop-camera-button").disabled = true;
  $("#engine-message").textContent = "";
  setSocketStatus(false);
}

function connectSocket() {
  if (!state.stream) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ class_id: state.classId });
  if (SERVER_OVERLAY) params.set("overlay", "server");
  state.socket = new WebSocket(`${protocol}://${location.host}/ws?${params}`);
  state.socket.binaryType = "arraybuffer";
  state.socket.onopen = () => {
    setSocketStatus(true);
    sendBehaviorConfig();
    restartCameraTimer();
  };
  state.socket.onmessage = ({ data }) => {
    state.waitingFrame = false;
    const payload = JSON.parse(data);
    if (payload.type === "error") {
      toast(payload.message, true);
      return;
    }
    if (payload.type === "behavior_config") {
      state.enabledBehaviors = new Set(payload.enabled_behaviors);
      renderBehaviorOptions();
      return;
    }
    recordRoundTrip();
    if (payload.image) {
      frame.src = `data:image/jpeg;base64,${payload.image}`;
      frame.style.display = "block";
    } else {
      state.lastPayload = payload;
      state.lastPayloadAt = performance.now();
      rememberAlertLabels(payload);
      drawOverlay();
    }
    const errors = [...new Set(payload.errors || [])];
    $("#engine-message").textContent = errors.join(" ");
    for (const alert of payload.alerts || []) addAlert(alert);
    
    state.lastFaceDetected = (payload.faces || []).length > 0;
    updatePickButtonState();
    // Refresh the roster only when the server reports a change instead of
    // polling the API on every frame that contains a recognised face.
    const checkedIn = payload.attendance || [];
    for (const item of checkedIn) announceCheckIn(item);
    const sessionChanged = (payload.session_id || null) !== (state.session ? state.session.id : null);
    if (checkedIn.length || sessionChanged) refreshSession();
  };
  state.socket.onclose = () => {
    state.socket = null;
    clearOverlay();
    setSocketStatus(false);
    clearInterval(state.cameraTimer);
    state.cameraTimer = null;
    state.waitingFrame = false;
    if (state.stream) setTimeout(connectSocket, 1800);
  };
}

function toggleBehavior(event) {
  const behaviorType = event.currentTarget.dataset.behavior;
  if (state.enabledBehaviors.has(behaviorType)) {
    state.enabledBehaviors.delete(behaviorType);
  } else {
    state.enabledBehaviors.add(behaviorType);
  }
  renderBehaviorOptions();
  sendBehaviorConfig();
}

function renderBehaviorOptions() {
  for (const button of document.querySelectorAll(".behavior-toggle")) {
    const active = state.enabledBehaviors.has(button.dataset.behavior);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function sendBehaviorConfig() {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
  state.socket.send(JSON.stringify({
    type: "behavior_config",
    enabled_behaviors: [...state.enabledBehaviors],
  }));
}

function sendFrame() {
  if (performance.now() - state.lastPayloadAt > OVERLAY_STALE_MS) clearOverlay();
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
  if (state.waitingFrame && performance.now() - state.sentAt > FRAME_TIMEOUT_MS) {
    state.waitingFrame = false; // response lost: do not stall the stream forever
  }
  if (state.waitingFrame || document.hidden || !camera.videoWidth) return;

  // Downscale before upload; the width adapts to the measured round-trip time.
  const maxDim = state.maxDim;
  let w = camera.videoWidth;
  let h = camera.videoHeight;
  if (w > maxDim) {
    h = Math.round((h * maxDim) / w);
    w = maxDim;
  }
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d").drawImage(camera, 0, 0, w, h);
  state.waitingFrame = true;
  state.sentAt = performance.now();
  canvas.toBlob((blob) => {
    if (!blob || !state.socket || state.socket.readyState !== WebSocket.OPEN) {
      state.waitingFrame = false;
      return;
    }
    state.socket.send(blob);
  }, "image/jpeg", 0.70);
}

function recordRoundTrip() {
  const rtt = performance.now() - state.sentAt;
  state.rttEma = state.rttEma === null ? rtt : state.rttEma * 0.8 + rtt * 0.2;
  state.framesSinceAdapt += 1;
  if (state.framesSinceAdapt >= 30) {
    state.framesSinceAdapt = 0;
    const index = UPLOAD_SIZES.indexOf(state.maxDim);
    if (state.rttEma > 350 && index < UPLOAD_SIZES.length - 1) state.maxDim = UPLOAD_SIZES[index + 1];
    else if (state.rttEma < 150 && index > 0) state.maxDim = UPLOAD_SIZES[index - 1];
  }
  setSocketStatus(true);
}

let overlayColors = null;

function readOverlayColors() {
  const styles = getComputedStyle(document.documentElement);
  const light = document.documentElement.dataset.theme === "light";
  overlayColors = {
    known: styles.getPropertyValue("--green").trim() || "#38e6a1",
    unknown: styles.getPropertyValue("--amber").trim() || "#ffbd4a",
    alert: styles.getPropertyValue("--red").trim() || "#ff5f77",
    // Label text sits on a solid pill of the box color.
    labelText: light ? "#ffffff" : "#04121b",
    font: `600 16px ${styles.fontFamily || "system-ui, sans-serif"}`,
  };
}

function rememberAlertLabels(payload) {
  const now = performance.now();
  for (const behavior of payload.behaviors || []) {
    if (behavior.alerts && behavior.alerts.length) {
      state.alertLabels.set(behavior.track_id, { types: behavior.alerts, until: now + ALERT_LABEL_MS });
    }
  }
  for (const [trackId, label] of state.alertLabels) {
    if (label.until < now) state.alertLabels.delete(trackId);
  }
}

function clearOverlay() {
  const context = overlay.getContext("2d");
  context.clearRect(0, 0, overlay.width, overlay.height);
}

function drawLabel(context, text, x, y, color, above) {
  context.font = overlayColors.font;
  const width = context.measureText(text).width + 12;
  const height = 26;
  const top = above ? Math.max(0, y - height - 3) : y + 3;
  context.fillStyle = color;
  context.beginPath();
  if (context.roundRect) context.roundRect(x, top, width, height, 5);
  else context.rect(x, top, width, height);
  context.fill();
  context.fillStyle = overlayColors.labelText;
  context.textBaseline = "middle";
  context.fillText(text, x + 6, top + height / 2 + 0.5);
}

function drawOverlay() {
  const payload = state.lastPayload;
  if (!payload || !payload.frame_size) return;
  if (!overlayColors) readOverlayColors();
  const ratio = window.devicePixelRatio || 1;
  const cssWidth = overlay.clientWidth;
  const cssHeight = overlay.clientHeight;
  if (overlay.width !== Math.round(cssWidth * ratio) || overlay.height !== Math.round(cssHeight * ratio)) {
    overlay.width = Math.round(cssWidth * ratio);
    overlay.height = Math.round(cssHeight * ratio);
  }
  const context = overlay.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, cssWidth, cssHeight);

  // The <video> uses object-fit: cover, so map frame pixels the same way.
  const { width: frameWidth, height: frameHeight } = payload.frame_size;
  const scale = Math.max(cssWidth / frameWidth, cssHeight / frameHeight);
  const offsetX = (cssWidth - frameWidth * scale) / 2;
  const offsetY = (cssHeight - frameHeight * scale) / 2;
  const toScreen = (box) => ({
    x: offsetX + box.x * scale,
    y: offsetY + box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
  });

  context.lineWidth = 2;
  for (const face of payload.faces || []) {
    const box = toScreen(face.box);
    const color = face.student_id ? overlayColors.known : overlayColors.unknown;
    context.strokeStyle = color;
    context.strokeRect(box.x, box.y, box.width, box.height);
    const known = isTvDisplay() ? "Đã nhận diện" : `${face.fullname} ${Math.round(face.confidence)}%`;
    const label = face.student_id ? known : "Không rõ";
    drawLabel(context, label, box.x, box.y, color, true);
  }
  for (const behavior of payload.behaviors || []) {
    const label = state.alertLabels.get(behavior.track_id);
    if (!label || namesHidden()) continue;
    const box = toScreen(behavior.box);
    const text = label.types.map((type) => BEHAVIOR_TEXT[type] || type).join(", ");
    drawLabel(context, text, box.x, box.y + box.height, overlayColors.alert, false);
  }
}

const BEHAVIOR_TEXT = {
  SLEEPING: "Ngủ gục",
  HAND_ON_FACE: "Chống tay",
  CHEATING: "Quay cóp",
  TALKING: "Nói chuyện",
};

function setSocketStatus(online) {
  const item = $("#socket-status");
  const latency = online && state.rttEma !== null ? ` · ${Math.round(state.rttEma)} ms` : "";
  item.textContent = online ? `Camera trực tuyến${latency}` : "Camera ngoại tuyến";
  item.className = `status-pill ${online ? "online" : "offline"}`;
}

async function refreshDashboard() {
  await refreshClasses();
  await Promise.all([refreshSession(), refreshAlerts(), refreshSpeechStatus()]);
}

const CLASS_STORAGE_KEY = "smart-classroom-class";

async function refreshClasses() {
  state.classes = await api("/api/classes");
  const saved = Number(state.classId || localStorage.getItem(CLASS_STORAGE_KEY));
  const current = state.classes.find((item) => item.id === saved) || state.classes[0];
  state.classId = current ? current.id : null;
  $("#class-select").innerHTML = state.classes.map((item) => `
    <option value="${item.id}" ${item.id === state.classId ? "selected" : ""}>${escapeHtml(item.name)}</option>
  `).join("");
}

async function onClassChange(event) {
  state.classId = Number(event.target.value);
  localStorage.setItem(CLASS_STORAGE_KEY, String(state.classId));
  const streaming = Boolean(state.stream);
  if (streaming) stopCamera();
  state.session = null;
  await Promise.all([refreshSession(), refreshAlerts()]);
  if (streaming) await startCamera();
}

async function refreshSession() {
  if (state.refreshingSession) {
    state.refreshQueued = true;
    return;
  }
  state.refreshingSession = true;
  try {
    const previousId = state.session ? state.session.id : null;
    if (state.classId) {
      state.session = await api(`/api/sessions/active?class_id=${state.classId}`);
      state.students = state.session ? state.session.students : await api(`/api/students?class_id=${state.classId}`);
    } else {
      state.session = null;
      state.students = [];
    }
    renderSession();
    if ((state.session ? state.session.id : null) !== previousId) refreshAlerts();
  } catch (error) {
    if (!error.message.includes("hết hạn")) toast(error.message, true);
  } finally {
    state.refreshingSession = false;
    if (state.refreshQueued) {
      state.refreshQueued = false;
      refreshSession();
    }
  }
}

function updatePickButtonState() {
  const active = Boolean(state.session);
  const faceDetected = state.lastFaceDetected || false;
  const button = $("#pick-button");
  if (button) {
    button.disabled = !active && !faceDetected;
  }
}

function formatTime(value) {
  return value ? new Date(value).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) : "";
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString("vi-VN") : "";
}

function attendanceBadge(student, active) {
  let label = "Chưa thấy";
  let css = "absent";
  if (student.is_present) {
    label = student.is_late ? "Đi muộn" : "Có mặt";
    css = student.is_late ? "late" : "present";
  } else if (student.attendance_source === "MANUAL") {
    label = "Vắng";
    css = "warn";
  }
  if (!active) return `<span class="badge ${css}">${label}</span>`;
  const title = student.is_present ? "Bấm để đánh dấu vắng" : "Bấm để xác nhận có mặt";
  return `<button type="button" class="badge ${css}" data-attendance="${student.id}" data-present="${student.is_present ? "1" : "0"}" title="${title}">${label}</button>`;
}

function renderSession() {
  const active = Boolean(state.session);
  const summary = active ? state.session.summary : null;
  const present = state.students.filter((student) => student.is_present).length;
  const called = state.students.filter((student) => student.is_called).length;
  const sessionName = active ? (state.session.title || `Phiên #${state.session.id}`) : "Chưa bắt đầu";
  $("#session-stat").textContent = sessionName;
  $("#present-stat").textContent = summary && summary.late
    ? `${present} / ${state.students.length} (${summary.late} muộn)`
    : `${present} / ${state.students.length}`;
  $("#called-stat").textContent = String(called);
  if (summary) $("#alert-stat").textContent = String(summary.behaviors);
  $("#session-meta").textContent = active
    ? `Bắt đầu lúc ${formatTime(state.session.created_at)} · tính muộn sau ${state.session.late_after_minutes} phút`
    : "";
  $("#session-title-input").disabled = active;
  $("#start-session-button").disabled = active;
  $("#finish-session-button").disabled = !active;
  $("#export-session-button").disabled = !active;
  $("#attendance-hint").style.visibility = active ? "visible" : "hidden";
  const waiting = state.students.filter((student) => student.consent_status === "PENDING").length;
  $("#consent-note").textContent = waiting ? `${waiting} học sinh chờ đồng ý: camera chưa nhận diện các em này` : "";
  updatePickButtonState();
  $("#reset-called-button").disabled = !active || !called;
  $("#student-list").innerHTML = state.students.map((student) => `
    <tr>
      <td><div class="student-cell"><span class="mini-avatar">${escapeHtml(initials(student.fullname))}</span><span>${escapeHtml(student.fullname)}${student.has_face ? "" : '<span class="source-tag missing-face">Chưa có ảnh khuôn mặt</span>'}</span></div></td>
      <td>${escapeHtml(student.student_code)}</td>
      <td>${active ? attendanceBadge(student, true) : '<span class="badge absent">-</span>'}${student.note ? `<span class="source-tag desk-only">${escapeHtml(student.note)}</span>` : ""}</td>
      <td>${student.checked_in_at ? `${formatTime(student.checked_in_at)}<span class="source-tag">${student.attendance_source === "MANUAL" ? "Giáo viên" : "Camera"}</span>` : "-"}</td>
      <td>${student.is_called
        ? `<span class="badge called">Đã gọi</span><span class="source-tag">${formatTime(student.called_at)}</span>`
        : student.called_at ? `<span class="source-tag">Vòng trước · ${formatTime(student.called_at)}</span>` : "-"}</td>
      <td class="desk-only">${consentSelect(student)}</td>
      <td class="desk-only"><div class="row-actions">
        <button type="button" class="button ghost" data-reenroll="${student.id}" title="Cập nhật ảnh khuôn mặt">${student.has_face ? "Ảnh" : "+ Ảnh"}</button>
        <button type="button" class="button danger" data-delete="${student.id}" title="Xóa học sinh">Xóa</button>
      </div></td>
    </tr>
  `).join("") || `<tr><td colspan="7" class="empty-row">${state.classId ? "Chưa có học sinh. Bấm nút + ở mục Đăng ký học sinh để thêm." : "Bạn chưa được phân công lớp nào. Hãy liên hệ Quản trị."}</td></tr>`;
}

const CONSENT_TEXT = {
  PENDING: "Chờ xác nhận",
  GRANTED: "Đã đồng ý",
  REFUSED: "Từ chối",
  WITHDRAWN: "Đã rút",
};

function consentSelect(student) {
  const options = Object.entries(CONSENT_TEXT).map(([value, label]) => `
    <option value="${value}" ${value === student.consent_status ? "selected" : ""} ${value === "PENDING" ? "disabled" : ""}>${label}</option>
  `).join("");
  return `<select class="select-field consent-select" data-consent="${student.id}" aria-label="Đồng ý của ${escapeHtml(student.fullname)}">${options}</select>`;
}

async function onConsentChange(event) {
  const select = event.target.closest("[data-consent]");
  if (!select) return;
  const student = state.students.find((item) => item.id === Number(select.dataset.consent));
  const erases = select.value !== "GRANTED";
  if (erases && !window.confirm(`Ảnh khuôn mặt và ảnh bằng chứng của ${student.fullname} sẽ bị xóa. Lịch sử điểm danh được giữ lại. Tiếp tục?`)) {
    await refreshSession();
    return;
  }
  try {
    await api(`/api/students/${student.id}/consent`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: select.value }),
    });
    await refreshSession();
    if (erases) await refreshAlerts();
    toast("Đã ghi nhận trạng thái đồng ý");
  } catch (error) {
    toast(error.message, true);
    await refreshSession();
  }
}

async function toggleAttendance(studentId, currentlyPresent) {
  if (!state.session) return;
  const student = state.students.find((item) => item.id === studentId);
  let note = null;
  if (currentlyPresent) {
    note = window.prompt(`Đánh dấu ${student ? student.fullname : "học sinh"} vắng. Lý do (không bắt buộc, VD: có phép):`, "");
    if (note === null) return;
  }
  try {
    await api(`/api/sessions/${state.session.id}/attendance/${studentId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ present: !currentlyPresent, note: note || null }),
    });
    await refreshSession();
  } catch (error) { toast(error.message, true); }
}

async function deleteStudent(studentId) {
  const student = state.students.find((item) => item.id === studentId);
  const name = student ? student.fullname : "học sinh này";
  if (!window.confirm(`Xóa ${name}? Ảnh khuôn mặt và lịch sử điểm danh của học sinh sẽ bị xóa.`)) return;
  try {
    await api(`/api/students/${studentId}?class_id=${state.classId}`, { method: "DELETE" });
    await refreshSession();
    toast(`Đã xóa ${name}`);
  } catch (error) { toast(error.message, true); }
}

async function captureCameraBlob() {
  if (!state.stream || !camera.videoWidth) return null;
  canvas.width = camera.videoWidth;
  canvas.height = camera.videoHeight;
  canvas.getContext("2d").drawImage(camera, 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
}

async function uploadFace(studentId, blob, filename) {
  const data = new FormData();
  data.set("image", blob, filename);
  try {
    await api(`/api/students/${studentId}/face`, { method: "POST", body: data });
    await refreshSession();
    toast("Đã cập nhật ảnh khuôn mặt");
  } catch (error) { toast(error.message, true); }
}

async function reenrollStudent(studentId) {
  const student = state.students.find((item) => item.id === studentId);
  if (student && student.consent_status !== "GRANTED") {
    toast("Cần ghi nhận đồng ý của phụ huynh trước khi lưu ảnh khuôn mặt", true);
    return;
  }
  const blob = await captureCameraBlob();
  if (blob && window.confirm("Chụp ảnh khuôn mặt từ camera đang bật? (Chọn Hủy để tải ảnh từ máy)")) {
    await uploadFace(studentId, blob, "webcam.jpg");
    return;
  }
  const input = $("#reenroll-input");
  input.dataset.studentId = String(studentId);
  input.value = "";
  input.click();
}

function onStudentListClick(event) {
  const attendance = event.target.closest("[data-attendance]");
  if (attendance) {
    toggleAttendance(Number(attendance.dataset.attendance), attendance.dataset.present === "1");
    return;
  }
  const reenroll = event.target.closest("[data-reenroll]");
  if (reenroll) {
    reenrollStudent(Number(reenroll.dataset.reenroll));
    return;
  }
  const remove = event.target.closest("[data-delete]");
  if (remove) deleteStudent(Number(remove.dataset.delete));
}

function summaryGrid(summary) {
  const cells = [
    ["Sĩ số", summary.total],
    ["Có mặt", summary.present],
    ["Đi muộn", summary.late],
    ["Vắng", summary.absent],
    ["Đã gọi", summary.called],
    ["Cảnh báo", summary.behaviors],
  ];
  return `<div class="report-grid">${cells.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}</div>`;
}

function exportSession(sessionId) {
  window.location.href = `/api/sessions/${sessionId}/export.csv`;
}

async function showSessionReport(sessionId) {
  try {
    const detail = await api(`/api/sessions/${sessionId}`);
    const absent = detail.students.filter((student) => !student.is_present);
    $("#report-title").textContent = detail.title || `Phiên #${detail.id}`;
    $("#report-body").innerHTML = `
      <span class="report-meta">${formatDateTime(detail.created_at)}${detail.finished_at ? ` → ${formatTime(detail.finished_at)}` : " · đang diễn ra"}</span>
      ${summaryGrid(detail.summary)}
      <div><strong>Học sinh vắng (${absent.length})</strong>
        ${absent.length ? `<ul class="absent-list">${absent.map((student) => `<li>${escapeHtml(student.fullname)} (${escapeHtml(student.student_code)})${student.note ? `<span class="desk-only"> – ${escapeHtml(student.note)}</span>` : ""}</li>`).join("")}</ul>` : '<p class="report-none">Không có.</p>'}
      </div>
      <button type="button" class="button secondary full" data-export="${detail.id}">Tải bảng điểm danh (CSV/Excel)</button>
    `;
    $("#report-modal").classList.add("visible");
  } catch (error) { toast(error.message, true); }
}

async function showHistory() {
  try {
    const sessions = await api(`/api/sessions?limit=30&class_id=${state.classId}`);
    $("#report-title").textContent = "Các phiên học gần đây";
    $("#report-body").innerHTML = sessions.map((item) => `
      <div class="history-item">
        <div>
          <strong>${escapeHtml(item.title || `Phiên #${item.id}`)}</strong>
          <small>${formatDateTime(item.created_at)} · ${item.status === "ACTIVE" ? "Đang diễn ra" : "Đã kết thúc"}</small>
          <small>Có mặt ${item.summary.present}/${item.summary.total} · muộn ${item.summary.late} · cảnh báo ${item.summary.behaviors}</small>
        </div>
        <div class="row-actions">
          <button type="button" class="button ghost" data-report="${item.id}">Chi tiết</button>
          <button type="button" class="button ghost" data-export="${item.id}">CSV</button>
        </div>
      </div>
    `).join("") || "<p>Chưa có phiên học nào.</p>";
    $("#report-modal").classList.add("visible");
  } catch (error) { toast(error.message, true); }
}

function onReportClick(event) {
  const exportButton = event.target.closest("[data-export]");
  if (exportButton) {
    exportSession(exportButton.dataset.export);
    return;
  }
  const report = event.target.closest("[data-report]");
  if (report) showSessionReport(report.dataset.report);
}

async function createSession() {
  const title = $("#session-title-input").value.trim();
  state.session = await api("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ class_id: state.classId, title: title || null }),
  });
  state.students = state.session.students;
  renderSession();
  refreshAlerts();
}

async function startSession() {
  try {
    await createSession();
    toast("Đã bắt đầu phiên học");
    if (!state.stream) toast("Bật camera để hệ thống tự động điểm danh");
  } catch (error) { toast(error.message, true); }
}

async function finishSession() {
  if (!state.session) return;
  const unrecorded = state.students.filter(
    (student) => !student.is_present && student.attendance_source !== "MANUAL",
  ).length;
  const message = unrecorded
    ? `Kết thúc phiên? Còn ${unrecorded} học sinh chưa được điểm danh và sẽ được ghi nhận là vắng.`
    : "Kết thúc phiên học?";
  if (!window.confirm(message)) return;
  try {
    const finished = await api(`/api/sessions/${state.session.id}/finish`, { method: "POST" });
    state.session = null;
    $("#session-title-input").value = "";
    await refreshSession();
    toast("Đã kết thúc phiên học");
    showSessionReport(finished.id);
  } catch (error) { toast(error.message, true); }
}

async function pickStudent() {
  let sessionId = state.session ? state.session.id : null;
  if (!sessionId) {
    try {
      await createSession();
      sessionId = state.session.id;
      toast("Đã tự động bắt đầu phiên học mới");
    } catch (error) {
      toast(error.message, true);
      return;
    }
  }

  $("#picker-modal").classList.add("visible");
  $("#picked-name").textContent = "Đang xáo trộn...";
  $("#picked-code").textContent = "";

  const initialsEl = $("#picked-initials");
  const avatarRing = $(".avatar-ring");
  const nameEl = $("#picked-name");

  if (initialsEl) {
    initialsEl.textContent = "?";
    initialsEl.style.display = "block"; // a previous pick with a photo hides it
  }
  if (avatarRing) {
    avatarRing.style.borderColor = "var(--blue)";
  }
  $("#picked-avatar").style.display = "none";

  try {
    const student = await api(`/api/sessions/${sessionId}/pick`, { method: "POST" });
    const allNames = state.students.map((item) => item.fullname);

    // Audio synthesizer for visual effects
    const playTick = (freq) => {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.setValueAtTime(freq, ctx.currentTime);
        gain.gain.setValueAtTime(0.04, ctx.currentTime);
        osc.start();
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.04);
        osc.stop(ctx.currentTime + 0.05);
      } catch (e) {}
    };

    const playTada = () => {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const now = ctx.currentTime;
        const playNote = (freq, start, duration) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.type = "triangle";
          osc.frequency.setValueAtTime(freq, start);
          gain.gain.setValueAtTime(0.08, start);
          gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
          osc.start(start);
          osc.stop(start + duration);
        };
        playNote(523.25, now, 0.15);       // C5
        playNote(659.25, now + 0.12, 0.15); // E5
        playNote(783.99, now + 0.24, 0.35); // G5
      } catch (e) {}
    };

    const colors = ["var(--blue)", "var(--green)", "var(--amber)", "var(--red)", "#b388ff", "#ff80ab", "#00e5ff"];
    let tick = 0;
    let delay = 40;

    const animate = () => {
      if (allNames.length > 0) {
        const randomName = allNames[Math.floor(Math.random() * allNames.length)];
        nameEl.textContent = randomName;
        if (initialsEl) initialsEl.textContent = initials(randomName);
      }

      const color = colors[tick % colors.length];
      if (avatarRing) {
        avatarRing.style.borderColor = color;
      }

      playTick(800 + (tick % 4) * 100);
      tick++;

      if (delay < 350) {
        delay += tick * 1.5;
        setTimeout(animate, delay);
      } else {
        showPickedStudent(student);
        if (avatarRing) {
          avatarRing.style.borderColor = "var(--green)";
        }
        playTada();
        speakWarning(`Mời bạn ${student.fullname} lên bảng trả bài`);
        refreshSession();
      }
    };

    setTimeout(animate, 200);

  } catch (error) {
    $("#picker-modal").classList.remove("visible");
    toast(`${error.message}. Có thể reset lượt gọi để bắt đầu vòng mới.`, true);
  }
}

function showPickedStudent(student) {
  $("#picked-name").textContent = student.fullname;
  $("#picked-code").textContent = student.student_code;

  const initialsEl = $("#picked-initials");
  if (initialsEl) {
    initialsEl.textContent = initials(student.fullname);
  }

  const image = $("#picked-avatar");
  if (student.avatar_url) {
    image.src = student.avatar_url;
    image.style.display = "block";
    if (initialsEl) initialsEl.style.display = "none";
  } else {
    image.style.display = "none";
    if (initialsEl) initialsEl.style.display = "block";
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
  data.set("class_id", state.classId);
  
  if (!data.has("consent")) {
    data.delete("image");
    if (!window.confirm("Chưa có đồng ý của phụ huynh nên hệ thống sẽ không lưu ảnh khuôn mặt. Vẫn đăng ký?")) return;
  } else if (!data.get("image").size) {
    const blob = await captureCameraBlob();
    if (blob) {
      data.set("image", blob, "webcam.jpg");
    } else {
      data.delete("image");
      if (!window.confirm("Chưa có ảnh khuôn mặt: học sinh sẽ không được camera tự điểm danh cho đến khi cập nhật ảnh. Vẫn đăng ký?")) return;
    }
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
    if (!state.classId) {
      state.alerts = [];
      renderAlerts();
      return;
    }
    const query = state.session ? `session_id=${state.session.id}` : `class_id=${state.classId}`;
    state.alerts = await api(`/api/behaviors?${query}`);
    renderAlerts();
  } catch (error) {
    if (!error.message.includes("hết hạn")) toast(error.message, true);
  }
}

const alertCooldowns = new Map();
const AUDIO_ALERT_STORAGE_KEY = "smart-classroom-audio-alert";
const TTS_ALERT_STORAGE_KEY = "smart-classroom-tts-alert";

function playWarningSound() {
  const checkbox = $("#audio-alert-checkbox-modal");
  if (!checkbox || !checkbox.checked) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime); // A5 note
    gain.gain.setValueAtTime(0.1, ctx.currentTime);
    
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
    osc.stop(ctx.currentTime + 0.2);
    
    setTimeout(() => {
      try {
        const osc2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        osc2.connect(gain2);
        gain2.connect(ctx.destination);
        osc2.type = "sine";
        osc2.frequency.setValueAtTime(880, ctx.currentTime);
        gain2.gain.setValueAtTime(0.1, ctx.currentTime);
        osc2.start();
        gain2.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15);
        osc2.stop(ctx.currentTime + 0.2);
      } catch (e) {}
    }, 150);
  } catch (e) {
    console.warn("Web Audio API not supported or blocked:", e);
  }
}

let voices = [];
const TTS_VOICE_STORAGE_KEY = "smart-classroom-tts-voice";

function populateVoices() {
  if (!("speechSynthesis" in window)) return;
  voices = window.speechSynthesis.getVoices();
  const select = $("#tts-voice-select-modal");
  if (!select) return;
  
  const currentSelected = localStorage.getItem(TTS_VOICE_STORAGE_KEY) || "";
  const viVoices = voices.filter(voice => voice.lang.includes("vi") || voice.lang.includes("VI"));
  const listToUse = viVoices.length > 0 ? viVoices : voices;
  
  select.innerHTML = listToUse.map(voice => `
    <option value="${voice.name}" ${voice.name === currentSelected ? "selected" : ""}>
      ${voice.name} (${voice.lang})
    </option>
  `).join("") || '<option value="">Không tìm thấy giọng đọc</option>';
  renderSpeechStatus();
}

if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = populateVoices;
  populateVoices();
}

let speechRequest = 0;
let speechPlayer = null;

function vietnameseBrowserVoice() {
  const selected = $("#tts-voice-select-modal").value;
  const vietnamese = voices.filter((voice) => voice.lang.toLowerCase().startsWith("vi"));
  return vietnamese.find((voice) => voice.name === selected) || vietnamese[0] || null;
}

function renderSpeechStatus() {
  $("#tts-voice-container").style.display = state.serverSpeech ? "none" : "";
  let message = "";
  if (state.serverSpeech) message = "Đang dùng giọng đọc tiếng Việt cài trên máy chủ.";
  else if (!vietnameseBrowserVoice()) message = "Máy này chưa có giọng tiếng Việt nên hệ thống chỉ phát tiếng bíp.";
  $("#tts-status").textContent = message;
}

async function refreshSpeechStatus() {
  try {
    state.serverSpeech = (await api("/api/tts/status")).available;
  } catch (error) {
    state.serverSpeech = false;
  }
  renderSpeechStatus();
}

function stopSpeech() {
  speechRequest += 1;
  if (speechPlayer) speechPlayer.pause();
  speechPlayer = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

async function playServerSpeech(text, request) {
  const response = await fetch("/api/tts", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error("Không tạo được giọng đọc");
  const audio = await response.blob();
  if (request !== speechRequest) return; // a newer sentence has replaced this one
  const url = URL.createObjectURL(audio);
  speechPlayer = new Audio(url);
  speechPlayer.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
  await speechPlayer.play();
}

function speakWithBrowser(text) {
  // Never fall back to a foreign voice: it mangles Vietnamese names.
  const voice = "speechSynthesis" in window ? vietnameseBrowserVoice() : null;
  if (!voice) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  window.speechSynthesis.speak(utterance);
}

async function speakWarning(text) {
  const checkbox = $("#tts-alert-checkbox-modal");
  if (!checkbox || !checkbox.checked) return;
  stopSpeech();
  const request = speechRequest;
  try {
    if (state.serverSpeech) {
      await playServerSpeech(text, request);
      return;
    }
  } catch (error) {
    console.warn("Không phát được giọng đọc máy chủ:", error);
  }
  try {
    speakWithBrowser(text);
  } catch (error) {
    console.warn("Speech Synthesis error:", error);
  }
}

const HIDE_NAMES_STORAGE_KEY = "smart-classroom-hide-alert-names";

// On the classroom TV, behavior alerts must never single anyone out.
function isTvDisplay() {
  return document.documentElement.dataset.display === "tv";
}

function namesHidden() {
  if (isTvDisplay()) return true;
  const checkbox = $("#hide-alert-names-checkbox-modal");
  return Boolean(checkbox && checkbox.checked);
}

function alertName(alert) {
  return namesHidden() ? "Một học sinh" : alert.fullname;
}

const DISPLAY_STORAGE_KEY = "smart-classroom-display";

function applyDisplay(mode) {
  document.documentElement.dataset.display = mode;
  localStorage.setItem(DISPLAY_STORAGE_KEY, mode);
  for (const button of document.querySelectorAll("[data-display-mode]")) {
    button.setAttribute("aria-pressed", String(button.dataset.displayMode === mode));
  }
  renderAlerts();
  drawOverlay();
}

function announceCheckIn(student) {
  if (isTvDisplay() && $("#tv-hide-checkin-checkbox-modal").checked) return;
  toast(`Đã điểm danh: ${student.fullname || "học sinh"}`);
}

function initTvPrivacy() {
  const options = [
    ["#tv-hide-checkin-checkbox-modal", "smart-classroom-tv-hide-checkin", null],
    ["#tv-hide-missing-face-checkbox-modal", "smart-classroom-tv-hide-missing-face", "tvHideMissingFace"],
  ];
  for (const [selector, storageKey, datasetKey] of options) {
    const checkbox = $(selector);
    const apply = () => {
      if (datasetKey) document.documentElement.dataset[datasetKey] = String(checkbox.checked);
    };
    checkbox.checked = localStorage.getItem(storageKey) !== "false"; // on by default
    apply();
    checkbox.addEventListener("change", () => {
      localStorage.setItem(storageKey, String(checkbox.checked));
      apply();
    });
  }
}

function initHideNames() {
  const checkbox = $("#hide-alert-names-checkbox-modal");
  checkbox.checked = localStorage.getItem(HIDE_NAMES_STORAGE_KEY) === "true";
  checkbox.addEventListener("change", (event) => {
    localStorage.setItem(HIDE_NAMES_STORAGE_KEY, String(event.target.checked));
    renderAlerts();
    drawOverlay();
  });
}

function initAudioToggles() {
  const audioCheckbox = $("#audio-alert-checkbox-modal");
  const ttsCheckbox = $("#tts-alert-checkbox-modal");
  
  if (audioCheckbox) {
    const saved = localStorage.getItem(AUDIO_ALERT_STORAGE_KEY);
    audioCheckbox.checked = saved !== null ? saved === "true" : true;
    audioCheckbox.addEventListener("change", (e) => {
      localStorage.setItem(AUDIO_ALERT_STORAGE_KEY, String(e.target.checked));
    });
  }
  
  const updateVoiceContainerVisibility = () => {
    const groupbox = ttsCheckbox ? ttsCheckbox.closest(".settings-groupbox") : null;
    const select = $("#tts-voice-select-modal");
    if (ttsCheckbox && ttsCheckbox.checked) {
      if (groupbox) groupbox.classList.remove("disabled");
      if (select) select.removeAttribute("disabled");
    } else {
      if (groupbox) groupbox.classList.add("disabled");
      if (select) select.setAttribute("disabled", "true");
    }
  };
  
  if (ttsCheckbox) {
    const saved = localStorage.getItem(TTS_ALERT_STORAGE_KEY);
    ttsCheckbox.checked = saved !== null ? saved === "true" : true;
    updateVoiceContainerVisibility();
    ttsCheckbox.addEventListener("change", (e) => {
      localStorage.setItem(TTS_ALERT_STORAGE_KEY, String(e.target.checked));
      updateVoiceContainerVisibility();
    });
  }
}

const FPS_STORAGE_KEY = "smart-classroom-fps";

function restartCameraTimer() {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
  clearInterval(state.cameraTimer);
  const select = $("#video-fps-select-modal");
  const interval = select ? parseInt(select.value, 10) : 100;
  state.cameraTimer = setInterval(sendFrame, interval);
}

function initSettings() {
  initAudioToggles();
  initHideNames();
  initTvPrivacy();
  populateVoices();
  const fpsSelect = $("#video-fps-select-modal");
  if (fpsSelect) {
    const saved = localStorage.getItem(FPS_STORAGE_KEY);
    if (saved) {
      fpsSelect.value = saved;
    }
    fpsSelect.addEventListener("change", (e) => {
      localStorage.setItem(FPS_STORAGE_KEY, e.target.value);
      restartCameraTimer();
    });
  }
  
  const voiceSelect = $("#tts-voice-select-modal");
  if (voiceSelect) {
    voiceSelect.addEventListener("change", (e) => {
      localStorage.setItem(TTS_VOICE_STORAGE_KEY, e.target.value);
    });
  }
}

function addAlert(alert) {
  if (alert.id && state.session && state.session.summary) state.session.summary.behaviors += 1;
  state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 30);
  renderAlerts();
  toast(`${alert.label}: ${alertName(alert)}`, true);

  const studentKey = alert.student_id || alert.fullname;
  const cooldownKey = `${alert.behavior_type}_${studentKey}`;
  const now = Date.now();

  if (!alertCooldowns.has(cooldownKey) || now - alertCooldowns.get(cooldownKey) > 10000) {
    alertCooldowns.set(cooldownKey, now);
    playWarningSound();
    speakWarning(namesHidden() ? `Cảnh báo ${alert.label}` : `Cảnh báo ${alert.label}, ${alert.fullname}`);
  }
}

function renderAlerts() {
  $("#alert-stat").textContent = state.session && state.session.summary
    ? String(state.session.summary.behaviors)
    : String(state.alerts.length);
  $("#clear-alerts-button").disabled = state.alerts.length === 0;
  $("#alert-list").innerHTML = state.alerts.map((alert) => `
    <div class="alert-item">
      <strong>${escapeHtml(alert.label || alert.behavior_type)} · ${escapeHtml(alertName(alert))}</strong>
      <span>${alert.timestamp ? new Date(alert.timestamp).toLocaleString("vi-VN") : "Vừa phát hiện"}</span>
    </div>
  `).join("") || '<p class="empty-note">Chưa có cảnh báo. Hành vi được phát hiện sẽ hiện ở đây.</p>';
}

async function clearAlerts() {
  if (!state.alerts.length) return;
  if (!window.confirm("Xóa nhật ký cảnh báo và ảnh bằng chứng của lớp này?")) return;
  try {
    const result = await api(`/api/behaviors?class_id=${state.classId}`, { method: "DELETE" });
    state.alerts = [];
    if (state.session && state.session.summary) state.session.summary.behaviors = 0;
    renderAlerts();
    toast(`Đã xóa ${result.deleted} bản ghi nhật ký hành vi`);
  } catch (error) {
    toast(error.message, true);
  }
}

function initials(name) {
  return name.split(/\s+/).slice(-2).map((part) => part[0]).join("").toUpperCase();
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value || "";
  // innerHTML leaves quotes alone, which is unsafe inside attribute values.
  return span.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

$("#login-form").addEventListener("submit", login);
$("#settings-button").addEventListener("click", () => $("#settings-modal").classList.add("visible"));
$("#close-settings-button").addEventListener("click", () => $("#settings-modal").classList.remove("visible"));
$("#theme-select-modal").addEventListener("change", (e) => applyTheme(e.target.value));
$("#start-camera-button").addEventListener("click", startCamera);
$("#stop-camera-button").addEventListener("click", stopCamera);
$("#video-source-select-modal").addEventListener("change", onVideoSourceChange);
for (const button of document.querySelectorAll(".behavior-toggle")) {
  button.addEventListener("click", toggleBehavior);
}
$("#start-session-button").addEventListener("click", startSession);
$("#finish-session-button").addEventListener("click", finishSession);
$("#pick-button").addEventListener("click", pickStudent);
$("#reset-called-button").addEventListener("click", resetCalled);
$("#clear-alerts-button").addEventListener("click", clearAlerts);
$("#close-picker-button").addEventListener("click", () => $("#picker-modal").classList.remove("visible"));
$("#toggle-register-button").addEventListener("click", (event) => {
  const hidden = $("#register-form").classList.toggle("hidden");
  event.currentTarget.setAttribute("aria-expanded", String(!hidden));
  if (!hidden) $('#register-form input[name="student_code"]').focus();
});
$("#register-form").addEventListener("submit", registerStudent);
$("#student-list").addEventListener("click", onStudentListClick);
$("#student-list").addEventListener("change", onConsentChange);
$("#export-session-button").addEventListener("click", () => state.session && exportSession(state.session.id));
$("#history-button").addEventListener("click", showHistory);
$("#admin-button").addEventListener("click", openAdmin);
$("#close-admin-button").addEventListener("click", () => $("#admin-modal").classList.remove("visible"));
$("#new-user-form").addEventListener("submit", createUser);
$("#admin-users").addEventListener("click", onAdminUsersClick);
$("#new-class-form").addEventListener("submit", createClass);
$("#admin-class-list").addEventListener("change", onClassTeacherChange);
$("#admin-class-list").addEventListener("submit", onAddStudentToClass);
$("#class-select").addEventListener("change", onClassChange);
$("#report-body").addEventListener("click", onReportClick);
$("#close-report-button").addEventListener("click", () => $("#report-modal").classList.remove("visible"));
$("#reenroll-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  const studentId = Number(event.target.dataset.studentId);
  if (file && studentId) uploadFace(studentId, file, file.name);
});

const setupOutsideClickClose = (modalSelector) => {
  const modal = $(modalSelector);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        modal.classList.remove("visible");
      }
    });
  }
};
setupOutsideClickClose("#settings-modal");
setupOutsideClickClose("#picker-modal");
setupOutsideClickClose("#report-modal");
setupOutsideClickClose("#admin-modal");
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const selector of ["#settings-modal", "#picker-modal", "#report-modal", "#admin-modal"]) {
    $(selector).classList.remove("visible");
  }
});
window.addEventListener("resize", () => drawOverlay());
document.addEventListener("visibilitychange", () => {
  // Frames are not sent while the tab is hidden; drop the stale overlay.
  if (document.hidden) clearOverlay();
});
$("#logout-button").addEventListener("click", async () => {
  stopCamera();
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

loadCurrentUser()
  .then(() => {
    $("#login-modal").classList.remove("visible");
    refreshDashboard();
  })
  .catch(() => $("#login-modal").classList.add("visible"));

applyTheme(document.documentElement.dataset.theme || "light");
for (const button of document.querySelectorAll("[data-display-mode]")) {
  button.addEventListener("click", () => applyDisplay(button.dataset.displayMode));
}
refreshVideoDevices();
initSettings();
applyDisplay(document.documentElement.dataset.display || "desk");
