// puppet.js — "puppet" view: this page mirrors an EXTERNAL simulator instead of
// stepping its own arm. main.js branches here (?view=puppet) BEFORE creating any
// WebGL context, so we own the canvas. Use case: train headless in MuJoCo, publish
// sim.obs on the Robot Bus at ~30 Hz, watch/verify the run live in three.js.
//
// Renders per obs (all inputs optional — missing fields keep the last value):
//   data.q[5] (rad, ArmConfig order) + data.gripper (0..1) → the same FK rig/fabrik
//     visuals the local sim uses;   data.objects → boxes/spheres at pos/quat
//     (robot→three conversion via frames.js);   data.goal.pos → translucent marker;
//   data.ee.pos → green EE dot (falls back to FK TCP).
// HUD:  `source: <msg.src> · <scenario> · ep <ep> · step <step> · <stage>`  and, when
// train.metrics flows, a small training overlay (timesteps · success % · fps · nines).
// #status = `puppet step=<n> src=<src>`; after 2 s of silence → "waiting for sim…".
// The red error overlay (index.html pre-module hooks) still catches everything.

import * as THREE from "three";
import { buildArm } from "./robot.js";
import { BusClient } from "./bus.js";
import { Cameras } from "./cameras.js";
import { ARM_CONFIG } from "./arm_config.js";
import { r2t, quatRobotToThree, clamp } from "./frames.js";

// mirrors main.js's table so the arm sits on the same worktop
function addRoom(scene) {
  scene.background = new THREE.Color(0x0a0f14);
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(0.6, 1.2, 0.4);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x88aaff, 0.4);
  fill.position.set(-0.5, 0.4, -0.6);
  scene.add(fill);
  const table = new THREE.Mesh(new THREE.BoxGeometry(0.90, 0.04, 0.72),
    new THREE.MeshStandardMaterial({ color: 0x1d2a36, roughness: 0.8 }));
  table.position.set(0, -0.02, -0.30);
  scene.add(table);
  const grid = new THREE.GridHelper(1.2, 24, 0x2a3a4a, 0x17222c);
  grid.position.y = 0.001;
  scene.add(grid);
}

function el(tag, id, parent, text) {
  const e = document.createElement(tag);
  if (id) e.id = id;
  if (text !== undefined) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}

function bootPanel(title) {
  const p = el("div", null, document.body);
  p.className = "panel";
  p.style.cssText = "position:absolute;top:10px;left:10px;z-index:5;max-width:430px";
  el("h3", null, p, title).style.cssText = "margin:2px 0 4px;font-size:11px;letter-spacing:.12em;color:#7d95aa;text-transform:uppercase";
  return p;
}

const fin = (v, lo = -1e9, hi = 1e9) => (Number.isFinite(Number(v)) ? clamp(Number(v), lo, hi) : null);
const arr3 = (v) => (Array.isArray(v) && v.length >= 3 && v.every((x) => Number.isFinite(Number(x)))) ? [Number(v[0]), Number(v[1]), Number(v[2])] : null;

// robot-frame quaternion [w,x,y,z] → three {x,y,z,w}; identity when missing/bad
function robotQuatToThree(wxyz) {
  const [w, x, y, z] = wxyz;
  const m = [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ];
  const q = quatRobotToThree(m);
  return new THREE.Quaternion(q[1], q[2], q[3], q[0]);
}

// deterministic object colour from id (so the same cube keeps its colour across runs)
function idColor(id) {
  let h = 0;
  for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) | 0;
  return [0xffaa33, 0x4da6f2, 0x59cc66, 0xfa9e33, 0xb07df2][Math.abs(h) % 5];
}

