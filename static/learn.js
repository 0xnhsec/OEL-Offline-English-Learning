/* Learn 101 — local login + dashboard */

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "xl_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  modules: [],
  leaderboard: [],
  mode: "login",
};

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(options.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function showLogin() {
  $("loginView").hidden = false;
  $("dashView").hidden = true;
}

function showDash() {
  $("loginView").hidden = true;
  $("dashView").hidden = false;
}

/* ───────────────────────── auth ───────────────────────── */
function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".login-tab").forEach((tab) =>
    tab.classList.toggle("active", tab.dataset.mode === mode));
  $("nameField").hidden = mode !== "register";
  $("loginTitle").textContent = mode === "register" ? "Buat akun lokal" : "Masuk ke bank soal";
  $("authSubmit").textContent = mode === "register" ? "Buat akun" : "Masuk";
  $("authErr").textContent = "";
}

async function submitAuth(event) {
  event.preventDefault();
  const username = $("authUser").value.trim();
  const password = $("authPass").value;
  const name = $("authName").value.trim();
  $("authErr").textContent = "";
  $("authSubmit").disabled = true;
  try {
    const path = state.mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const payload = state.mode === "register"
      ? { username, name, password }
      : { username, password };
    const result = await api(path, { method: "POST", body: JSON.stringify(payload) });
    state.token = result.token;
    state.user = result.user;
    localStorage.setItem(TOKEN_KEY, state.token);
    await loadDashboard();
    showDash();
  } catch (error) {
    $("authErr").textContent = error.message;
  } finally {
    $("authSubmit").disabled = false;
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {}
  localStorage.removeItem(TOKEN_KEY);
  state.token = "";
  state.user = null;
  showLogin();
}

/* ───────────────────────── data ───────────────────────── */
async function loadDashboard() {
  const [modules, board] = await Promise.all([
    api("/api/modules"),
    api("/api/leaderboard"),
  ]);
  state.modules = modules.modules || [];
  state.leaderboard = board.entries || [];
  renderUser();
  renderStats();
  renderModules();
  renderBoard();
}

function renderUser() {
  const user = state.user;
  if (!user) return;
  const letters = initials(user.name);
  ["railAvatar", "topAvatar"].forEach((id) => { $(id).textContent = letters; });
  $("popName").textContent = user.name;
  $("popHandle").textContent = `@${user.username}`;
  $("popPoints").textContent = user.points || 0;
  $("popSets").textContent = user.sets || 0;
  $("topName").textContent = user.name;
  $("topHandle").textContent = `@${user.username}`;
}

function renderStats() {
  const user = state.user || {};
  const progress = user.progress || {};
  const bank = state.modules.reduce((sum, m) => sum + (m.count || 0), 0);
  $("statPoints").textContent = user.points || 0;
  $("statAcc").textContent = `${Math.round((user.accuracy || 0) * 100)}%`;
  $("statSets").textContent = user.sets || 0;
  $("statBank").textContent = bank;
  $("statsSub").textContent = `${Object.keys(progress).length} set aktif`;
}

function moduleProgress(module) {
  const progress = (state.user && state.user.progress) || {};
  return progress[module.title] || null;
}

function renderModules() {
  const query = ($("moduleSearch").value || "").toLowerCase().trim();
  const items = state.modules.filter((module) =>
    !query || module.title.toLowerCase().includes(query));
  const list = $("moduleList");
  list.innerHTML = items.map((module) => {
    const progress = moduleProgress(module);
    const best = progress ? Math.min(progress.best, module.count || progress.total || 1) : 0;
    const total = module.count || 1;
    const pct = Math.max(0, Math.min(100, Math.round((best / total) * 100)));
    const diffs = Object.entries(module.difficulty || {})
      .filter(([key]) => ["easy", "medium", "hard"].includes(key))
      .map(([key, value]) => `<span class="module-tag ${key}">${key} ${value}</span>`)
      .join("");
    return `<a class="module-row" href="/?module=${encodeURIComponent(module.id)}">
      <div>
        <div class="module-name">${escapeHtml(module.title)}</div>
        <div class="module-meta">
          <span class="module-count">${module.count} soal</span>
          ${diffs}
          ${progress ? `<span class="module-count">best ${best}/${total}</span>` : ""}
        </div>
      </div>
      <span class="module-arrow">→</span>
      <div class="module-progress"><i style="width:${pct}%"></i></div>
    </a>`;
  }).join("");
  $("moduleEmpty").hidden = items.length > 0;
  const done = state.modules.filter((m) => moduleProgress(m)).length;
  $("modulesSub").textContent = `${done}/${state.modules.length} dimulai`;
}

function renderBoard() {
  const user = state.user || {};
  const list = $("boardList");
  const max = Math.max(1, ...state.leaderboard.map((row) => row.points || 0));
  list.innerHTML = state.leaderboard.map((row) => {
    const mine = row.username === user.username;
    const pct = row.points > 0 ? Math.max(4, Math.round((row.points / max) * 100)) : 0;
    return `<div class="board-row ${mine ? "me" : ""}">
      <span class="board-rank">${String(row.rank).padStart(2, "0")}</span>
      <span class="board-avatar">${escapeHtml(initials(row.name))}</span>
      <div>
        <div class="board-name">${escapeHtml(row.name)}${mine ? " · kamu" : ""}</div>
        <div class="board-handle">@${escapeHtml(row.username)} · ${row.sets} set · ${Math.round((row.accuracy || 0) * 100)}%</div>
      </div>
      <span class="board-points">${row.points} pt</span>
      <div class="board-bar"><i style="width:${pct}%"></i></div>
    </div>`;
  }).join("");
  $("boardEmpty").hidden = state.leaderboard.length > 0;
  $("boardSub").textContent = `${state.leaderboard.length} pemain`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

/* ───────────────────────── panels ───────────────────────── */
function setPanel(name) {
  document.querySelectorAll(".lnav, .rail-btn[data-panel]").forEach((button) =>
    button.classList.toggle("active", button.dataset.panel === name));
  const grid = document.querySelector(".dash-grid");
  if (grid) grid.dataset.panel = name;
  if (name === "modules") $("moduleList").scrollIntoView({ behavior: "smooth", block: "center" });
  else if (name === "leaderboard") $("boardList").scrollIntoView({ behavior: "smooth", block: "center" });
  else window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ───────────────────────── boot ───────────────────────── */
async function boot() {
  $("authForm").addEventListener("submit", submitAuth);
  document.querySelectorAll(".login-tab").forEach((tab) =>
    tab.addEventListener("click", () => setMode(tab.dataset.mode)));
  $("logoutBtn").addEventListener("click", logout);
  $("moduleSearch").addEventListener("input", renderModules);
  $("freePracticeBtn").addEventListener("click", () => { location.href = "/?view=study"; });
  $("uploadBtn").addEventListener("click", () => { location.href = "/?view=study"; });
  $("railSettings").addEventListener("click", () => { location.href = "/?view=settings"; });
  document.querySelectorAll(".lnav, .rail-btn[data-panel]").forEach((button) =>
    button.addEventListener("click", () => setPanel(button.dataset.panel)));

  if (!state.token) { showLogin(); return; }
  try {
    const me = await api("/api/auth/me");
    state.user = me.user;
    await loadDashboard();
    showDash();
  } catch (_) {
    localStorage.removeItem(TOKEN_KEY);
    state.token = "";
    showLogin();
  }
}

boot();
