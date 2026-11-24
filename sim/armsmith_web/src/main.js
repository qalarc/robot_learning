// main.js — ARMSMITH web app shell: boots physics + visuals + bus, runs the fixed-step
// loop (run → capture → detect stall → agents fix → run again), builds sim.obs, and
// handles every sim.cmd from docs/PROTOCOL.md.
// ?autotest=1 → headless smoke mode (bus counters into #busstat after ~2 s)
// ?hub=ws://host:port/ws → bus URL override   ?physics=dynamic → rapier dynamic arm
// ?scenario=name → starting scenario          ?view=puppet → mirror an external sim (puppet.js)

import * as THREE from "three";
import { Physics } from "./physics.js";
import { buildArm } from "./robot.js";
import { ArmController } from "./arm_controller.js";
import { Scenario, SCENARIOS } from "./scenarios.js";
import { StallDetector } from "./stall.js";
import { BusClient } from "./bus.js";
import { Recorder, downloadText } from "./recorder.js";
import { Cameras } from "./cameras.js";
import { UI } from "./ui.js";
import { r2t, quatRobotToThree, t2r } from "./frames.js";
import { matToQuat } from "./frames.js";
import { ARM_CONFIG } from "./arm_config.js";
import { fk as robotFk } from "./robot.js";

// ---------- error overlay: hooks installed pre-module in index.html ----------
const errOverlay = document.getElementById("errOverlay");
const errText = document.getElementById("errText");
const showError = window.__showRuntimeError || ((w, d) => {
  errText.textContent += `\n[${w}] ${d}`;
  errOverlay.style.display = "block";
});

const $ = (id) => document.getElementById(id);
if (window.__armsmithBoot) window.__armsmithBoot.module = true;

// ?view=puppet → this page is a DISPLAY for an EXTERNAL simulator: puppet.js mirrors
// sim.obs published on the Robot Bus (headless MuJoCo training → watch in three.js).
// We skip creating the WebGL context here so the two apps never share one canvas, and
// boot() (physics/loop/UI) never runs — see the branch at the bottom of this file.
const PUPPET = new URLSearchParams(location.search).get("view") === "puppet";

// ---------- three scene ----------
const canvas = $("view");
let renderer = null, renderBroken = false;
if (!PUPPET) {
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    renderer.autoClear = true;
  } catch (e) {
    renderBroken = true;
    console.warn("WebGL unavailable — continuing WITHOUT rendering (physics/telemetry still run)", e);
  }
}

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0f14);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.5);
sun.position.set(0.6, 1.2, 0.4);
scene.add(sun);
const fill = new THREE.DirectionalLight(0x88aaff, 0.4);
fill.position.set(-0.5, 0.4, -0.6);
scene.add(fill);

// worktop visual (top at three y=0)
{
  const table = new THREE.Mesh(new THREE.BoxGeometry(0.90, 0.04, 0.72),
    new THREE.MeshStandardMaterial({ color: 0x1d2a36, roughness: 0.8 }));
  table.position.set(0, -0.02, -0.30);
  scene.add(table);
  const grid = new THREE.GridHelper(1.2, 24, 0x2a3a4a, 0x17222c);
  grid.position.y = 0.001;
  scene.add(grid);
}

// wrist-cam picture-in-picture (renderer scissor viewport)
const pip = $("pip");

// ---------- core objects ----------
const query = new URLSearchParams(location.search);
const autotest = query.has("autotest");
const physicsMode = query.get("physics") === "dynamic" ? "dynamic" : "kinematic";
const hubUrl = query.get("hub") || "ws://127.0.0.1:8890/ws";
const startScenario = SCENARIOS.includes(query.get("scenario")) ? query.get("scenario") : "pick_place";

let physics, armVis, ctl, scenario, stallDet, recorder, cams, ui, bus;
const state = {
  step: 0, t: 0, ep: 0, ok: 0, fail: 0,
  obsHz: 30, assist: true, record: false,
  lastServoDeg: null, frame: 0,
  objectMeshes: new Map(),
  lastHands: null, lastHandsT: -1e9,
  stallAnnounced: false, epEnded: false, lastStall: { stalled: false, score: 0, steps: 0, reasons: [] },
};

