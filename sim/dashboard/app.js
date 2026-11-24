// app.js — robot_learning mission-control dashboard (zero-build, no libs).
// Data sources:
//   · WebSocket to the hub (bus protocol v1): train.metrics (charts/nines/header),
//     ctl.stall + ctl.recovery (stall-loop panel), sim.event episode_end (escalation
//     success heuristic). ctl.* are ordinary blackboard topics; train.metrics would
//     also arrive by default — we subscribe anyway for clarity.
//   · HTTP GET <hub>/roster + /health every 3 s (fetch, guarded — the page never
//     errors and retries forever when the hub is down).
// Params: ?hub=ws://127.0.0.1:8890/ws · ?puppet=http://127.0.0.1:8891/?view=puppet
"use strict";

(() => {
  const q = new URLSearchParams(location.search);
  const hubWs = q.get("hub") || "ws://127.0.0.1:8890/ws";
  const hubHttp = hubWs.replace(/\/ws\/?$/, "").replace(/^ws/, "http");
  const puppetUrl = q.get("puppet") || "http://127.0.0.1:8891/?view=puppet";

  const $ = (id) => document.getElementById(id);
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const fmtN = (v, dp = 2) => (v == null ? "—" : v.toFixed(dp));

  const S = {
    metrics: null,        // last normalized train.metrics
    success: [],          // [{ts, v}]
    rew: [],              // [{ts, v}]
    wsUp: false, httpUp: false,
    stalls: 0, recov: {}, recovTotal: 0, recovEps: {}, escOk: 0, escFail: 0,
    lastStallKey: null, firstSeen: null,
  };

  // ---------- helpers ----------
  const fmtUptime = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
    return h ? `${h}h${String(m).padStart(2, "0")}m` : m ? `${m}m${String(ss).padStart(2, "0")}s` : `${ss}s`;
  };
  const fmtElapsed = (s) => {
    if (s == null) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = Math.floor(s % 60);
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${m}:${String(ss).padStart(2, "0")}`;
  };

  function normalize(d) {
    const succ = num(d.success_rate) ?? (num(d.success_pct) != null ? d.success_pct / 100 : num(d.success));
    const fail = num(d.failure_rate) ?? (succ != null ? 1 - succ : null);
    const baseFail = num(d.baseline_failure_rate) ?? (num(d.baseline_success_rate) != null ? 1 - d.baseline_success_rate : null);
    const nines = num(d.nines) ?? (fail != null && fail > 0 ? -Math.log10(Math.max(fail, 1e-9)) : null);
    const baseNines = num(d.baseline_nines) ?? (baseFail != null && baseFail > 0 ? -Math.log10(Math.max(baseFail, 1e-9)) : null);
    return {
      run: d.run || d.run_name || "—",
      policy: d.policy || d.algo || "—",
      stage: d.stage || "—",
      fps: num(d.fps),
      timesteps: num(d.timesteps) ?? num(d.global_step) ?? num(d.ts),
      epRew: num(d.ep_rew_mean) ?? num(d.reward_mean) ?? num(d.rew_mean),
      succ, fail, nines, baseNines, baseFail,
      elapsed: num(d.elapsed_s),
    };
  }

  // ---------- banner ----------
  function setBanner() {
    const b = $("busBanner");
    const up = S.wsUp || S.httpUp;
    b.textContent = up ? "bus online · " + hubHttp + "  (ws " + (S.wsUp ? "up" : "down") + ")" : "bus offline — retrying…";
    b.className = "banner " + (up ? "ok" : "warn");
  }

  // ---------- websocket (train.metrics / ctl.* / sim.event) ----------
  let ws = null, wsRetry = 0;
  function connectWs() {
    try {
      ws = new WebSocket(hubWs);
    } catch (e) { S.wsUp = false; setBanner(); setTimeout(connectWs, 3000); return; }
    ws.onopen = () => {
      S.wsUp = true; wsRetry = 0; setBanner();
      const send = (o) => { try { ws.send(JSON.stringify(o)); } catch (e) { /* never */ } };
      send({ v: 1, id: crypto.randomUUID(), ts: Date.now() / 1000, src: "dashboard", topic: "bus.hello", data: { name: "dashboard", roles: ["viewer"], caps: [] } });
      send({ v: 1, id: crypto.randomUUID(), ts: Date.now() / 1000, src: "dashboard", topic: "bus.sub", data: { topics: ["train.metrics"] } });
    };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (!m || typeof m !== "object") return;
      handleBus(m.topic, m.data || {}, m);
    };
    ws.onclose = () => { S.wsUp = false; setBanner(); wsRetry++; setTimeout(connectWs, Math.min(3000, 500 * wsRetry)); };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* never */ } };
  }

  function handleBus(topic, d, m) {
    if (topic === "train.metrics") {
      const n = normalize(d);
      if (n.timesteps != null) {
        if (S.firstSeen == null) S.firstSeen = Date.now() / 1000;
        if (n.succ != null) S.success.push({ ts: n.timesteps, v: n.succ });
        if (n.epRew != null) S.rew.push({ ts: n.timesteps, v: n.epRew });
        if (S.success.length > 2000) S.success.splice(0, S.success.length - 2000);
        if (S.rew.length > 2000) S.rew.splice(0, S.rew.length - 2000);
      }
      S.metrics = n;
      renderMetrics();
      drawCharts();
    } else if (topic === "ctl.stall") {
      const key = `${d.ep}:${d.step}`;
      if (key !== S.lastStallKey) { S.lastStallKey = key; S.stalls++; renderStall(); }
    } else if (topic === "ctl.recovery") {
      const src = d.source || "unknown";
      S.recov[src] = (S.recov[src] || 0) + 1;
      S.recovTotal++;
      if (d.ep != null) S.recovEps[d.ep] = src;
      renderStall();
    } else if (topic === "sim.event" && d.kind === "episode_end" && d.ep != null) {
      if (d.ep in S.recovEps) { (d.outcome === "success" ? S.escOk++ : S.escFail++); delete S.recovEps[d.ep]; renderStall(); }
    } else if (topic === "sim.event" && d.kind === "episode_start" && d.ep != null) {
      delete S.recovEps[d.ep];
    }
  }

  // ---------- renderers ----------
  function renderMetrics() {
    const n = S.metrics;
    if (!n) return;
    $("runField").textContent = n.run;
    $("policyField").textContent = n.policy;
    $("stageField").textContent = n.stage;
    $("fpsField").textContent = fmtN(n.fps, 0);
    $("tsField").textContent = n.timesteps != null ? n.timesteps.toLocaleString("en-US") : "—";
    $("elapsedField").textContent = fmtElapsed(n.elapsed ?? (S.firstSeen != null ? Date.now() / 1000 - S.firstSeen : null));

    const cur = $("nines"), base = $("ninesBase");
    cur.textContent = n.nines != null ? n.nines.toFixed(2) : "—";
    base.textContent = n.baseNines != null ? n.baseNines.toFixed(2) : "—";
    cur.classList.toggle("down", n.baseNines != null && n.nines != null && n.nines < n.baseNines);
    const arrow = $("ninesArrow");
    if (n.baseNines != null && n.nines != null) {
      const delta = n.nines - n.baseNines;
      arrow.textContent = delta >= 0 ? "▲" : "▼";
      arrow.style.color = delta >= 0 ? "var(--ok)" : "var(--bad)";
    } else arrow.textContent = "→";
    $("ninesDetail").textContent =
      `failure_rate ${fmtN(n.fail, 3)} · baseline_failure_rate ${fmtN(n.baseFail, 3)} · ` +
      (n.baseNines != null && n.nines != null ? `${n.nines >= n.baseNines ? "+" : ""}${(n.nines - n.baseNines).toFixed(2)} nines vs baseline` : "waiting for baseline");
  }

  function renderStall() {
    $("stallCount").textContent = S.stalls;
    $("recovCount").textContent = S.recovTotal;
    $("escOk").textContent = S.escOk;
    $("escFail").textContent = S.escFail;
    const body = $("recovBody");
    const keys = Object.keys(S.recov);
    body.innerHTML = keys.length
      ? keys.map((k) => `<tr><td>${k}</td><td>${S.recov[k]}</td></tr>`).join("")
      : '<tr class="empty"><td colspan="2">no ctl.recovery yet</td></tr>';
  }

  function renderRoster(clients) {
    const body = $("rosterBody");
    if (!Array.isArray(clients) || !clients.length) {
      body.innerHTML = '<tr class="empty"><td colspan="4">nobody on the bus</td></tr>';
      return;
    }
    body.innerHTML = clients.map((c) =>
      `<tr><td>${c.name || "—"}</td><td>${(c.roles || []).join(",") || "—"}</td>` +
      `<td>${fmtUptime(c.uptime_s)}</td><td>${c.rx != null ? c.rx + "/" + c.tx : "—"}</td></tr>`).join("");
  }

  // ---------- charts (plain canvas, autoscale, last-value labels) ----------
  function drawChart(canvas, pts, color, fmt) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || canvas.width, h = canvas.clientHeight || canvas.height;
    if (canvas.width !== Math.round(w * dpr)) canvas.width = Math.round(w * dpr);
    if (canvas.height !== Math.round(h * dpr)) canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = "10px " + "ui-monospace, monospace";

    if (pts.length < 1) {
      ctx.fillStyle = "#7d95aa";
      ctx.fillText("waiting for train.metrics…", 12, 20);
      return;
    }
    const xs = pts.map((p) => p.ts), ys = pts.map((p) => p.v);
    let x0 = Math.min(...xs), x1 = Math.max(...xs);
    if (x1 - x0 < 1e-9) { x0 -= 1; x1 += 1; }
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    const yPad = (y1 - y0) * 0.12 || Math.abs(y1) * 0.1 || 0.5;
    y0 -= yPad; y1 += yPad;
    const padL = 38, padR = 64, padT = 10, padB = 18;
    const px = (t) => padL + ((t - x0) / (x1 - x0)) * (w - padL - padR);
    const py = (v) => padT + (1 - (v - y0) / (y1 - y0)) * (h - padT - padB);

    // grid + y labels
    ctx.strokeStyle = "#1a2530"; ctx.fillStyle = "#7d95aa";
    for (let i = 0; i <= 3; i++) {
      const v = y0 + ((y1 - y0) * i) / 3, yy = py(v);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
      ctx.fillText(v.toFixed(2), 4, yy + 3);
    }
    // x labels
    ctx.fillText(String(Math.round(x0)), padL, h - 4);
    const endLab = String(Math.round(x1));
    ctx.fillText(endLab, w - padR - ctx.measureText(endLab).width, h - 4);

    // line
    ctx.strokeStyle = color; ctx.lineWidth = 1.6;
    ctx.beginPath();
    pts.forEach((p, i) => { const X = px(p.ts), Y = py(p.v); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.stroke();
    // last point + label
    const last = pts[pts.length - 1];
    const lx = px(last.ts), ly = py(last.v);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(lx, ly, 3, 0, 2 * Math.PI); ctx.fill();
    const lab = fmt(last.v);
    ctx.fillStyle = "#d7e6f5";
    ctx.fillText(lab, Math.min(lx + 6, w - padR + 4), ly - 5);
  }

  function drawCharts() {
    try {
      drawChart($("chartSuccess"), S.success, "#4be07a", (v) => (v * 100).toFixed(1) + "%");
      drawChart($("chartReward"), S.rew, "#ffc14d", (v) => v.toFixed(2));
    } catch (e) { /* charts must never break the page */ }
  }

  // ---------- HTTP polls (roster + health), guarded, every 3 s ----------
  async function pollOnce(path) {
    const r = await fetch(hubHttp + path, { cache: "no-store" });
    if (!r.ok) throw new Error("http " + r.status);
    return r.json();
  }
  async function tick() {
    try {
      const roster = await pollOnce("/roster");
      S.httpUp = true;
      // /roster returns a bare array of client info; be liberal in what we accept
      const list = Array.isArray(roster) ? roster : ((roster && roster.clients) || []);
      renderRoster(list);
    } catch (e) {
      S.httpUp = false;
      renderRoster([]);
    }
    setBanner();
  }

  // ---------- boot ----------
  const frame = $("puppetFrame");
  const src = $("puppetSrc");
  try {
    const sep = puppetUrl.includes("?") ? "&" : "?";
    const full = q.get("hub") && !puppetUrl.includes("hub=") ? puppetUrl + sep + "hub=" + encodeURIComponent(hubWs) : puppetUrl;
    frame.src = full;
    src.textContent = full;
  } catch (e) { frame.src = puppetUrl; }

  setBanner();
  renderRoster([]);
  renderStall();
  connectWs();
  tick();
  setInterval(tick, 3000);
  setInterval(drawCharts, 1000);
  window.__dash = S; // headless-test / debugging handle
})();