export function bootPuppet() {
  const $ = (id) => document.getElementById(id);
  const query = new URLSearchParams(location.search);
  const hubUrl = query.get("hub") || "ws://127.0.0.1:8890/ws";
  if (window.__armsmithBoot) window.__armsmithBoot.boot = true;

  // the sim HUD is meaningless here — swap it for puppet panels, keep #stats
  for (const id of ["hud", "help", "pip", "mocapPanel"]) {
    const e = $(id);
    if (e) e.style.display = "none";
  }

  let renderer = null;
  const canvas = $("view");
  let renderBroken = false;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(window.innerWidth, window.innerHeight, false);
  } catch (e) {
    renderBroken = true;
    console.warn("puppet: WebGL unavailable — bus/HUD still live", e);
  }

  const scene = new THREE.Scene();
  addRoom(scene);
  const armVis = buildArm(scene, ARM_CONFIG);
  armVis.targetGizmo.visible = false; // no local IK target; obs.ik_target re-enables it
  armVis.eeDot.visible = true;

  // translucent goal marker (data.goal.pos)
  const goalMarker = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045, 0.045, 0.012, 20),
    new THREE.MeshStandardMaterial({ color: 0x4be07a, transparent: true, opacity: 0.35, emissive: 0x114422 }));
  goalMarker.visible = false;
  scene.add(goalMarker);
  const goalBeam = new THREE.Mesh(
    new THREE.CylinderGeometry(0.003, 0.003, 1, 6),
    new THREE.MeshBasicMaterial({ color: 0x4be07a, transparent: true, opacity: 0.25 }));
  goalBeam.visible = false;
  scene.add(goalBeam);

  const cams = new Cameras(canvas);
  window.addEventListener("resize", () => {
    if (!renderer) return;
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    cams.current.aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
    cams.current.updateProjectionMatrix();
  });

  // minimal camera controls (RMB orbit / MMB pan / wheel zoom) — no IK here to steal them
  let drag = null;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, b: e.button }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.b === 2) cams.orbitBy(dx, dy);
    else if (drag.b === 1) cams.panBy(dx, dy);
  });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); cams.zoomBy(e.deltaY); }, { passive: false });

  // ---- HUD panels -----------------------------------------------------------
  const hud = bootPanel("puppet — external sim");
  const hudLine = el("div", "puppetSrc", hud, "source: — · waiting for sim…");
  hudLine.style.cssText = "color:#cfe3f5;white-space:pre";
  const hudObs = el("div", "puppetObs", hud, "obs received: 0");
  hudObs.style.cssText = "color:#7d95aa;margin-top:2px;white-space:pre";
  const met = el("div", "puppetMetrics", hud, "");
  met.style.cssText = "display:none;margin-top:5px;padding-top:5px;border-top:1px solid #2a3a4a;color:#ffc14d;white-space:pre";

  const state = {
    lastObsT: -1e9, obsCount: 0, metrics: null, angles: ARM_CONFIG.home.slice(),
    close: 0, objects: new Map(), eePos: null, src: null, step: 0,
  };

  function fmtMetrics(d) {
    const ts = d.timesteps ?? d.global_step;
    const succ = d.success_rate ?? (d.success_pct != null ? Number(d.success_pct) / 100 : d.success);
    const fr = d.failure_rate ?? (succ != null ? 1 - succ : null);
    const nines = d.nines ?? (Number.isFinite(fr) && fr > 0 ? (-Math.log10(Math.max(fr, 1e-9))).toFixed(2) : "—");
    const fps = Number.isFinite(Number(d.fps)) ? Number(d.fps).toFixed(0) : "—";
    return `train ${d.run || d.policy || ""} [${d.stage || "train"}]  ts ${ts ?? "—"}  ·  success ${succ != null ? Math.round(succ * 100) + "%" : "—"}  ·  ${fps} fps  ·  nines ${nines}`;
  }

  function applyObs(d, env) {
    state.lastObsT = Date.now() / 1000;   // wall clock: obs arrive in real time,
    state.obsCount++;
    state.src = (env && env.src) || state.src || "sim";
    state.step = Number(d.step) || state.step;

    // 5 joint radians (ArmConfig order = publish order) + gripper through the FK rig
    const q = Array.isArray(d.q) ? d.q : null;
    if (q && q.length >= 5 && q.every((x) => Number.isFinite(Number(x)))) {
      state.angles = q.slice(0, 5).map(Number);
    }
    const grip = fin(d.gripper, 0, 1);
    if (grip !== null) state.close = grip;

    const ik = arr3(d.ik_target);
    armVis.targetGizmo.visible = !!ik;
    const F = armVis.apply({ angles: state.angles, close: state.close, ikTargetWorld: ik || undefined });

    // EE marker at the PUBLISHED ee.pos (falls back to FK TCP)
    const ee = arr3(d.ee && d.ee.pos);
    if (ee) { state.eePos = ee; armVis.eeDot.position.set(...r2t(ee)); }
    else armVis.eeDot.position.set(...r2t(F.tcp));

    // goal marker (translucent puck + drop beam)
    const goal = arr3(d.goal && d.goal.pos);
    goalMarker.visible = goalBeam.visible = !!goal;
    if (goal) {
      const g = r2t(goal);
      goalMarker.position.set(g[0], 0.008, g[2]);
      goalBeam.position.set(g[0], g[1] / 2, g[2]);
      goalBeam.scale.y = Math.max(0.05, g[1]);
    }

    // objects: boxes/spheres at pos/quat (robot frame → three frame)
    const seen = new Set();
    for (const o of Array.isArray(d.objects) ? d.objects : []) {
      const p = arr3(o.pos);
      if (!o.id || !p) continue;
      seen.add(o.id);
      let m = state.objects.get(o.id);
      const isSphere = /ball|sphere/i.test(String(o.id)) || /sphere/i.test(String(o.shape || ""));
      if (!m) {
        const col = idColor(o.id);
        m = isSphere
          ? new THREE.Mesh(new THREE.SphereGeometry(0.03, 16, 12), new THREE.MeshStandardMaterial({ color: col, roughness: 0.5 }))
          : new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 0.04), new THREE.MeshStandardMaterial({ color: col, roughness: 0.5 }));
        scene.add(m);
        state.objects.set(o.id, m);
      }
      m.position.set(...r2t(p));
      const qt = Array.isArray(o.quat) && o.quat.length >= 4 && o.quat.every((x) => Number.isFinite(Number(x)))
        ? robotQuatToThree(o.quat.map(Number)) : new THREE.Quaternion();
      m.quaternion.copy(qt);
      if (m.material.emissive) m.material.emissive.setHex(o.grasped ? 0x335511 : 0x000000);
    }
    for (const [id, m] of state.objects) {
      if (!seen.has(id)) { scene.remove(m); state.objects.delete(id); }
    }

    // HUD + status (the fields the mission-control page and smoke test assert on)
    const prog = d.progress || {};
    hudLine.textContent = `source: ${state.src} · ${d.scenario || "?"} · ep ${d.ep ?? "?"} · step ${state.step} · ${prog.stage || "?"}`;
    hudObs.textContent = `obs received: ${state.obsCount}  last: ${d.stall && d.stall.stalled ? "STALLED " : ""}${d.stall ? "score " + Number(d.stall.score).toFixed(2) : ""}`;
    $("status").textContent = `puppet step=${state.step} src=${state.src}`;
    // data-* attrs are the authoritative headless-test signal: only obs writes them,
    // the 2 s "waiting for sim…" watchdog never touches them.
    $("status").dataset.step = String(state.step);
    $("status").dataset.src = state.src;
    $("epCount").textContent = d.ep ?? 0;
    $("stallbar").style.width = `${Math.round((fin(d.stall && d.stall.score, 0, 1) || 0) * 100)}%`;
    $("stallbar").style.background = d.stall && d.stall.stalled ? "#ff5d5d" : "#4be07a";
    $("stalltxt").textContent = d.stall
      ? `stall: ${d.stall.stalled ? "STALLED" : "ok"} score=${Number(d.stall.score || 0).toFixed(2)} ${(d.stall.reasons || []).join(",")}`
      : "stall: —";
    if (window.__armsmithBoot) window.__armsmithBoot.step = state.step;
    window.__puppet = { step: state.step, obs: state.obsCount, src: state.src };
  }

  const bus = new BusClient({
    url: hubUrl,
    subscribe: ["sim.obs", "train.metrics"], // high-rate opt-in per PROTOCOL.md
    handlers: {
      onObs: applyObs,
      onMetrics: (d) => {
        state.metrics = d;
        met.style.display = "block";
        met.textContent = fmtMetrics(d);
      },
      onStatus: (t) => { $("busstat").textContent = `puppet ${t}  · obs recv=${bus.obsRecv} metrics=${bus.metricsRecv}`; },
      onRoster: () => { /* busstat carries connection info */ },
    },
  });

  // 2 s watchdog → "waiting for sim…" (also renders; see note below on headless).
  // Wall clock (Date.now), not performance.now: under virtual-time harnesses the
  // monotonic clock is warped and outruns the real-time websocket obs stream, so the
  // watchdog would fire between two live obs. Silence is a REAL-time concept here.
  setInterval(() => {
    const silent = Date.now() / 1000 - state.lastObsT > 2;
    if (silent) {
      $("status").textContent = "waiting for sim…";
      if (state.obsCount === 0) hudLine.textContent = `source: — · waiting for sim… (bus ${bus.connected ? "connected" : "offline"} @ ${hubUrl})`;
    }
    if (!renderBroken) {
      renderer.setViewport(0, 0, window.innerWidth, window.innerHeight);
      renderer.setScissorTest(false);
      renderer.render(scene, cams.current);
    }
  }, 100);

  window.__puppetBoot = { hubUrl, renderBroken };
}