const DT = 1 / 60;

async function boot() {
  physics = await Physics.create();
  physics.setMode(physicsMode, ARM_CONFIG, (i) => sampleFk(i));
  ctl = new ArmController(ARM_CONFIG);
  armVis = buildArm(scene, ARM_CONFIG);
  scenario = new Scenario(startScenario, physics, scene);
  stallDet = new StallDetector();
  recorder = new Recorder();
  cams = new Cameras(canvas);

  ui = new UI({
    ctl, cameras: cams, canvas, bus: null,
    onScenario: (name) => { $("scenSel").value = name; resetEpisode(name); bus.publishEvent({ kind: "scenario_change", scenario: name, ep: scenario.epIndex }); },
    onReset: () => resetEpisode(),
    onHome: () => ctl.home(),
    onGripToggle: () => ctl.cmdGripper(ctl.closeCmd > 0.5 ? 1 : 0),
    onRecord: () => toggleRecord(),
    onExportEp: () => exportEp(),
    onExportAll: () => exportAll(),
    onAssist: (v) => { state.assist = v; },
    onPhysics: (m) => { physics.setMode(m, ARM_CONFIG, (i) => sampleFk(i)); ui.setPhysics(m); },
    onObsHz: (hz) => { bus.obsHz = hz; },
  });

  bus = new BusClient({
    url: hubUrl,
    handlers: {
      onCmd: handleCmd,
      onHands: (data) => { state.lastHands = data; state.lastHandsT = performance.now() / 1000; },
      onStatus: (text) => ui.setBusstat(text),
      onRoster: (data) => { /* roster shows clients; keep busstat for traffic */ },
    },
  });
  ui.setPhysics(physicsMode);
  $("modeSel").value = ctl.mode;
  $("scenSel").value = scenario.name;

  // episode bookkeeping
  state.ep = scenario.epIndex;
  recorder.start(state.ep, scenario.name, scenario.seed);
  bus.publishEvent({ kind: "episode_start", ep: scenario.epIndex, scenario: scenario.name, seed: scenario.seed });

  setInterval(loop, 16);
  booted = true;
  if (window.__armsmithBoot) window.__armsmithBoot.boot = true;
  if (autotest) setTimeout(autotestTick, 2000);
  // ?meshcheck=1 → headless FK acceptance probe (5 targets, ±15 mm), also reports
  // which visual path loaded (meshes=stl|capsule) — see test/smoke_meshes.sh
  if (query.has("meshcheck")) runMeshcheck();
}

