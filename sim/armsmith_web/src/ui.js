// ui.js — HUD wiring, keyboard jog (KeyBindings/ArmController scheme), mouse IK on the
// work-plane (MouseInteraction idea: LMB drag moves the target; wheel = depth, shift=fine;
// RMB drag orbits — cameras.js). All DOM ids referenced by index.html.

import { r2t, t2r, DEG, RAD, clamp } from "./frames.js";
import { ARM_CONFIG, REAL_SO101, WORKSPACE_BOX } from "./arm_config.js";

const JOINT_KEYS = [["t", "g"], ["y", "h"], ["u", "j"], ["i", "k"], ["o", "l"], ["p", ";"]];

export class UI {
  constructor(ctx) {
    this.ctx = ctx; // {ctl, cameras, canvas, bus, scenario, onMode, onScenario, onReset, onHome, onRecord, onExportEp, onExportAll, onAssist, onPhysics, onObsHz}
    this.mouseFollow = true;
    this.keys = new Set();
    this.drag = null;          // {kind:'orbit'|'ik', x, y}
    this.buildSliders();
    this.buildSpec();
    this.wireDom();
    this.wireKeyboard();
    this.wireMouse();
  }

  // ---- SPEC panel: the REAL STS3215/SO-101 facts driving the sim ----------------
  // Values come from ARM_CONFIG / REAL_SO101 / WORKSPACE_BOX (parsed from
  // so101_new_calib.xml, verified 2026-11-24) — no hard-coded spec strings here.
  buildSpec() {
    const host = document.getElementById("hud");
    if (!host) return;
    const wrap = document.createElement("div");
    wrap.id = "specPanel";
    const head = document.createElement("h3");
    head.style.cssText = "cursor:pointer;user-select:none";
    const title = document.createElement("span");
    title.textContent = "spec — real SO-101";
    const caret = document.createElement("span");
    caret.id = "specCaret";
    caret.textContent = " ▸";
    head.append(title, caret);
    head.addEventListener("click", () => this.setSpecOpen(wrap.style.display === "none"));
    const body = document.createElement("div");
    body.id = "specBody";
    body.style.display = "none";
    wrap.append(head, body);
    host.appendChild(wrap);

    const row = (k, v) => {
      const d = document.createElement("div");
      d.style.cssText = "margin:1px 0;color:#7d95aa";
      const b = document.createElement("b");
      b.style.color = "#cfe3f5"; b.textContent = v;
      d.append(`${k}: `, b);
      return d;
    };
    const R = REAL_SO101;
    body.appendChild(row("servo", `${R.servoModel} · ${R.ticksPerRev} ticks/rev (${R.degPerTick.toFixed(3)}°/tick) · ${R.servoNoLoadSpeedDegPerSec}°/s`));
    body.appendChild(row("torque cap", `${R.actuatorForceRangeNm} N·m (MJCF actuator forcerange)`));
    body.appendChild(row("PD gains", `kp ${R.actuatorKp} · kv ${R.actuatorKv} (MJCF position actuator)`));
    body.appendChild(row("joint friction", `damping ${R.jointDamping} · armature ${R.jointArmature} · frictionloss ${R.jointFrictionLoss}`));
    for (const j of ARM_CONFIG.joints) {
      body.appendChild(row(j.name,
        `${(j.min * RAD).toFixed(1)}°…${(j.max * RAD).toFixed(1)}° · ${(j.massKg * 1000).toFixed(0)} g`));
    }
    body.appendChild(row("total mass", `${(R.totalMassKg * 1000).toFixed(0)} g (all links, MJCF)`));
    body.appendChild(row("jaw travel", `${(REAL_SO101.jawRangeRad[0] * RAD).toFixed(0)}° closed … ${(REAL_SO101.jawRangeRad[1] * RAD).toFixed(0)}° open`));
    body.appendChild(row("workspace", `x ${WORKSPACE_BOX.x[0]}–${WORKSPACE_BOX.x[1]} · y ±${Math.abs(WORKSPACE_BOX.y[1])} · z ${WORKSPACE_BOX.z[0]}–${WORKSPACE_BOX.z[1]} m`));
    const meshRow = row("meshes", "loading…");
    meshRow.id = "specMeshRow";
    body.appendChild(meshRow);
    body.appendChild(row("mesh/licence", R.meshSource));
    this.setSpecOpen(false);
  }

