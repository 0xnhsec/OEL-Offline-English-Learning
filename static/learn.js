/* Learn 101 — local login, dashboard, leaderboard, bio + foto profil */

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
  $("authPass").minLength = mode === "register" ? 6 : 3;
  $("authPass").placeholder = mode === "register" ? "min. 6 karakter" : "••••";
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

function paintAvatar(el, user) {
  if (!el) return;
  const url = user && user.avatar;
  if (url) {
    el.innerHTML = `<img src="${escapeHtml(url)}" alt="${escapeHtml((user && user.name) || "")}">`;
    el.classList.add("has-photo");
  } else {
    el.textContent = initials(user && user.name);
    el.classList.remove("has-photo");
  }
}

function flash(text) {
  const el = $("popMsg");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
  if (text) setTimeout(() => { if (el.textContent === text) { el.hidden = true; el.textContent = ""; } }, 3200);
}

async function uploadAvatar(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  flash("mengunggah…");
  try {
    const res = await fetch("/api/auth/avatar", {
      method: "POST", headers: authHeaders(), body: form,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    state.user = body.user;
    await loadDashboard();
    flash("foto profil diperbarui");
  } catch (error) {
    flash(error.message);
  }
}

async function clearAvatar() {
  flash("menghapus…");
  try {
    const res = await fetch("/api/auth/avatar", { method: "DELETE", headers: authHeaders() });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    state.user = body.user;
    await loadDashboard();
    flash("foto profil dihapus");
  } catch (error) {
    flash(error.message);
  }
}

function renderUser() {
  const user = state.user;
  if (!user) return;
  paintAvatar($("railAvatar"), user);
  paintAvatar($("topAvatar"), user);
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
    const pct = Math.max(3, Math.round(((row.points || 0) / max) * 100));
    const hasBio = !!(row.bio && Object.keys(row.bio).length);
    const avatar = row.avatar
      ? `<span class="board-avatar has-photo"><img src="${escapeHtml(row.avatar)}" alt=""></span>`
      : `<span class="board-avatar">${escapeHtml(initials(row.name))}</span>`;
    return `<div class="board-row${mine ? " me" : ""}${row.featured ? " legend" : ""}${hasBio ? " has-bio" : ""}"
      data-username="${escapeHtml(row.username)}"${hasBio ? ' role="button" tabindex="0" title="klik untuk lihat bio"' : ""}>
      <span class="board-rank">${String(row.rank).padStart(2, "0")}</span>
      ${avatar}
      <div>
        <div class="board-name">${escapeHtml(row.name)}${row.featured ? ' <span class="crown">★ legend</span>' : ""}${mine ? " · kamu" : ""}</div>
        <div class="board-handle">@${escapeHtml(row.username)} · ${row.sets} set · ${Math.round((row.accuracy || 0) * 100)}%${hasBio ? ' · <span class="bio-hint">klik → bio</span>' : ""}</div>
      </div>
      <span class="board-points">${row.points} pt</span>
      <div class="board-bar"><i style="width:${pct}%"></i></div>
    </div>`;
  }).join("");

  list.querySelectorAll(".board-row.has-bio").forEach((row) => {
    const open = () => {
      const entry = state.leaderboard.find((item) => item.username === row.dataset.username);
      if (entry) openBio(entry);
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });

  $("boardEmpty").hidden = state.leaderboard.length > 0;
  $("boardSub").textContent = `${state.leaderboard.length} pemain`;
}

/* ───────────────────────── bio ───────────────────────── */
function openBio(entry) {
  if (!entry) return;
  $("bioName").textContent = entry.name || entry.username;
  $("bioHandle").textContent = `@${entry.username}`;
  $("bioKicker").textContent = entry.featured
    ? "legend · rank 01"
    : `rank ${String(entry.rank || 1).padStart(2, "0")}`;
  paintAvatar($("bioAvatar"), entry);
  const bio = entry.bio || {};
  const keys = Object.keys(bio);
  $("bioList").innerHTML = keys.length
    ? keys.map((key) => `<div class="bio-row"><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(bio[key])}</dd></div>`).join("")
    : `<div class="bio-row"><dt>Name</dt><dd>${escapeHtml(entry.name || entry.username)}</dd></div>
       <div class="bio-row"><dt>Gender</dt><dd>—</dd></div>
       <div class="bio-row"><dt>Address</dt><dd>—</dd></div>`;
  $("bioNote").textContent = entry.featured
    ? "Profil legenda OEL — tetap, tidak bisa diubah. Foto: ayang.png"
    : "Bio pemain ini belum diisi.";
  $("bioModal").hidden = false;
  document.body.classList.add("modal-open");
  $("bioClose").focus();
}

function closeBio() {
  $("bioModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

/* popover user: position fixed supaya tidak terpotong .learn-shell{overflow:hidden} */
function placeUserPop() {
  const rail = $("railUser");
  const pop = document.querySelector(".user-pop");
  if (!rail || !pop) return;
  const rect = rail.getBoundingClientRect();
  const width = pop.offsetWidth || 258;
  const height = pop.offsetHeight || 240;
  let left = rect.right - 2;
  if (left + width > window.innerWidth - 10) left = Math.max(10, window.innerWidth - width - 10);
  let top = rect.bottom - height + 8;
  top = Math.max(10, Math.min(top, window.innerHeight - height - 10));
  pop.style.left = `${Math.round(left)}px`;
  pop.style.top = `${Math.round(top)}px`;
  pop.style.bottom = "auto";
}

function initUserPop() {
  const rail = $("railUser");
  const pop = document.querySelector(".user-pop");
  if (!rail || !pop) return;
  if (pop.parentElement !== document.body) document.body.appendChild(pop);

  const open = () => { placeUserPop(); pop.classList.add("open"); };
  const close = () => pop.classList.remove("open");
  let timer = 0;

  rail.addEventListener("mouseenter", () => { clearTimeout(timer); open(); });
  rail.addEventListener("mouseleave", () => {
    timer = setTimeout(() => { if (!pop.matches(":hover")) close(); }, 180);
  });
  pop.addEventListener("mouseenter", () => clearTimeout(timer));
  pop.addEventListener("mouseleave", () => { if (!rail.matches(":hover")) close(); });
  rail.addEventListener("focusin", open);
  rail.addEventListener("focusout", (event) => {
    if (!rail.contains(event.relatedTarget) && !pop.matches(":hover")) close();
  });
  placeUserPop();
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
  $("avatarPickBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    $("avatarInput").click();
  });
  $("avatarInput").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    uploadAvatar(file);
  });
  $("avatarClearBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    clearAvatar();
  });
  initUserPop();
  document.body.appendChild($("bioModal"));   // bebas dari clipping .learn-shell
  window.addEventListener("resize", placeUserPop);
  $("bioClose").addEventListener("click", closeBio);
  $("bioBackdrop").addEventListener("click", closeBio);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("bioModal").hidden) closeBio();
  });
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