// ---------- ?meshcheck=1 — FK acceptance probe + mesh-path report ----------
// Drives the CONTROLLER (IK + servo chain) to five calibration targets and checks the
// FK TCP lands within ±15 mm of each — the acceptance bound the rig was tuned to
// (README: IK residual ≤ ~1 cm). Runs the probe in whatever visual path loaded; STL
// fetches must not move FK (meshes are visual-only), so PASS is expected either way.
let meshcheckNote = "";
// Probe targets live in the WELL-CONDITIONED working band (radius 0.19–0.28 m from
// the pan pivot). The close-in envelope (<~0.17 m) is genuinely unreachable — the
// solver reports the honest residual there (README "Known limitations") — so probing
// it would measure the mechanism, not the calibration.
const MESHCHECK_TARGETS = [
  [0.22, 0.00, 0.12], [0.20, 0.10, 0.10], [0.26, -0.06, 0.06],
  [0.20, 0.00, 0.18], [0.24, 0.12, 0.08],
];
async function runMeshcheck() {
  window.__meshcheckRunning = true;
  // wait for the STL fetches to SETTLE (resolve on allSettled semantics, no timers —
  // a failed fetch resolves quickly into the capsule fallback and the probe still runs)
  await armVis.meshesReady;
  ui.setMeshPath(armVis.meshState.path);
  ctl.setMode("ik");
  let maxErr = 0;
  const errs = [];
  try {
    for (const t of MESHCHECK_TARGETS) {
      ctl.setMouseTarget(t);
      ctl.setMode("ik");                    // keep probe mode even alongside ?autotest=1
      for (let i = 0; i < 240; i++) ctl.tick(DT);   // 4 s simulated convergence
      const tcp = ctl.lastFk.tcp;
      const err = Math.hypot(tcp[0] - t[0], tcp[1] - t[1], tcp[2] - t[2]) * 1000;
      errs.push(err);
      maxErr = Math.max(maxErr, err);
    }
  } catch (e) {
    meshcheckNote = `meshcheck FAIL (${e && e.message}) meshes=${armVis.meshState.path}`;
    window.__armsmithMesh = { meshcheck: "FAIL", error: String(e), meshes: armVis.meshState.path };
    return;
  }
  const pass = maxErr <= 15.0;
  const perTarget = errs.map((e) => e.toFixed(0)).join(",");
  meshcheckNote = `meshcheck ${pass ? "PASS" : "FAIL"} max_err=${maxErr.toFixed(1)}mm [${perTarget}] meshes=${armVis.meshState.path}`;
  window.__armsmithMesh = { meshcheck: pass ? "PASS" : "FAIL", maxErrMm: maxErr, meshes: armVis.meshState.path };
  window.__meshcheckRunning = false;
}

// FK sample accessor for physics.setMode (may run before the controller exists → home pose)
function sampleFk(i) {
  const f = ctl ? ctl.lastFk : robotFk(ARM_CONFIG.home, ARM_CONFIG);
  return f.joints[i];
}

// ---------- sim.cmd dispatch (PROTOCOL.md) ----------
function handleCmd(data, envelope) {
  const cmd = data.cmd, args = data.args || {};
  try {
    switch (cmd) {
      case "joint": ctl.cmdJoint(args.q || []); break;
      case "ee": ctl.cmdEe(args.pos || [0.2, 0, 0.1], { yaw: args.yaw, pitch: args.pitch, gripper: args.gripper, mode: args.mode }); break;
      case "gripper": ctl.cmdGripper(Number(args.open ?? 1)); break;
      case "scenario": resetEpisode(SCENARIOS.includes(args.name) ? args.name : null); break;
      case "reset": resetEpisode(args.scenario && SCENARIOS.includes(args.scenario) ? args.scenario : null, args.seed); break;
      case "mode": ctl.setMode(args.control || args.mode); $("modeSel").value = ctl.mode; break;
      case "play": ctl.cmdPlay(args.actions || [], args.fps || 30); break;
      case "set":
        if (args.obs_hz) bus.obsHz = Number(args.obs_hz);
        if ("record" in args) setRecord(!!args.record);
        break;
      case "ping":
        bus.reply(envelope, { pong: true, step: state.step, ep: state.ep, t: state.t, physics: physics.mode });
        break;
      case "snapshot": {
        const camName = ["free", "wrist", "env"].includes(args.cam) ? args.cam : "free";
        const w = Math.max(16, Math.min(1280, Number(args.w || 640)));
        const h = Math.max(16, Math.min(1280, Number(args.h || 480)));
        const jpeg = snapshot(camName, w, h);
        bus.reply(envelope, jpeg
          ? { jpeg_b64: jpeg, cam: camName, step: state.step }
          : { error: "render unavailable (headless software path)", cam: camName, step: state.step });
        break;
      }
      default:
        bus.publishLog("warn", `unknown sim.cmd '${cmd}'`);
    }
  } catch (e) {
    bus.publishLog("error", `sim.cmd ${cmd} failed: ${e && e.message}`);
  }
}

