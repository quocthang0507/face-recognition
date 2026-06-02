const state = {
  stream: null,
  socket: null,
  session: null,
  students: [],
  alerts: [],
  waitingFrame: false,
  cameraTimer: null,
  enabledBehaviors: new Set(["SLEEPING", "HAND_ON_FACE", "CHEATING", "TALKING"]),
  videoDevices: [],
};

const $ = (selector) => document.querySelector(selector);
const camera = $("#camera");
const canvas = $("#capture-canvas");
const frame = $("#processed-frame");
const THEME_STORAGE_KEY = "smart-classroom-theme";

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

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_STORAGE_KEY, theme);
  const select = $("#theme-select-modal");
  if (select) {
    select.value = theme;
  }
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
    $("#start-camera-button").textContent = "Camera đang bật";
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
  frame.removeAttribute("src");
  frame.style.display = "none";
  $("#camera-placeholder").style.display = "grid";
  $("#start-camera-button").textContent = "Bật camera";
  $("#start-camera-button").disabled = false;
  $("#stop-camera-button").disabled = true;
  $("#engine-message").textContent = "";
  setSocketStatus(false);
}

function connectSocket() {
  if (!state.stream) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws`);
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
    frame.src = `data:image/jpeg;base64,${payload.image}`;
    frame.style.display = "block";
    const errors = [...new Set(payload.errors || [])];
    $("#engine-message").textContent = errors.join(" ");
    for (const alert of payload.alerts || []) addAlert(alert);
    
    state.lastFaceDetected = (payload.faces || []).length > 0;
    updatePickButtonState();
    if ((payload.faces || []).some((face) => face.student_id)) refreshSession();
  };
  state.socket.onclose = () => {
    state.socket = null;
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
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN || state.waitingFrame) return;
  if (!camera.videoWidth) return;

  // Downscale frame to a maximum width of 640px to optimize network and CPU usage
  const maxDim = 640;
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
  canvas.toBlob((blob) => {
    if (!blob || !state.socket || state.socket.readyState !== WebSocket.OPEN) {
      state.waitingFrame = false;
      return;
    }
    state.socket.send(blob);
  }, "image/jpeg", 0.70);
}

function setSocketStatus(online) {
  const item = $("#socket-status");
  item.textContent = online ? "Camera trực tuyến" : "Camera ngoại tuyến";
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

function updatePickButtonState() {
  const active = Boolean(state.session);
  const faceDetected = state.lastFaceDetected || false;
  const button = $("#pick-button");
  if (button) {
    button.disabled = !active && !faceDetected;
  }
}

function renderSession() {
  const active = Boolean(state.session);
  const present = state.students.filter((student) => student.is_present).length;
  const called = state.students.filter((student) => student.is_called).length;
  $("#session-stat").textContent = active ? `#${state.session.id} Đang hoạt động` : "Chưa bắt đầu";
  $("#present-stat").textContent = `${present} / ${state.students.length}`;
  $("#called-stat").textContent = String(called);
  $("#start-session-button").disabled = active;
  $("#finish-session-button").disabled = !active;
  updatePickButtonState();
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
  let sessionId = state.session ? state.session.id : null;
  if (!sessionId) {
    try {
      state.session = await api("/api/sessions", { method: "POST" });
      state.students = state.session.students;
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

  if (initialsEl) initialsEl.textContent = "?";
  if (avatarRing) {
    avatarRing.style.borderColor = "var(--blue)";
    avatarRing.style.boxShadow = "none";
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
        avatarRing.style.boxShadow = `0 0 15px ${color}`;
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
          avatarRing.style.boxShadow = "0 0 30px var(--green)";
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
  
  if (!data.get("image").size) {
    if (state.stream && camera.videoWidth) {
      canvas.width = camera.videoWidth;
      canvas.height = camera.videoHeight;
      canvas.getContext("2d").drawImage(camera, 0, 0);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
      data.set("image", blob, "webcam.jpg");
    } else {
      data.delete("image");
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
    state.alerts = await api("/api/behaviors");
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
}

if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = populateVoices;
  populateVoices();
}

function speakWarning(text) {
  const checkbox = $("#tts-alert-checkbox-modal");
  if (!checkbox || !checkbox.checked) return;
  try {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "vi-VN";
      utterance.rate = 1.0;
      
      const voiceSelect = $("#tts-voice-select-modal");
      if (voiceSelect && voiceSelect.value) {
        const selectedVoice = voices.find(v => v.name === voiceSelect.value);
        if (selectedVoice) {
          utterance.voice = selectedVoice;
          utterance.lang = selectedVoice.lang;
        }
      }
      window.speechSynthesis.speak(utterance);
    }
  } catch (e) {
    console.warn("Speech Synthesis error:", e);
  }
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
  state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 30);
  renderAlerts();
  toast(`${alert.label}: ${alert.fullname}`, true);

  const studentKey = alert.student_id || alert.fullname;
  const cooldownKey = `${alert.behavior_type}_${studentKey}`;
  const now = Date.now();

  if (!alertCooldowns.has(cooldownKey) || now - alertCooldowns.get(cooldownKey) > 10000) {
    alertCooldowns.set(cooldownKey, now);
    playWarningSound();
    speakWarning(`Cảnh báo ${alert.label}, ${alert.fullname}`);
  }
}

function renderAlerts() {
  $("#alert-stat").textContent = String(state.alerts.length);
  $("#clear-alerts-button").disabled = state.alerts.length === 0;
  $("#alert-list").innerHTML = state.alerts.map((alert) => `
    <div class="alert-item">
      <strong>${escapeHtml(alert.label || alert.behavior_type)} · ${escapeHtml(alert.fullname)}</strong>
      <span>${alert.timestamp ? new Date(alert.timestamp).toLocaleString("vi-VN") : "Vừa phát hiện"}</span>
    </div>
  `).join("") || '<span class="badge absent">Chưa có cảnh báo</span>';
}

async function clearAlerts() {
  if (!state.alerts.length) return;
  if (!window.confirm("Xóa toàn bộ audit trail và ảnh bằng chứng đã lưu?")) return;
  try {
    const result = await api("/api/behaviors", { method: "DELETE" });
    state.alerts = [];
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
  return span.innerHTML;
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
$("#toggle-register-button").addEventListener("click", () => $("#register-form").classList.toggle("hidden"));
$("#register-form").addEventListener("submit", registerStudent);

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
$("#logout-button").addEventListener("click", async () => {
  stopCamera();
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

api("/api/auth/status")
  .then(() => {
    $("#login-modal").classList.remove("visible");
    refreshDashboard();
  })
  .catch(() => $("#login-modal").classList.add("visible"));

applyTheme(document.documentElement.dataset.theme || "dark");
refreshVideoDevices();
initSettings();
