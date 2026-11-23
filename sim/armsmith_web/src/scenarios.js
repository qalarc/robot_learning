// scenarios.js — reach / pick_place / push_to_zone / stack (port of ScenarioManager.cs +
// TaskManager.cs ideas: seeded placement, dense reward shaping, stage labels, OOB watchdog).

import * as THREE from "three";
import { r2t } from "./frames.js";
import { makeRng } from "./arm_config.js";

export const SCENARIOS = ["reach", "pick_place", "push_to_zone", "stack"];

const OOB = { minX: -0.55, maxX: 0.55, minFwd: -0.15, maxFwd: 0.75, minZ: -0.15 };

function discMarker(scene, radius, color, opacity = 0.55) {
  const m = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 32),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2; // three: lying on the ground plane
  scene.add(m);
  return m;
}

export class Scenario {
  constructor(name, physics, scene) {
    this.name = name;
    this.physics = physics;
    this.scene = scene;
    this.markers = [];
    this.timeLimit = 30;
    this.epIndex = 0;
    this.reset(this.name, Math.floor(Math.random() * 1e9));
  }

  disposeMarkers() {
    for (const m of this.markers) this.scene.remove(m);
    this.markers = [];
  }

  reset(name, seed) {
    if (name) this.name = name;
    this.seed = seed;
    this.rng = makeRng(seed);
    this.elapsed = 0;
    this.done = false;
    this.success = false;
    this.stage = "reach";
    this.reward = 0;
    this.lastEvent = null;
    this.primaryId = null;
    this.disposeMarkers();

    // clear previous episode's objects
    for (const id of [...this.physics.objects.keys()]) this.physics.removeObject(id);

    const r = (lo, hi) => lo + (hi - lo) * this.rng();
    const ang = (lo, hi) => this.rng() * (hi - lo) + lo;

    if (this.name === "reach") {
      // pink target point, no grasp (ScenarioManager.ReachTouch: < 4 cm)
      const a = ang(-0.9, 0.9), rad = r(0.15, 0.30);
      this.goal = [Math.cos(a) * rad, Math.sin(a) * rad, r(0.03, 0.16)];
      const m = discMarker(this.scene, 0.02, 0xff5db0);
      m.position.set(...r2t(this.goal));
      this.markers.push(m);
      this.distKey = "ee";
    } else if (this.name === "pick_place") {
      const a = ang(-0.5, 0.5), rad = r(0.18, 0.26);
      const cube = [Math.cos(a) * rad, Math.sin(a) * rad, 0.0225];
      const tb = a + Math.PI + ang(-0.7, 0.7);
      const trad = r(0.15, 0.28);
      this.pad = [Math.cos(tb) * trad, Math.sin(tb) * trad, 0.002];
      this.physics.addObject("cube", cube, { size: 0.045, color: 0xe6c84a });
      this.primaryId = "cube";
      this.goal = this.pad;
      const m = discMarker(this.scene, 0.06, 0x3380ee);
      m.position.set(...r2t(this.pad));
      this.markers.push(m);
      this.distKey = "cube";
    } else if (this.name === "push_to_zone") {
      const a = ang(-0.4, 0.4);
      const cube = [Math.cos(a) * r(0.14, 0.20), Math.sin(a) * r(0.06, 0.14), 0.0225];
      this.zone = [r(0.22, 0.32), Math.sin(a) * 0.12 + ang(-0.05, 0.05), 0.002];
      this.physics.addObject("cube", cube, { size: 0.05, color: 0x63c7ff, density: 60 });
      this.primaryId = "cube";
      this.goal = this.zone;
      const m = discMarker(this.scene, 0.07, 0x3ad06a);
      m.position.set(...r2t(this.zone));
      this.markers.push(m);
      this.distKey = "cube";
    } else if (this.name === "stack") {
      // purple base cube (bigger) + yellow cube to stack on it (ScenarioManager.StackTwo)
      const a = ang(-0.5, 0.5), rad = r(0.18, 0.26);
      const b = [Math.cos(a) * rad, Math.sin(a) * rad, 0.04];
      const a2 = a + ang(0.5, 1.1);
      const y = [Math.cos(a2) * r(0.16, 0.24), Math.sin(a2) * r(0.10, 0.22), 0.0225];
      this.physics.addObject("cubeB", b, { size: 0.06, color: 0xcc66d8 });
      this.physics.addObject("cubeA", y, { size: 0.045, color: 0xf2d940 });
      this.primaryId = "cubeA";
      this.basePos = b;
      this.goal = b;
      const m = new THREE.Mesh(new THREE.RingGeometry(0.05, 0.06, 32),
        new THREE.MeshBasicMaterial({ color: 0xcc66d8, transparent: true, opacity: 0.5, side: THREE.DoubleSide }));
      m.rotation.x = -Math.PI / 2;
      m.position.set(...r2t([b[0], b[1], 0.061]));
      this.scene.add(m); this.markers.push(m);
      this.distKey = "cubeA";
    }
    this.epIndex++;
    this.lastEvent = { kind: "episode_start", ep: this.epIndex, scenario: this.name, seed };
  }

