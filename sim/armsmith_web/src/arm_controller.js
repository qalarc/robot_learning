// arm_controller.js — port of ArmController.cs ideas: modes ik|joint|script|mocap|off.
// IK mode: FABRIK solves the virtual chain (fabrik.js), solved bone directions become
// per-joint targets (robot.js anglesFromPoints). Every command passes through the
// ServoModel chain (rate limit + tick quantise) before it drives the arm — digital twin.
// Includes the SAFETY ENVELOPE from ArmController.cs SolveIK: goals are clamped into the
// reachable shell, above the worktop, and inside the workspace box (AGENTS.md rule 1).

import { ARM_CONFIG, totalReach } from "./arm_config.js";
import { fabrikSolve } from "./fabrik.js";
import { fk, anglesFromPlanarPoints } from "./robot.js";
import { makeServos } from "./servo.js";
import { clamp, DEG, RAD } from "./frames.js";

const HOME = ARM_CONFIG.home;
// workspace box (robot frame) — mirrors control/robot_ops.schema.json
const BOX = { x: [0.03, 0.32], y: [-0.20, 0.20], z: [0.02, 0.28] };

// scripted demo waypoints (autotest / no-operator motion): [x, y, z, close]
const SCRIPT_WAYPOINTS = [
  [0.20, 0.00, 0.12, 0.0], [0.20, 0.00, 0.06, 0.0], [0.20, 0.00, 0.055, 0.9],
  [0.20, 0.00, 0.16, 0.9], [0.24, 0.12, 0.12, 0.9], [0.24, 0.12, 0.07, 0.9],
  [0.24, 0.12, 0.065, 0.0], [0.22, 0.06, 0.14, 0.0],
];

// in-plane chain for a set of cumulative pitches (seeds for the multi-seed FABRIK)
function seedChain(cum) {
  const L = ARM_CONFIG.fabrikLengths;
  const pts = [[0, 0, 0]];
  let p = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    p = [p[0] + Math.sin(cum[i]) * L[i], 0, p[2] + Math.cos(cum[i]) * L[i]];
    pts.push(p.slice());
  }
  return pts;
}

export class ArmController {
  constructor(cfg = ARM_CONFIG) {
    this.cfg = cfg;
    this.mode = "ik";
    this.targets = HOME.slice();         // commanded joint angles (rad)
    this.servoState = HOME.slice();      // what the servos actually hold (deg stored in servoModel path)
    this.servos = makeServos(cfg);
    this.servoDeg = HOME.map((a) => a * RAD);
    this.ikTarget = null;                // robot frame [x,y,z]
    this.workPlaneZ = 0.05;              // "depth" of the mouse work-plane
    this.closeCmd = 0;                   // 0 open .. 1 closed (commanded)
    this.lastCmd = null;
    this.playback = null;
    this.wpIndex = 0;
    this.holdUntil = 0;                  // mocap hold-last-target window
    this.calib = { scale: 1, off: [0, 0, 0] };
    this.lastFk = fk(HOME, cfg);
    this.ikTarget = this.lastFk.tcp.slice();
    this.ikResidual = 0;
    this.ikErrAccum = 0; this.ikErrN = 0;
  }

  note(cmd, args) { this.lastCmd = { cmd, args, t: Date.now() / 1000 }; }

  setMode(m) {
    if (!["ik", "joint", "script", "mocap", "off"].includes(m)) return false;
    this.mode = m;
    return true;
  }

  // ---------- command handlers (called by bus.js / UI / keyboard) ----------
  cmdJoint(q) {
    for (let i = 0; i < 5; i++) this.targets[i] = clamp(Number(q[i] ?? this.targets[i]), this.cfg.joints[i].min, this.cfg.joints[i].max);
    this.note("joint", { q });
  }

  cmdEe(pos, opts = {}) {
    let p = pos.slice();
    if (opts.mode === "relative") {
      const cur = this.lastFk.tcp;
      p = [cur[0] + p[0], cur[1] + p[1], cur[2] + p[2]];
    }
    this.ikTarget = this.envelope(p);
    if (Number.isFinite(opts.yaw)) this.targets[0] = clamp(opts.yaw, this.cfg.joints[0].min, this.cfg.joints[0].max);
    if (Number.isFinite(opts.pitch)) this.targets[4] = clamp(opts.pitch, this.cfg.joints[4].min, this.cfg.joints[4].max);
    if (Number.isFinite(opts.gripper)) this.closeCmd = clamp(opts.gripper, 0, 1);
    this.note("ee", { pos, ...opts });
  }