// ---------- snapshot: render cam → JPEG base64 (data: prefix stripped) ----------
function snapshot(camName, w, h) {
  if (renderBroken || !renderer) return null;
  const cam = cams.byName(camName);
  const oldW = renderer.domElement.width, oldH = renderer.domElement.height;
  const oldAspect = cam.aspect;
  try {
    renderer.setSize(w, h, false);
    cam.aspect = w / h;
    cam.updateProjectionMatrix();
    renderer.render(scene, cam);
    const url = renderer.domElement.toDataURL("image/jpeg", 0.8);
    return url.slice(url.indexOf(",") + 1);
  } catch (e) {
    console.warn("snapshot failed", e);
    return null;
  } finally {
    renderer.setSize(oldW, oldH, false);
    cam.aspect = oldAspect;
    cam.updateProjectionMatrix();
  }
}

// ---------- episode lifecycle ----------
function resetEpisode(name, seed) {
  scenario.reset(name || null, Number.isFinite(seed) ? seed : Math.floor(Math.random() * 1e9));
  state.ep = scenario.epIndex;
  state.epEnded = false;
  stallDet.reset();
  ctl.home();
  clearObjectMeshes();
  recorder.start(state.ep, scenario.name, scenario.seed);
  bus.publishEvent({ kind: "episode_start", ep: state.ep, scenario: scenario.name, seed: scenario.seed });
}

function endEpisode(outcome) {
  if (outcome === "success") state.ok++; else state.fail++;
  recorder.end(state.ep, outcome);
  bus.publishEvent({ kind: "episode_end", ep: state.ep, scenario: scenario.name, outcome, step: state.step, reward: scenario.reward });
  ui.setCounts(state.ok, state.fail);
  ui.setButtons(recorder.enabled, recorder.episodes);
  // auto-advance episodes (the loop keeps running — this is the march of nines)
  setTimeout(() => { if (scenario.done) resetEpisode(); }, 700);
}

function setRecord(on) {
  recorder.enabled = on;
  state.record = on;
  ui.setRec(on);
  ui.setButtons(on, recorder.episodes);
  if (on && !recorder.current) recorder.start(state.ep, scenario.name, scenario.seed);
}
function toggleRecord() { setRecord(!recorder.enabled); }
function exportEp() {
  if (!recorder.episodes.length) return;
  downloadText(`ep_${recorder.episodes[recorder.episodes.length - 1].ep}.jsonl`, recorder.toEpisodeJsonl(recorder.episodes.length - 1));
}
function exportAll() { downloadText("armsmith_episodes.jsonl", recorder.toAllJsonl()); }

// ---------- object visuals ----------
function clearObjectMeshes() {
  for (const m of state.objectMeshes.values()) scene.remove(m);
  state.objectMeshes.clear();
}
function syncObjectVisuals() {
  for (const rec of physics.objects.values()) {
    let mesh = state.objectMeshes.get(rec.id);
    if (!mesh) {
      mesh = new THREE.Mesh(new THREE.BoxGeometry(rec.size, rec.size, rec.size),
        new THREE.MeshStandardMaterial({ color: rec.color, roughness: 0.5 }));
      scene.add(mesh);
      state.objectMeshes.set(rec.id, mesh);
    }
    const p = rec.body.translation(), q = rec.body.rotation();
    mesh.position.set(p.x, p.y, p.z);
    mesh.quaternion.set(q.x, q.y, q.z, q.w);
  }
}

