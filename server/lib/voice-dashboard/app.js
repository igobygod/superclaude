"use strict";
const P = document.body.dataset.prefix;
const $ = (id) => document.getElementById(id);
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = String(text); return e; }
function dur(s) { if (s == null) return ""; s = Math.round(s); return s < 90 ? s + "s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h"; }
function ago(s) { return s < 90 ? s + "s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 129600 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago"; }
async function post(path, body) {
  const r = await fetch(P + path, { method: "POST", headers: { "X-Dash": "1", "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const j = await r.json(); alert(j.msg); load();
}
function meter(label, w) {
  const c = el("div", "card meter");
  c.append(el("div", "muted", label));
  const pct = w && w.pct != null ? w.pct : null;
  c.append(el("div", "v", pct == null ? "?" : Math.round(pct) + "%"));
  const t = el("div", "track"), f = el("div", "fill" + (pct >= 80 ? " hot" : pct >= 60 ? " warn" : ""));
  f.style.width = (pct || 0) + "%"; t.append(f); c.append(t);
  if (w && w.resets_at) c.append(el("div", "muted", "resets " + new Date(w.resets_at * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))); 
  return c;
}
function render(s) {
  $("upd").textContent = "updated " + new Date().toLocaleTimeString();
  const b = $("banner"); b.hidden = !s.paused; b.textContent = s.paused ? "PAUSED: kill switch is on. Running tasks are stopped and none will start." : "";
  $("resume").hidden = !s.paused;
  const m = $("meters"); m.replaceChildren(meter("Claude 5-hour", s.usage.five_hour), meter("Claude week", s.usage.week));
  if (s.usage.five_hour && s.usage.five_hour.pct == null || s.usage.error) m.append(el("div", "muted", "Usage: " + (s.usage.error ? "problem reading it (" + s.usage.error + ")" : "no exact numbers")));
  const jobs = $("jobs"); jobs.replaceChildren();
  if (!s.jobs.length) jobs.append(el("div", "muted", "No tasks yet."));
  for (const j of s.jobs) {
    const cls = j.status.replace(" ", "");
    const card = el("div", "job " + (j.status === "timed out" ? "timed" : cls));
    const top = el("div", "top"); top.append(el("span", "chip " + (j.status === "timed out" ? "timed" : cls), j.status));
    top.append(el("span", "muted", [j.voice ? "voice" : "helper", j.worker, dur(j.seconds), ago(j.age)].filter(Boolean).join(" · ")));
    if (j.stoppable) { const b2 = el("button", "stop", "Stop"); b2.onclick = () => post("/api/stop", { id: j.id }); top.append(b2); }
    card.append(top, el("div", "task", j.task || "(no description)"));
    for (const u of j.updates) card.append(el("div", "upd", "• " + u));
    if (j.status !== "running" && j.status !== "queued" && j.result) card.append(el("div", "res", j.result));
    jobs.append(card);
  }
  const calls = $("calls"); calls.replaceChildren();
  if (!s.calls.length) calls.append(el("div", "muted", "No calls yet."));
  for (const c of s.calls) {
    const d = el("div", "call"); const t = el("div", "top");
    t.append(el("span", "chip " + (c.status === "missed" ? "failed" : c.status === "answered" || c.status === "live" ? "succeeded" : "queued"), c.status));
    t.append(el("span", "muted", c.time ? new Date(c.time * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""));
    d.append(t, el("div", "task", c.reason || c.note || "")); calls.append(d);
  }
}
async function load() { try { const r = await fetch(P + "/api/state", { cache: "no-store" }); render(await r.json()); } catch (e) { $("upd").textContent = "offline, retrying"; } }
$("stopall").onclick = () => { if (confirm("Stop ALL voice tasks and block new ones until you press Resume?")) post("/api/stopall"); };
$("resume").onclick = () => post("/api/resume");
load(); setInterval(load, 5000);