  setSpecOpen(open) {
    const body = document.getElementById("specBody");
    const caret = document.getElementById("specCaret");
    if (!body) return;
    body.style.display = open ? "block" : "none";
    if (caret) caret.textContent = open ? " ▾" : " ▸";
  }

  // meshes=stl|capsule — updated once STL fetches settle (main.js)
  setMeshPath(path) {
    const el = document.getElementById("specMeshRow");
    if (!el) return;
    const b = el.querySelector("b");
    if (b) b.textContent = path;
  }

  buildSliders() {
    const host = document.getElementById("jSliders");
    const names = ["pan", "lift", "elbow", "w_flex", "w_roll"];
    this.jVals = [];
    names.forEach((nm, i) => {
      const row = document.createElement("div");
      row.className = "jrow";
      const lab = document.createElement("span");
      lab.className = "jlab";
      lab.textContent = `${JOINT_KEYS[i] ? JOINT_KEYS[i][0].toUpperCase() + "/" + JOINT_KEYS[i][1].toUpperCase() : ""} ${nm}`;
      const slider = document.createElement("input");
      slider.type = "range"; slider.min = -180; slider.max = 180; slider.step = 0.5; slider.value = 0;
      slider.dataset.joint = i;
      slider.addEventListener("input", () => {
        this.ctx.ctl.setMode("joint");
        document.getElementById("modeSel").value = "joint";
        this.ctx.ctl.nudgeJoint(i, 0); // ensure mode
        this.ctx.ctl.targets[i] = slider.value * DEG;
      });
      const val = document.createElement("span");
      val.className = "jval"; val.textContent = "0";
      row.append(lab, slider, val);
      host.appendChild(row);
      this.jVals.push({ slider, val });
    });
  }

  wireDom() {
    const $ = (id) => document.getElementById(id);
    const ctx = this.ctx;
    $("modeSel").addEventListener("change", (e) => { ctx.ctl.setMode(e.target.value); this.setMocapVisible(e.target.value === "mocap"); });
    $("scenSel").addEventListener("change", (e) => ctx.onScenario(e.target.value));
    $("homeBtn").addEventListener("click", () => ctx.onHome());
    $("resetBtn").addEventListener("click", () => ctx.onReset());
    $("gripBtn").addEventListener("click", () => ctx.onGripToggle());
    $("recordBtn").addEventListener("click", () => ctx.onRecord());
    $("expEpBtn").addEventListener("click", () => ctx.onExportEp());
    $("expAllBtn").addEventListener("click", () => ctx.onExportAll());
    $("assistChk").addEventListener("change", (e) => ctx.onAssist(e.target.checked));
    $("physChk").addEventListener("change", (e) => ctx.onPhysics(e.target.checked ? "dynamic" : "kinematic"));
    $("gripSlider").addEventListener("input", (e) => { ctx.ctl.closeCmd = Number(e.target.value); });
    // mocap calibration sliders (vision.hands -> ctl.calib)
    const mc = (id, fn, disp) => {
      const el = $(id), lab = $(disp);
      el.addEventListener("input", () => { fn(Number(el.value)); lab.textContent = Number(el.value).toFixed(2); });
    };
    mc("mcScale", (v) => ctx.ctl.calib.scale = v, "mcScaleV");
    mc("mcOx", (v) => ctx.ctl.calib.off[0] = v, "mcOxV");
    mc("mcOy", (v) => ctx.ctl.calib.off[1] = v, "mcOyV");
    mc("mcOz", (v) => ctx.ctl.calib.off[2] = v, "mcOzV");
    document.querySelectorAll(".camBtn").forEach((b) =>
      b.addEventListener("click", () => {
        document.querySelectorAll(".camBtn").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        ctx.cameras.select(b.dataset.cam);
      }));
  }

  setMocapVisible(on) { document.getElementById("mocapPanel").style.display = on ? "block" : "none"; }