  cmdGripper(open) { this.closeCmd = clamp(1 - open, 0, 1); this.note("gripper", { open }); }

  cmdPlay(actions, fps = 30) {
    this.playback = { actions, fps, idx: 0, acc: 0 };
    this.setMode("joint");
    this.note("play", { n: actions.length, fps });
  }

  nudgeJoint(i, delta) {
    this.targets[i] = clamp(this.targets[i] + delta, this.cfg.joints[i].min, this.cfg.joints[i].max);
  }

  // mouse work-plane target (robot frame); scroll-depth handled by ui.js via workPlaneZ
  setMouseTarget(p) { this.ikTarget = this.envelope(p); }

  // clamp into the safety envelope (workspace box + reach sphere + above worktop)
  envelope(p) {
    let [x, y, z] = p;
    x = clamp(x, BOX.x[0], BOX.x[1]);
    y = clamp(y, BOX.y[0], BOX.y[1]);
    z = clamp(z, BOX.z[0], BOX.z[1]);
    const base = [this.cfg.panPivot[0], 0, this.cfg.panPivot[2]];
    const reach = totalReach(this.cfg) * 0.98;
    const dx = x - base[0], dy = y - base[1], dz = z - base[2];
    const d = Math.hypot(dx, dy, dz);
    if (d > reach) { x = base[0] + (dx / d) * reach; y = base[1] + (dy / d) * reach; z = base[2] + (dz / d) * reach; }
    return [x, y, z];
  }

  home() {
    this.targets = HOME.slice();
    this.ikTarget = fk(HOME, this.cfg).tcp.slice();
    this.note("home", {});
  }

  // mocap: vision.hands data (bus). ee_target in robot base frame; 1-pinch gripper.
  updateMocap(hands, tNow) {
    if (!hands || !hands.length) {
      if (tNow > this.holdUntil) return false; // no hand for > 0.6 s: hold last target
      return true;
    }
    const h = hands[0];
    this.holdUntil = tNow + 0.6;
    let t = h.ee_target || null;
    if (!t) return true;
    const c = this.calib;
    t = [c.scale * t[0] + c.off[0], c.scale * t[1] + c.off[1], c.scale * t[2] + c.off[2]];
    this.ikTarget = this.envelope(t);
    if (Number.isFinite(h.pinch)) this.closeCmd = clamp(h.pinch, 0, 1);
    return true;
  }

  // ---------- fixed-step control tick ----------
  tick(dt, tNow) {
    // script mode: cycle demo waypoints through the IK target
    if (this.mode === "script") {
      const wp = SCRIPT_WAYPOINTS[this.wpIndex];
      this.ikTarget = wp.slice(0, 3);
      this.closeCmd = wp[3];
      if (Math.hypot(this.lastFk.tcp[0] - wp[0], this.lastFk.tcp[1] - wp[1], this.lastFk.tcp[2] - wp[2]) < 0.018)
        this.wpIndex = (this.wpIndex + 1) % SCRIPT_WAYPOINTS.length;
    }

    if (this.mode === "ik" || this.mode === "script" || this.mode === "mocap") this.solveIK();
    if (this.playback) {
      this.playback.acc += dt;
      const frame = 1 / this.playback.fps;
      while (this.playback.acc >= frame && this.playback.idx < this.playback.actions.length) {
        this.playback.acc -= frame;
        const a = this.playback.actions[this.playback.idx++];
        this.cmdJointQuiet(a);
      }
      if (this.playback.idx >= this.playback.actions.length) this.playback = null;
    }
    if (this.mode === "off") { /* hold: no target updates */ }

    // servo chain: commanded target -> rate limit -> tick quantise -> held state
    for (let i = 0; i < 5; i++) {
      const targetDeg = this.targets[i] * RAD;
      this.servoDeg[i] = this.servos[i].command(this.servoDeg[i], targetDeg, dt);
    }
    this.lastFk = fk(this.servoDeg.map((d) => d * DEG), this.cfg);
    this.ikResidual = Math.hypot(
      this.lastFk.tcp[0] - this.ikTarget[0],
      this.lastFk.tcp[1] - this.ikTarget[1],
      this.lastFk.tcp[2] - this.ikTarget[2]);
    this.ikErrAccum += this.ikResidual; this.ikErrN++;
    return { angles: this.lastFk ? this.servoDeg.map((d) => d * DEG) : this.targets, close: this.closeCmd };
  }