// ---------- main loop ----------
// The SIMULATION runs on a 16 ms setInterval: timers behave identically in real browsers
// and under headless virtual-time harnesses. Rendering alone rides requestAnimationFrame
// (headless may suppress frames — that must never stop physics/telemetry).
let lastT = performance.now() / 1000, acc = 0;
let renderQueued = false;
function loop() {
  const now = performance.now() / 1000;
  const dt = Math.min(0.1, now - lastT);
  lastT = now;
  ui.updateKeyboard(dt);

  // fixed-step control+physics (run → capture happens via obs/event publishing)
  acc += dt;
  let sub = 0;
  while (acc >= DT && sub < 8) {
    acc -= DT; sub++;
    stepOnce(DT);
  }

  syncObjectVisuals();

  // visuals from servo state (kinematic truth) or physics bodies (dynamic)
  armVis.apply({
    angles: ctl.servoDeg.map((d) => d * (Math.PI / 180)),
    close: ctl.closeCmd,
    ikTargetWorld: ctl.ikTarget,
  });

  // EE three pose for wrist cam + grasp
  const eePosThree = new THREE.Vector3(...r2t(ctl.lastFk.tcp));
  const eeQ = quatRobotToThree(matToQuat(ctl.lastFk.joints[4].mat));
  const eeQuatThree = new THREE.Quaternion(eeQ[1], eeQ[2], eeQ[3], eeQ[0]);
  cams.updateWrist(eePosThree, eeQuatThree);

  state.frame++;
  if (state.frame % 8 === 0) {
    $("status").textContent = `running step=${state.step}${meshcheckNote ? "\n" + meshcheckNote : ""}`;
    if (window.__armsmithBoot) window.__armsmithBoot.step = state.step;
    ui.refresh(ctl.lastFk ? ctl.servoDeg.map((d) => d * (Math.PI / 180)) : [0, 0, 0, 0, 0],
      ctl.closeCmd, state.lastStall || { score: 0, stalled: false, reasons: [] },
      { ep: state.ep });
    ui.setCounts(state.ok, state.fail);
  }

  // obs publishing + busstat every few frames
  if (state.lastObs) bus.publishObs(state.lastObs, dt);
  if (state.frame % 12 === 0) {
    const b = bus;
    ui.setBusstat(`bus: ${b.connected ? "connected" : "offline"} sent=${b.sent} (obs ${b.obsSent}) recv=${b.recv} (cmds ${b.recvCmds}) to=${b.name}@${b.url}`);
  }

  if (!renderBroken) requestRender();
}

function requestRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderer.setViewport(0, 0, window.innerWidth, window.innerHeight);
    renderer.setScissorTest(false);
    renderer.render(scene, cams.current);
    // wrist PiP
    const r = pip.getBoundingClientRect();
    renderer.setScissorTest(true);
    renderer.setViewport(window.innerWidth - r.width - 10, 10, r.width, r.height - 4);
    renderer.setScissor(window.innerWidth - r.width - 10, 10, r.width, r.height - 4);
    renderer.render(scene, cams.wrist);
    renderer.setScissorTest(false);
  });
}

function stepOnce(dt) {
  state.step++;
  state.t += dt;

  // mocap control (vision.hands → EE target; hold last 0.6 s)
  if (ctl.mode === "mocap") {
    const fresh = state.lastHands && (performance.now() / 1000 - state.lastHandsT) < 0.6;
    ctl.updateMocap(fresh ? (state.lastHands.hands || []) : null, performance.now() / 1000);
  }

  ctl.tick(dt);

  // drive physics: kinematic FK poses or dynamic motor targets
  physics.updateArm(null, ctl.servoDeg.map((d) => d * (Math.PI / 180)), ctl.lastFk, ctl.closeCmd, ARM_CONFIG);

  // grasp (assist attach / release)
  const eePosThree = { x: r2t(ctl.lastFk.tcp)[0], y: r2t(ctl.lastFk.tcp)[1], z: r2t(ctl.lastFk.tcp)[2] };
  const q4 = quatRobotToThree(matToQuat(ctl.lastFk.joints[4].mat));
  const eeQuatThree = new THREE.Quaternion(q4[1], q4[2], q4[3], q4[0]);
  const graspEvent = physics.updateGrasp(eePosThree, eeQuatThree, ctl.closeCmd, state.assist, null);
  if (graspEvent) bus.publishEvent({ ...graspEvent, ep: state.ep, step: state.step });

  physics.step();

  // scenario + stall (per-step capture for the learning loop)
  const prog = scenario.update(dt, { ee: ctl.lastFk.tcp, close: ctl.closeCmd });
  const stall = stallDet.update({
    progressDist: prog.dist_to_goal,
    eePos: ctl.lastFk.tcp,
    eeTarget: ctl.ikTarget,
  });
  if (stall.stalled && !state.stallAnnounced) {
    state.stallAnnounced = true;
    bus.publishEvent({ kind: "stall", ep: state.ep, step: state.step, ...stall });
  }
  if (!stall.stalled) state.stallAnnounced = false;
  state.lastStall = stall;

  // recorder row (throttled to ~30 Hz to keep memory sane)
  if (recorder.enabled && recorder.current && state.step % 2 === 0) {
    recorder.row(state.step, state.t, buildObs(prog, stall), { q: ctl.servoDeg.map((d) => d * (Math.PI / 180)), grip: ctl.closeCmd });
  }

  // episode end?
  if (prog.done && !state.epEnded) {
    state.epEnded = true;
    endEpisode(prog.success ? "success" : "fail");
  }

  state.lastObs = buildObs(prog, stall);
}