  wireKeyboard() {
    const ctx = this.ctx;
    window.addEventListener("keydown", (e) => {
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "SELECT")) return;
      const k = e.key.toLowerCase();
      if (["tab", " ", ",", ".", "[", "]", "z", "x", "m", "g"].includes(k) || JOINT_KEYS.flat().includes(k)) e.preventDefault();
      if (this.keys.has(k)) return;
      this.keys.add(k);
      if (k === "tab") {
        const m = ctx.ctl.mode === "ik" ? "joint" : "ik";
        ctx.ctl.setMode(m);
        document.getElementById("modeSel").value = m;
      } else if (k === "g" || k === " ") ctx.onGripToggle();
      else if (k === "z") ctx.onHome();
      else if (k === "x") ctx.onReset();
      else if (k === "m") this.mouseFollow = !this.mouseFollow;
      else if (k === "n") ctx.ctl.nudgeJoint(4, 5 * DEG);
      else if (k === "b") ctx.ctl.nudgeJoint(4, -5 * DEG);
    });
    window.addEventListener("keyup", (e) => this.keys.delete(e.key.toLowerCase()));
    window.addEventListener("blur", () => this.keys.clear());
  }

  // held-key continuous motion (called each frame with dt)
  updateKeyboard(dt) {
    const ctx = this.ctx, ctl = ctx.ctl, keys = this.keys;
    // per-joint jog (T/G Y/H U/J I/K O/L P/;) — nudge targets on top of any mode
    JOINT_KEYS.forEach(([up, dn], i) => {
      const d = (keys.has(up) ? 1 : 0) - (keys.has(dn) ? 1 : 0);
      if (d !== 0) ctl.nudgeJoint(i, d * 60 * DEG * dt);
    });
    // gripper open/close hold (Unity: , .)
    if (keys.has(".")) ctl.closeCmd = clamp(ctl.closeCmd + 2 * dt, 0, 1);
    if (keys.has(",")) ctl.closeCmd = clamp(ctl.closeCmd - 2 * dt, 0, 1);
    // depth ([ ] / scroll handled here)
    let dz = 0;
    if (keys.has("]")) dz += 0.25 * dt;
    if (keys.has("[")) dz -= 0.25 * dt;
    if (dz !== 0) { ctl.workPlaneZ = clamp(ctl.workPlaneZ + dz, 0.02, 0.45); ctl.setMouseTarget([ctl.ikTarget[0], ctl.ikTarget[1], ctl.workPlaneZ]); }
    // fly the IK target camera-relative (WASD + Q/E — ArmController.cs HandleIKInput)
    if (ctl.mode === "ik" || ctl.mode === "mocap") {
      const cam = ctx.cameras.free;
      const fwd = new (cam.position.constructor)();
      cam.getWorldDirection(fwd); fwd.y = 0;
      if (fwd.lengthSq() < 1e-6) fwd.set(1, 0, 0);
      fwd.normalize();
      const right = new (cam.position.constructor)(fwd.z, 0, -fwd.x);
      const d = new (cam.position.constructor)();
      if (keys.has("w")) d.add(fwd);
      if (keys.has("s")) d.sub(fwd);
      if (keys.has("d")) d.add(right);
      if (keys.has("a")) d.sub(right);
      if (keys.has("e") || keys.has("r")) d.y += 1;
      if (keys.has("q") || keys.has("f")) d.y -= 1;
      if (d.lengthSq() > 0) {
        d.normalize().multiplyScalar(0.35 * dt);
        const p = [ctl.ikTarget[0] + d.x, ctl.ikTarget[1] + d.y, ctl.ikTarget[2] + d.z];
        ctl.workPlaneZ = p[2];
        ctl.setMouseTarget(p);
      }
    }
  }

  wireMouse() {
    const ctx = this.ctx, canvas = ctx.canvas;
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      this.drag = { kind: e.button === 2 ? "orbit" : e.button === 1 ? "pan" : "ik", x: e.clientX, y: e.clientY };
    });
    canvas.addEventListener("pointerup", (e) => { this.drag = null; try { canvas.releasePointerCapture(e.pointerId); } catch { /* ignore */ } });
    canvas.addEventListener("pointermove", (e) => {
      if (!this.drag) return;
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
      this.drag.x = e.clientX; this.drag.y = e.clientY;
      if (this.drag.kind === "orbit") ctx.cameras.orbitBy(dx, dy);
      else if (this.drag.kind === "pan") ctx.cameras.panBy(dx, dy);
      else if (this.drag.kind === "ik" && this.mouseFollow) this.mousePlaneTarget(e);
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (e.buttons & 2) { ctx.cameras.zoomBy(e.deltaY); return; }   // RMB+wheel = zoom
      // wheel = depth (scrollDepth, shift = fine — ArmController.cs)
      const step = e.shiftKey ? 0.12 : 0.45;
      const ctl = ctx.ctl;
      ctl.workPlaneZ = clamp(ctl.workPlaneZ - Math.sign(e.deltaY) * step * 0.1, 0.02, 0.45);
      ctl.setMouseTarget([ctl.ikTarget[0], ctl.ikTarget[1], ctl.workPlaneZ]);
    }, { passive: false });
  }

  // Port of ArmController.cs HandleIKInput mouse-follow: project the cursor onto the
  // work-plane (horizontal from above; camera-facing vertical plane from the side).
  mousePlaneTarget(e) {
    const ctx = this.ctx, ctl = ctx.ctl;
    const cam = ctx.cameras.free;
    const rect = canvas_rect(ctx.canvas);
    const ndc = new ((cam.position.constructor))(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = raycaster(ndc, cam);
    const fwd = new (cam.position.constructor)();
    cam.getWorldDirection(fwd);
    const down = new (cam.position.constructor)(0, -1, 0);
    const pitch = Math.acos(clamp(fwd.dot(down), -1, 1)); // 0 = top-down
    const sideView = pitch > 55 * DEG;
    const planeN = sideView
      ? new (cam.position.constructor)(fwd.x, 0, fwd.z).normalize()
      : new (cam.position.constructor)(0, 1, 0);
    const planeP = sideView
      ? new (cam.position.constructor)(...r2t(ctl.ikTarget))
      : new (cam.position.constructor)(0, ctl.workPlaneZ, 0);
    const plane = new THREE_PLANE(planeN, planeP);
    const pOut = new (cam.position.constructor)();
    if (ray.intersectPlane(plane, pOut)) {
      const rp = t2r([pOut.x, pOut.y, pOut.z]);
      if (sideView) { ctl.workPlaneZ = clamp(rp[2], 0.02, 0.45); ctl.setMouseTarget(rp); }
      else ctl.setMouseTarget([rp[0], rp[1], ctl.workPlaneZ]);
    }
  }

  // refresh sliders/HUD from sim state
  refresh(anglesRad, close, stall, status) {
    for (let i = 0; i < 5; i++) {
      const deg = anglesRad[i] * RAD;
      const j = this.jVals[i];
      if (document.activeElement !== j.slider) j.slider.value = Math.max(-180, Math.min(180, deg));
      j.val.textContent = deg.toFixed(1);
    }
    const gs = document.getElementById("gripSlider");
    if (document.activeElement !== gs) gs.value = close;
    document.getElementById("gripVal").textContent = Number(close).toFixed(2);
    document.getElementById("stallbar").style.width = `${Math.round(stall.score * 100)}%`;
    document.getElementById("stallbar").style.background = stall.stalled ? "#ff5d5d" : stall.score > 0.6 ? "#ffc14d" : "#4be07a";
    document.getElementById("stalltxt").textContent =
      `stall: ${stall.stalled ? "STALLED" : "ok"} score=${stall.score.toFixed(2)} ${stall.reasons.join(",")}`;
    document.getElementById("epCount").textContent = status.ep;
  }

  setCounts(ok, fail) {
    document.getElementById("okCount").textContent = ok;
    document.getElementById("failCount").textContent = fail;
  }
  setStatus(text) { document.getElementById("status").textContent = text; }
  setBusstat(text) { document.getElementById("busstat").textContent = text; }
  setRec(on) { const el = document.getElementById("recdot"); el.textContent = on ? "● REC" : "● idle"; el.className = on ? "on" : ""; }
  setButtons(recording, episodes) {
    document.getElementById("recordBtn").classList.toggle("on", recording);
    document.getElementById("recordBtn").textContent = recording ? "recording…" : "record";
    document.getElementById("expEpBtn").disabled = episodes.length === 0;
    document.getElementById("expAllBtn").disabled = episodes.length === 0;
  }
  setMocapHands(text) { document.getElementById("mcState").textContent = text; }
  setPhysics(mode) { document.getElementById("physChk").checked = mode === "dynamic"; }
}

// small three shims kept local so ui.js has a single import of three
import * as THREE from "three";
function canvas_rect(c) { return c.getBoundingClientRect(); }
function raycaster(ndc, cam) {
  const rc = new THREE.Raycaster();
  rc.setFromCamera({ x: ndc.x, y: ndc.y }, cam);
  return rc.ray;
}
function THREE_PLANE(n, p) { return new THREE.Plane(n.clone().normalize(), -n.clone().normalize().dot(p)); }