  cmdJointQuiet(a) {
    for (let i = 0; i < 5; i++) this.targets[i] = clamp(Number(a[i] ?? this.targets[i]), this.cfg.joints[i].min, this.cfg.joints[i].max);
    if (a.length > 5) this.closeCmd = clamp(Number(a[5]), 0, 1);
  }

  // FABRIK over the 4 CONTROLLABLE bones (lift->elbow->wrist->palm->TCP), solved IN THE
  // YAW PLANE (u = forward along yawDir, v = up): the SO-101 is a planar pitch chain after
  // the pan joint, so constraining the solver to that plane makes the bone-direction ->
  // joint-angle mapping exact instead of approximate (the Unity port's ~7 cm residual came
  // from exactly this out-of-plane bulge — see KINEMATICS_NOTES/HANDOVER; re-tuned here).
  solveIK() {
    const cfg = this.cfg;
    const goal = this.envelope(this.ikTarget);
    const base = cfg.panPivot;

    // 1) yaw: point the plane at the goal
    const yaw = Math.atan2(goal[1] - base[1], goal[0] - base[0]);
    this.targets[0] = clamp(yaw, cfg.joints[0].min, cfg.joints[0].max);

    // 2) lift pivot for that yaw (fixed offset in the pan frame) + plane axes
    const cy = Math.cos(this.targets[0]), sy = Math.sin(this.targets[0]);
    const P1 = [
      base[0] + cy * cfg.liftOffset[0] - sy * cfg.liftOffset[1],
      base[1] + sy * cfg.liftOffset[0] + cy * cfg.liftOffset[1],
      base[2] + cfg.liftOffset[2],
    ];
    const udir = [cy, sy, 0];
    const toPlane = (p) => [
      (p[0] - P1[0]) * udir[0] + (p[1] - P1[1]) * udir[1],
      0,
      p[2] - P1[2],
    ];

    // 3) goal in plane coords (seed chains start from scratch each solve)
    const g = toPlane(goal);
    const reach = cfg.fabrikLengths.reduce((a, b) => a + b, 0) * 0.999;
    const gd = Math.hypot(g[0], g[2]);
    if (gd > reach) {
      g[0] = (g[0] / gd) * reach;
      g[2] = (g[2] / gd) * reach;
    }
    if (g[2] < 0.02 - P1[2]) g[2] = 0.02 - P1[2]; // never command below the worktop

    // 4) FABRIK from MULTIPLE SEEDS (ArmController.cs S7f anti-elbow-up restart): FABRIK
    // doesn't know joint limits, so a single seed can settle in a branch whose extracted
    // angles clamp badly. Try 3 seeds, FK-verify each against the true 3D goal, keep best.
    const seeds = [
      [[0, 0, 0], [0, 0, cfg.fabrikLengths[0]],
       [0, 0, cfg.fabrikLengths[0] + cfg.fabrikLengths[1]],
       [0, 0, cfg.fabrikLengths[0] + cfg.fabrikLengths[1] + cfg.fabrikLengths[2]]], // straight up
      seedChain([40 * DEG, 60 * DEG, 60 * DEG]),   // reach forward-down
      seedChain([-30 * DEG, 90 * DEG, 60 * DEG]),  // backward-shoulder branch
    ];
    let bestErr = Infinity, bestAngles = null;
    for (const seedPts of seeds) {
      const trial = seedPts.map((p) => p.slice());
      fabrikSolve(trial, cfg.fabrikLengths, g, 5, 0.001);
      const cand = anglesFromPlanarPoints(trial, cfg, this.targets[0]);
      const verify = fk(cand, cfg);
      const err = Math.hypot(verify.tcp[0] - goal[0], verify.tcp[1] - goal[1], verify.tcp[2] - goal[2]);
      if (err < bestErr) { bestErr = err; bestAngles = cand; }
    }
    const solved = bestAngles;
    // keep commanded wrist roll (position-only IK can't observe it)
    solved[4] = this.targets[4];
    // blend for smooth motion (ArmController.cs blends, never snaps)
    for (let i = 0; i < 5; i++) this.targets[i] = this.targets[i] + (solved[i] - this.targets[i]) * 0.4;
    this.ikTarget = this.envelope(goal);
  }

  meanIkError() { return this.ikErrN ? this.ikErrAccum / this.ikErrN : 0; }
}