function buildObs(prog, stall) {
  const objs = physics.objectsSnapshot();
  const q4 = ctl.lastFk.joints[4];
  const dq = state.lastServoDeg
    ? ctl.servoDeg.map((d, i) => (d - state.lastServoDeg[i]) / DT * (Math.PI / 180))
    : ctl.servoDeg.map(() => 0);
  state.lastServoDeg = ctl.servoDeg.slice();
  const primary = objs.find((o) => o.id === scenario.primaryId);
  return {
    ep: state.ep, step: state.step, t: state.t,
    scenario: scenario.name, control: ctl.mode,
    q: ctl.servoDeg.map((d) => d * (Math.PI / 180)),
    dq,
    gripper: ctl.closeCmd,
    ee: { pos: ctl.lastFk.tcp, quat: q4.quat },
    ik_target: ctl.ikTarget,
    objects: objs,
    goal: { pos: scenario.goal },
    progress: { dist_to_goal: Number.isFinite(prog.dist_to_goal) ? prog.dist_to_goal : null, reward: prog.reward, stage: prog.stage },
    done: prog.done, success: prog.success,
    stall,
    physics: physics.mode,
    last_cmd: ctl.lastCmd,
    primary_grasped: primary ? primary.grasped : false,
  };
}

// ---------- autotest headless mode ----------
function autotestTick() {
  // scripted control for a deterministic motion if nothing else is driving
  // (?meshcheck=1 owns the controller while probing — don't switch it to script)
  if (!meshcheckNote.startsWith("meshcheck")) {
    // note empty until the probe finishes; while probing, leave the mode alone
    if (!window.__meshcheckRunning && ctl.mode !== "script" && ctl.mode !== "mocap") ctl.setMode("script");
  }
  const write = () => {
    const b = bus;
    const line = `autotest bus: sent=${b.sent} (obs ${b.obsSent}) recv=${b.recv} (cmds ${b.recvCmds}) step=${state.step} physics=${physics.mode} render=${renderBroken ? "off" : "on"} meshes=${armVis.meshState.path}`;
    ui.setBusstat(line);
    $("status").textContent = `running step=${state.step}${meshcheckNote ? "\n" + meshcheckNote : ""}`;
    window.__armsmith = { step: state.step, busSent: b.sent, obsSent: b.obsSent, recvCmds: b.recvCmds, physics: physics.mode, meshes: armVis.meshState.path };
  };
  setTimeout(write, 800);
  // rewrite once meshes settle so the DOM carries the final meshes=stl|capsule verdict
  armVis.meshesReady.then(() => { ui.setMeshPath(armVis.meshState.path); write(); });
}

if (PUPPET) {
  import("./puppet.js").then((m) => m.bootPuppet())
    .catch((e) => showError("puppet", e && (e.stack || e.message) || String(e)));
} else {
  boot().catch((e) => { showError("boot", e && (e.stack || e.message) || String(e)); });
}

let booted = false;