  // oo = observation pieces from main: {ee:[x,y,z], close, vel}
  update(dt, oo) {
    if (this.done) return this.status(0);
    this.elapsed += dt;
    const objs = this.physics.objectsSnapshot();
    const primary = objs.find((o) => o.id === this.primaryId);
    const grasped = primary ? primary.grasped : false;
    let distGoal = Infinity, reward = 0, success = false;
    const ee = oo.ee;

    if (this.name === "reach") {
      distGoal = dist(ee, this.goal);
      reward = -distGoal;
      success = distGoal < 0.04;
      this.stage = success ? "done" : "reach";
    } else if (this.name === "pick_place" || this.name === "stack") {
      const cube = primary.pos;
      const gripToCube = dist(ee, cube);
      const target = this.name === "stack" ? this.basePos : this.pad;
      const flat = Math.hypot(cube[0] - target[0], cube[1] - target[1]);
      // TaskManager.cs dense shaping
      reward = -gripToCube * 0.5;
      if (grasped) reward += 0.5 - flat;
      distGoal = grasped ? flat : gripToCube;
      if (this.stage === "reach" && grasped) this.stage = "grasp";
      else if (this.stage === "grasp" && cube[2] > 0.07) this.stage = "lift";
      else if (this.stage === "lift" && flat < 0.06) this.stage = "place";
      const stackTop = this.name === "stack" ? this.basePos[2] + 0.055 : 0.06;
      const onTarget = flat < 0.06 && cube[2] < stackTop;
      const atRest = objSpeed(this.physics, this.primaryId) < 0.03;
      success = onTarget && atRest && (!grasped || this.name === "stack");
      if (success) this.stage = "done";
    } else if (this.name === "push_to_zone") {
      const cube = primary.pos;
      distGoal = Math.hypot(cube[0] - this.zone[0], cube[1] - this.zone[1]);
      reward = -0.4 * dist(ee, cube) - 0.3 * distGoal;
      if (this.stage === "reach" && dist(ee, cube) < 0.09) this.stage = "push";
      success = distGoal < 0.06 && objSpeed(this.physics, this.primaryId) < 0.03;
      if (success) this.stage = "done";
    }

    // TaskManager.cs: sparse bonus + speed bonus; OOB penalty
    if (success) {
      reward += 10 + Math.max(0, this.timeLimit - this.elapsed) * 0.1;
      this.done = true;
    }
    if (primary && oob(primary.pos)) reward -= 5;
    if (this.elapsed > this.timeLimit) this.done = true;
    this.reward = reward;
    if (success && !this.success) this.success = true;

    const outcome = this.done ? (success ? "success" : "fail") : null;
    this.lastEvent = outcome
      ? { kind: "episode_end", ep: this.epIndex, scenario: this.name, outcome, steps: Math.round(this.elapsed * 60) }
      : null;
    return this.status(distGoal, reward);
  }

  status(distGoal = Infinity, reward = 0) {
    return {
      stage: this.stage, done: this.done, success: this.success,
      reward: reward || this.reward, dist_to_goal: Number.isFinite(distGoal) ? distGoal : (this.goal ? dist([0, 0, 0], this.goal) : 0),
      ep: this.epIndex, elapsed: this.elapsed, scenario: this.name,
    };
  }
}

function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }

function objSpeed(physics, id) {
  const rec = physics.objects.get(id);
  if (!rec) return 0;
  const v = rec.body.linvel();
  return Math.hypot(v.x, v.y, v.z);
}

function oob(p) {
  return p[0] < OOB.minX || p[0] > OOB.maxX || p[1] < OOB.minFwd || p[1] > OOB.maxFwd || p[2] < OOB.minZ;
}
