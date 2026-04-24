// SQLi Expert Audit - answering UI
// vanilla JS, no framework.

const $  = (q) => document.querySelector(q);
const $$ = (q) => Array.from(document.querySelectorAll(q));

const state = {
  token: localStorage.getItem("audit_token") || "",
  name : localStorage.getItem("audit_name")  || "",
  current: null,
  q1: null, q2: null, q3: new Set(),
  t0: 0,
};

// ---------- helpers ------------------------------------------------------

async function api(path, { method="GET", body=null } = {}) {
  const opts = { method, headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json";
              opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`${r.status}: ${t}`);
  }
  return r.json();
}

function setMsg(id, text, cls="muted") {
  const el = $(id); if (!el) return;
  el.textContent = text; el.className = `small ${cls}`;
}

// tiny SQL highlighter
const KW = /\b(SELECT|FROM|WHERE|AND|OR|NOT|UNION|ALL|INSERT|INTO|VALUES|UPDATE|SET|DELETE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|IS|NULL|LIKE|IN|EXISTS|CASE|WHEN|THEN|ELSE|END|CREATE|TABLE|DROP|ALTER|INDEX|PRIMARY|KEY|FOREIGN|REFERENCES|DISTINCT|CAST|EXEC|EXECUTE|DECLARE|BEGIN|IF|SLEEP|WAITFOR|DELAY|BENCHMARK)\b/gi;
function highlight(sql) {
  const esc = sql.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  return esc
    .replace(/('([^']|'')*'|"([^"]|"")*")/g, m => `<span class="str">${m}</span>`)
    .replace(/\b\d+(?:\.\d+)?\b/g, m => `<span class="num">${m}</span>`)
    .replace(/(--[^\n]*|\/\*[\s\S]*?\*\/|#[^\n]*)/g, m => `<span class="cmt">${m}</span>`)
    .replace(KW, m => `<span class="kw">${m}</span>`);
}

// ---------- flow ---------------------------------------------------------

function showLogin() {
  $("#login").classList.remove("hidden");
  $("#quiz").classList.add("hidden");
  $("#done").classList.add("hidden");
  if (state.name)  $("#in-name").value  = state.name;
  if (state.token) $("#in-token").value = state.token;
}

function showQuiz() {
  $("#login").classList.add("hidden");
  $("#quiz").classList.remove("hidden");
  $("#done").classList.add("hidden");
  $("#who").textContent = `Expert: ${state.name}`;
}

function showDone(prog) {
  $("#login").classList.add("hidden");
  $("#quiz").classList.add("hidden");
  $("#done").classList.remove("hidden");
  if (prog) {
    $("#done").innerHTML += `<p class="muted">Annotated ${prog.done}/${prog.total}.</p>`;
  }
}

async function login() {
  const name  = $("#in-name").value.trim();
  const token = $("#in-token").value.trim();
  if (!name || !token) {
    setMsg("#login-msg", "Please provide both a display name and a token.", "muted");
    return;
  }
  try {
    const r = await api("/login", { method: "POST",
                                    body: { display_name: name, token: token } });
    state.token = token; state.name = name;
    localStorage.setItem("audit_token", token);
    localStorage.setItem("audit_name",  name);
    if (r.is_new) setMsg("#login-msg", "New expert created.", "muted");
    else          setMsg("#login-msg", "Welcome back — resuming.", "muted");
    showQuiz();
    await loadNext();
  } catch (e) { setMsg("#login-msg", `Login failed: ${e.message}`, "muted"); }
}

function logout() {
  state.token = ""; state.name = "";
  localStorage.removeItem("audit_token");
  localStorage.removeItem("audit_name");
  showLogin();
}

async function loadNext() {
  const r = await api(`/api/next?token=${encodeURIComponent(state.token)}`);
  if (r.done) { showDone(r.progress); return; }
  renderSample(r.sample, r.progress);
}

function renderSample(s, prog) {
  state.current = s; state.q1 = null; state.q2 = null; state.q3 = new Set();
  state.t0 = Date.now();

  $("#sql-box").innerHTML = highlight(s.sql || "");
  $("#cal-badge").classList.toggle("hidden", !s.is_calibration);

  $$(".q1").forEach(b => b.classList.remove("sel"));
  $$(".q2").forEach(b => b.classList.remove("sel"));
  $$(".q3").forEach(c => c.checked = false);
  $("#q2-block").classList.add("hidden");
  $("#q3-block").classList.add("hidden");
  $("#notes").value = "";
  setMsg("#submit-msg", "");

  if (prog) {
    $("#progress-text").textContent = `${prog.done}/${prog.total}`;
    const pct = prog.total ? Math.round(prog.done * 100 / prog.total) : 0;
    $("#progress-fill").style.width = `${pct}%`;
  }
}

function pickQ1(v) {
  state.q1 = v;
  $$(".q1").forEach(b => b.classList.toggle("sel", b.dataset.v === v));
  // show Q2 only for mal/ben; Q3 only for mal
  $("#q2-block").classList.toggle("hidden", !(v === "mal" || v === "ben"));
  $("#q3-block").classList.toggle("hidden", v !== "mal");
  if (v !== "mal" && v !== "ben") state.q2 = null;
  if (v !== "mal") state.q3 = new Set();
}

function pickQ2(v) {
  state.q2 = v;
  $$(".q2").forEach(b => b.classList.toggle("sel", b.dataset.v === v));
}

async function submit() {
  if (!state.current) return;
  if (!state.q1) { setMsg("#submit-msg", "Answer Q1 first.", "muted"); return; }
  if ((state.q1 === "mal" || state.q1 === "ben") && !state.q2) {
    setMsg("#submit-msg", "Answer Q2 first.", "muted"); return;
  }
  const q3 = Array.from(
    $$(".q3")).filter(c => c.checked).map(c => c.value);
  const body = {
    token: state.token,
    sample_id: state.current.sample_id,
    q1: state.q1, q2: state.q2,
    q3_attacks: state.q1 === "mal" ? q3 : null,
    notes: $("#notes").value.trim() || null,
    time_spent_ms: Date.now() - state.t0,
  };
  try {
    await api("/api/annotate", { method: "POST", body });
    setMsg("#submit-msg", "Saved.", "muted");
    await loadNext();
  } catch (e) {
    setMsg("#submit-msg", `Save failed: ${e.message}`, "muted");
  }
}

async function back() {
  try {
    const r = await api(`/api/back?token=${encodeURIComponent(state.token)}`,
                        { method: "POST" });
    renderSample(r.sample, null);
    // re-apply prior answer so the expert can tweak instead of redoing
    if (r.prior_answer) {
      pickQ1(r.prior_answer.q1);
      if (r.prior_answer.q2) pickQ2(r.prior_answer.q2);
      if (r.prior_answer.q3_attacks) {
        const list = JSON.parse(r.prior_answer.q3_attacks);
        $$(".q3").forEach(c => c.checked = list.includes(c.value));
      }
      if (r.prior_answer.notes) $("#notes").value = r.prior_answer.notes;
    }
    // refresh progress
    const p = await api(`/api/progress?token=${encodeURIComponent(state.token)}`);
    $("#progress-text").textContent = `${p.done}/${p.total}`;
    const pct = p.total ? Math.round(p.done * 100 / p.total) : 0;
    $("#progress-fill").style.width = `${pct}%`;
  } catch (e) {
    setMsg("#submit-msg", `Back failed: ${e.message}`, "muted");
  }
}

// ---------- wiring -------------------------------------------------------

$("#btn-login").addEventListener("click", login);
$("#btn-logout").addEventListener("click", logout);
$("#btn-back").addEventListener("click", back);
$("#btn-submit").addEventListener("click", submit);

$$(".q1").forEach(b => b.addEventListener("click", () => pickQ1(b.dataset.v)));
$$(".q2").forEach(b => b.addEventListener("click", () => pickQ2(b.dataset.v)));

// keyboard shortcuts
document.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA") return;
  if ($("#quiz").classList.contains("hidden")) return;
  const k = ev.key.toLowerCase();
  if (k === "1") pickQ1("mal");
  else if (k === "2") pickQ1("ben");
  else if (k === "3") pickQ1("ambiguous");
  else if (k === "4") pickQ1("invalid");
  else if (k === "y") pickQ2("yes");
  else if (k === "n") pickQ2("no");
  else if (k === "enter") { ev.preventDefault(); submit(); }
});

// boot: if we already have a token stashed, try to jump straight into quiz
(async () => {
  if (state.token && state.name) {
    try {
      await api(`/api/progress?token=${encodeURIComponent(state.token)}`);
      showQuiz();
      await loadNext();
      return;
    } catch (_) { /* token invalid / server reset */ }
  }
  showLogin();
})();
