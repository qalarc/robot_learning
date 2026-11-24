// robot.js — procedural SO-101 6-DOF arm (port of ProceduralArm.cs ideas).
// Pure-math FK in the ROBOT frame (x fwd, y left, z up) + three.js visuals built from
// capsule/box primitives ("authentic silhouette, not exact STLs").
// Geometry data comes from arm_config.js which was derived from vendor/kinematics.json.

import * as THREE from "three";
import { ARM_CONFIG, totalReach } from "./arm_config.js";
import { r2t, quatRobotToThree, DEG, matToQuat } from "./frames.js";

// ---------- tiny mat3/vec3 (robot frame) ---------------------------------
const m3mul = (a, b) => {
  const r = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++)
    for (let k = 0; k < 3; k++) r[i][j] += a[i][k] * b[k][j];
  return r;
};
const Rz = (t) => [[Math.cos(t), -Math.sin(t), 0], [Math.sin(t), Math.cos(t), 0], [0, 0, 1]];
const Ry = (t) => [[Math.cos(t), 0, Math.sin(t)], [0, 1, 0], [-Math.sin(t), 0, Math.cos(t)]];
const m3v = (m, v) => [
  m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
  m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
  m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
];
const vadd = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const vscale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const vnorm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

// ---------- analytic forward kinematics (robot frame) ---------------------
// angles = [yaw, shoulder, elbow, wrist, roll] (rad), zero pose = arm straight up.
// Positive pitch = lean toward the yaw direction (see arm_config.js notes).
export function fk(angles, cfg = ARM_CONFIG) {
  const [yaw, s, e, w, roll] = angles;
  const f = [Math.cos(yaw), Math.sin(yaw), 0];          // yaw direction ("forward")
  const L = [-Math.sin(yaw), Math.cos(yaw), 0];         // left axis (pitch axis)
  const dir1 = [f[0] * Math.sin(s), f[1] * Math.sin(s), Math.cos(s)];
  const dir2 = [f[0] * Math.sin(s + e), f[1] * Math.sin(s + e), Math.cos(s + e)];
  const dir3 = [f[0] * Math.sin(s + e + w), f[1] * Math.sin(s + e + w), Math.cos(s + e + w)];

  const P0 = cfg.panPivot.slice();
  const P1 = vadd(P0, m3v(Rz(yaw), cfg.liftOffset));
  const P2 = vadd(P1, vscale(dir1, cfg.joints[1].linkLength));
  const P3 = vadd(P2, vscale(dir2, cfg.joints[2].linkLength));
  const P4 = vadd(P3, vscale(dir3, cfg.joints[3].linkLength));
  const P5 = vadd(P4, vscale(dir3, cfg.jawBaseToTCP));   // TCP (gripper_frame_link)

  const points = [P0, P1, P2, P3, P4, P5];
  const mPan = Rz(yaw);
  const mLift = m3mul(Rz(yaw), Ry(s));
  const mElbow = m3mul(Rz(yaw), Ry(s + e));
  const mWrist = m3mul(Rz(yaw), Ry(s + e + w));
  const mRoll = m3mul(mWrist, Rz(roll));
  const joints = [
    { name: cfg.joints[0].name, pos: P0, mat: mPan },
    { name: cfg.joints[1].name, pos: P1, mat: mLift },
    { name: cfg.joints[2].name, pos: P2, mat: mElbow },
    { name: cfg.joints[3].name, pos: P3, mat: mWrist },
    { name: cfg.joints[4].name, pos: P4, mat: mRoll },
  ].map((j) => ({ ...j, quat: matToQuat(j.mat) }));

  // left axis of the TOOL frame (jaw separation direction, world)
  const toolLeft = m3v(mRoll, [0, 1, 0]);
  const toolDir = dir3;
  return { points, dirs: [null, dir1, dir2, dir3], joints, tcp: P5, toolLeft, toolDir, f, L };
}

// ---------- IK-mapping helpers: solved bone directions -> joint targets ---
// (port of ArmController.cs "resulting bone directions converted to per-joint angle targets")
// Accepts the full chain (…, lift, elbow, wrist, palm) or the controllable chain
// (lift, elbow, wrist, TCP) — the LAST FOUR points are always the mapped bones.
export function anglesFromPoints(points, cfg = ARM_CONFIG) {
  const k = points.length;
  const A = points[k - 4], B = points[k - 3], C = points[k - 2], D = points[k - 1];
  const d1 = vnorm([B[0] - A[0], B[1] - A[1], B[2] - A[2]]);  // lift->elbow  (upper arm)
  const d2 = vnorm([C[0] - B[0], C[1] - B[1], C[2] - B[2]]);  // elbow->wrist (lower arm)
  const d3 = vnorm([D[0] - C[0], D[1] - C[1], D[2] - C[2]]);  // wrist->palm/TCP

  const yaw = Math.atan2(d1[1], d1[0]);
  const f = [Math.cos(yaw), Math.sin(yaw), 0];
  const L = [-Math.sin(yaw), Math.cos(yaw), 0];

  // pitch = angle of bone from vertical (+ = lean forward), accumulated
  const s = Math.atan2(d1[0] * f[0] + d1[1] * f[1], d1[2]);
  // relative pitch = signed angle between consecutive bones about L
  const rel = (a, b) => {
    const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const cx = a[1] * b[2] - a[2] * b[1], cy = a[2] * b[0] - a[0] * b[2], cz = a[0] * b[1] - a[1] * b[0];
    return Math.atan2(cx * L[0] + cy * L[1] + cz * L[2], dot);
  };
  const e = rel(d1, d2);
  const w = rel(d2, d3);
  const cl = (v, j) => Math.min(j.max, Math.max(j.min, v));
  return [
    cl(yaw, cfg.joints[0]),
    cl(s, cfg.joints[1]),
    cl(e, cfg.joints[2]),
    cl(w, cfg.joints[3]),
    0, // wrist roll is not observable from position-only IK; commanded separately
  ];
}

// Planar variant used by the IK solver: points are in the yaw plane (x = forward-u,
// y = 0, z = up-v), yaw is KNOWN (aimed at the goal), so pitches extract exactly —
// even when the upper arm leans backward past vertical (the elbow-down branch).
export function anglesFromPlanarPoints(points, cfg = ARM_CONFIG, yaw = 0) {
  const k = points.length;
  const A = points[k - 4], B = points[k - 3], C = points[k - 2], D = points[k - 1];
  const d1 = vnorm([B[0] - A[0], 0, B[2] - A[2]]);
  const d2 = vnorm([C[0] - B[0], 0, C[2] - B[2]]);
  const d3 = vnorm([D[0] - C[0], 0, D[2] - C[2]]);
  const s = Math.atan2(d1[0], d1[2]);                       // from vertical, + = forward
  const rel = (a, b) => Math.atan2(a[2] * b[0] - a[0] * b[2], a[0] * b[0] + a[2] * b[2]);
  const e = rel(d1, d2);
  const w = rel(d2, d3);
  const cl = (v, j) => Math.min(j.max, Math.max(j.min, v));
  return [
    cl(yaw, cfg.joints[0]),
    cl(s, cfg.joints[1]),
    cl(e, cfg.joints[2]),
    cl(w, cfg.joints[3]),
    0, // wrist roll is not observable from position-only IK; commanded separately
  ];
}

// ---------- visuals --------------------------------------------------------
// Two visual tiers:
//   1. REAL MESHES (default when assets load): the official SO-101 STLs from
//      TheRobotStudio/SO-ARM100 (assets/so101/, Apache-2.0), placed per joint with
//      local offsets/rotations derived from the calibrated official MJCF
//      (so101_new_calib.xml) — placements verified against the MJCF chain to
//      <1e-5 deg over 200 random poses (tools: /tmp/rl_b4/compute_placements3.py,
//      2026-11-24). The arm skeleton here is the web sim's planar idealisation
//      (arm_config.js): mesh pivots are anchored to ITS pivots, lateral y offsets
//      are collapsed so meshes ride the planar bones (documented in README).
//   2. CAPSULE FALLBACK: the original primitive rig below. If ANY STL fetch/parse
//      fails (404, bad file, missing STLLoader) we silently keep the capsule rig —
//      the sim never breaks (also covers headless SwiftShader runs).
// STL units are METRES (the onshape-to-robot sim set; the MJCF references them
// without a scale attribute) — no mm scaling needed.
const SERVO_PALETTE = [0xf24d4d, 0xfa9e33, 0xf2d940, 0x59cc66, 0x4da6f2]; // ProceduralArm.cs palette

// Per-joint STL placements in the WEB joint frames at the arm-up calibration pose.
// pos = robot-frame metres relative to the joint pivot; quat = robot-frame [w,x,y,z].
// joint: 0 pan · 1 lift · 2 elbow · 3 wrist_flex · 4 wrist_roll · -1 static base.
const SO101_MESH_PLACEMENTS = [
  { mesh: "base_motor_holder_so101_v1", joint: -1, pos: [-0.006365, -0.000099, -0.002400], quat: [0.5000000, 0.5000000, 0.5000000, 0.5000000] },
  { mesh: "base_so101_v2", joint: -1, pos: [-0.006365, -0.000000, -0.002400], quat: [0.5000000, 0.5000000, 0.5000000, 0.5000000] },
  { mesh: "sts3215_03a_v1", joint: -1, pos: [0.026335, -0.000000, 0.043700], quat: [1.0000000, -0.0000000, -0.0000000, 0.0000000] },
  { mesh: "waveshare_mounting_plate_so101_v2", joint: -1, pos: [-0.030983, -0.000199, 0.047400], quat: [0.5000000, 0.5000000, 0.5000000, 0.5000000] },
  { mesh: "sts3215_03a_v1", joint: 0, pos: [0.030435, 0.000000, 0.041700], quat: [0.5000000, 0.5000000, -0.5000000, 0.5000000] },
  { mesh: "motor_holder_so101_base_v1", joint: 0, pos: [0.067634, 0.000000, -0.015850], quat: [-0.5000000, -0.5000000, -0.5000000, 0.5000000] },
  { mesh: "rotation_pitch_so101_v1", joint: 0, pos: [-0.012166, 0.000000, -0.046400], quat: [0.0000000, 0.0000000, -0.7071070, -0.7071070] },
  { mesh: "sts3215_03a_v1", joint: 1, pos: [0.048704, 0.000000, 0.122183], quat: [0.7018604, 0.7018604, -0.0859784, 0.0859784] },
  { mesh: "upper_arm_so101_v1", joint: 1, pos: [0.033479, 0.000000, 0.069464], quat: [-0.5570860, -0.5570860, -0.4354942, 0.4354942] },
  { mesh: "under_arm_so101_v1", joint: 2, pos: [0.095309, 0.000000, 0.076169], quat: [-0.4902761, -0.4902761, -0.5095386, 0.5095386] },
  { mesh: "motor_holder_so101_wrist_v1", joint: 2, pos: [0.095309, 0.000000, 0.076169], quat: [0.4902761, 0.4902761, 0.5095386, -0.5095386] },
  { mesh: "sts3215_03a_v1", joint: 2, pos: [0.060353, 0.000000, 0.135110], quat: [0.5095386, 0.5095386, -0.4902761, 0.4902761] },
  { mesh: "sts3215_03a_no_horn_v1", joint: 3, pos: [0.060835, 0.000000, 0.055100], quat: [-0.7071072, 0.0000000, -0.0000000, 0.7071072] },
  { mesh: "wrist_roll_pitch_so101_v2", joint: 3, pos: [0.060835, 0.000000, 0.040700], quat: [-0.0000000, 0.7071072, 0.7071072, -0.0000000] },
  { mesh: "sts3215_03a_v1", joint: 4, pos: [0.053139, 0.000000, 0.034100], quat: [0.0172091, 0.0172091, -0.7068977, -0.7068977] },
  { mesh: "wrist_roll_follower_so101_v1", joint: 4, pos: [0.060845, 0.000000, 0.009751], quat: [-0.0243374, 0.0000000, -0.0000000, 0.9997039] },
  { mesh: "moving_jaw_so101_v1", joint: 4, pos: [0.040663, 0.000000, 0.034100], quat: [-0.0172091, 0.0172091, -0.7068977, 0.7068977] },
];

// Moving-jaw hinge axis (robot frame at the arm-up pose; the 2.79° calib offset of the
// wrist_roll joint origin is baked in) + jaw joint travel, from so101_new_calib.xml.
const JAW_AXIS = [0.048660, -0.998815, -0.000001];
const JAW_OPEN_RAD = 1.7453291995659765;    // +100° = fully open (MJCF gripper range)
const JAW_CLOSE_RAD = -0.17453297762778586; // -10° = closed

const STL_DIR = "./assets/so101/";
// Neutral two-tone: dark-grey structure + amber accent on the servo bodies (the MJCF's
// own palette family: black servos / amber structure — inverted so parts read in-scene).
const STL_STRUCT_COLOR = 0x57606c;
const STL_ACCENT_COLOR = 0xcf9d3f;
const ACCENT_MESHES = new Set(["sts3215_03a_v1", "sts3215_03a_no_horn_v1"]);

function capsuleMesh(r, len, color) {
  const geo = new THREE.CapsuleGeometry(r, Math.max(0.01, len - 2 * r), 6, 12);
  return new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.35 }));
}
function boxMesh(w, h, d, color) {
  return new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
    new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.2 }));
}
function cylMesh(r, h, color) {
  return new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 20),
    new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.4 }));
}

// orient a three mesh whose local +Y is its length axis so it spans [a,b] (three coords)
function setSpan(mesh, aRobot, bRobot, radius) {
  const a = new THREE.Vector3(...r2t(aRobot));
  const b = new THREE.Vector3(...r2t(bRobot));
  const mid = a.clone().add(b).multiplyScalar(0.5);
  mesh.position.copy(mid);
  const d = b.clone().sub(a);
  const len = d.length() || 1e-6;
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize());
  mesh.scale.set(1, len / (mesh.userData.len0 || 1), 1);
  return len;
}

// robot-frame quaternion [w,x,y,z] -> three THREE.Quaternion
function robotQuat3(qRobot) {
  const q = quatRobotToThree(qRobot);
  return new THREE.Quaternion(q[1], q[2], q[3], q[0]);
}

export function buildArm(scene, cfg = ARM_CONFIG) {
  const group = new THREE.Group();
  group.name = "arm";
  scene.add(group);

  const linkColor = 0x9aa7b4, jointColor = 0x3b4a5a, gripColor = 0xd8dde2;

  // base pedestal + foot (static)
  const foot = cylMesh(cfg.baseRadius * 1.9, 0.012, 0x22303e);
  foot.position.set(...r2t([cfg.panPivot[0] * 0.5, 0, 0.006]));
  group.add(foot);
  const base = cylMesh(cfg.baseRadius, cfg.baseHeight, jointColor);
  base.position.set(...r2t([cfg.panPivot[0] * 0.5, 0, cfg.baseHeight / 2]));
  group.add(base);

  // one visual cluster per joint: servo disc at the joint + capsule link after it
  const links = [], servos = [];
  for (let i = 0; i < 4; i++) {
    const j = cfg.joints[i];
    const servo = cylMesh(j.linkRadius * 1.15, j.linkRadius * 1.6, SERVO_PALETTE[i]);
    servo.userData.isServo = true;
    group.add(servo); servos.push(servo);
    const link = capsuleMesh(j.linkRadius, j.linkLength, linkColor);
    link.userData.len0 = j.linkLength;
    group.add(link); links.push(link);
  }
  // forearm roll barrel
  const roll = cylMesh(cfg.joints[4].linkRadius, cfg.jawBaseToTCP * 0.55, SERVO_PALETTE[4]);
  group.add(roll); servos.push(roll);

  // gripper: palm + two fingers (parallel jaw)
  const palm = boxMesh(cfg.gripperWidth + 0.02, cfg.gripperWidth + 0.02, 0.028, jointColor);
  group.add(palm);
  const fingerL = boxMesh(0.012, cfg.gripperLength, 0.03, gripColor);
  const fingerR = boxMesh(0.012, cfg.gripperLength, 0.03, gripColor);
  fingerL.userData.len0 = cfg.gripperLength;
  fingerR.userData.len0 = cfg.gripperLength;
  group.add(fingerL, fingerR);

  // IK target gizmo + EE marker
  const targetGizmo = new THREE.Mesh(
    new THREE.SphereGeometry(0.012, 14, 10),
    new THREE.MeshStandardMaterial({ color: 0xff5db0, emissive: 0x992255, transparent: true, opacity: 0.9 }));
  group.add(targetGizmo);
  const eeDot = new THREE.Mesh(new THREE.SphereGeometry(0.008, 10, 8),
    new THREE.MeshBasicMaterial({ color: 0x4be07a }));
  group.add(eeDot);

  // ---- real-STL skin (async swap-in; capsule rig above stays as the fallback) ----
  const stlStatic = new THREE.Group();          // base meshes (world placement)
  const stlGroups = [];                          // one group per web joint 0..4
  for (let i = 0; i < 5; i++) {
    const g = new THREE.Group();
    g.name = `stl_joint_${i}`;
    g.visible = false;
    group.add(g); stlGroups.push(g);
  }
  group.add(stlStatic);

  // capsule visuals hidden when the full STL skin loads
  const capsuleVisuals = [foot, base, ...servos, ...links, palm, fingerL, fingerR];

  const meshState = { path: "capsule", loaded: 0, total: SO101_MESH_PLACEMENTS.length, files: {} };
  let jawMesh = null;
  let jawBaseQuat = null;
  const jawAxisThree = (() => {
    const t = r2t(JAW_AXIS);                   // robot -> three basis change
    return new THREE.Vector3(t[0], t[1], t[2]).normalize();
  })();

  // Fetch+parse each unique STL once; any failure (404/parse/loader-missing) => null.
  // Resolves when every fetch has settled: meshState.path is final afterwards, so the
  // smoke tests can assert meshes=stl|capsule deterministically (no timers involved).
  const meshesReady = (async () => {
    let loader = null;
    try {
      const m = await import("three/loaders/STLLoader.js");
      loader = new m.STLLoader();
    } catch (e) {
      console.warn("STL skin disabled: STLLoader import failed:", e && (e.stack || e.message) || e);
      meshState.files["<stlloader>"] = "fail"; return meshState;   // capsule fallback
    }
    const geoCache = new Map();                  // file -> Promise<BufferGeometry|null>
    const loadGeo = (name) => {
      if (!geoCache.has(name)) {
        // placement mesh names are the MJCF mesh ids (extension-less); the files on
        // disk carry .stl
        geoCache.set(name, loader.loadAsync(`${STL_DIR}${name}.stl`)
          .then((g) => { meshState.files[name] = "ok"; return g; })
          .catch((e) => { console.warn(`STL fetch failed: ${name}`, e && (e.message || e)); meshState.files[name] = "fail"; return null; }));
      }
      return geoCache.get(name);
    };
    const geos = await Promise.all(SO101_MESH_PLACEMENTS.map((pl) => loadGeo(pl.mesh)));
    const ok = geos.every((g) => g !== null);
    if (!ok) { meshState.path = "capsule"; return meshState; }    // silent full fallback
    const matStruct = new THREE.MeshStandardMaterial({
      color: STL_STRUCT_COLOR, roughness: 0.62, metalness: 0.18, flatShading: true });
    const matAccent = new THREE.MeshStandardMaterial({
      color: STL_ACCENT_COLOR, roughness: 0.5, metalness: 0.25, flatShading: true });
    SO101_MESH_PLACEMENTS.forEach((pl, i) => {
      const mesh = new THREE.Mesh(geos[i], ACCENT_MESHES.has(pl.mesh) ? matAccent : matStruct);
      mesh.name = `stl_${pl.mesh}${pl.joint >= 0 ? `_j${pl.joint}` : "_base"}`;
      mesh.position.set(...r2t(pl.pos));
      mesh.quaternion.copy(robotQuat3(pl.quat));
      mesh.visible = false;                      // revealed together below (atomic swap)
      (pl.joint >= 0 ? stlGroups[pl.joint] : stlStatic).add(mesh);
      if (pl.mesh === "moving_jaw_so101_v1") { jawMesh = mesh; jawBaseQuat = mesh.quaternion.clone(); }
      meshState.loaded++;
    });
    if (jawMesh && !jawBaseQuat) jawBaseQuat = jawMesh.quaternion.clone();
    // atomic swap: STL skin on, capsule primitives off
    for (const g of stlGroups) g.visible = true;
    for (const m of [...stlStatic.children, ...stlGroups.flatMap((g) => g.children)]) m.visible = true;
    for (const m of capsuleVisuals) m.visible = false;
    meshState.path = "stl";
    return meshState;
  })();

  const reach = totalReach(cfg);

  function apply(state) {
    // state = { angles:[yaw,sh,el,wr,roll], close:0..1 }
    const F = fk(state.angles, cfg);
    const [P0, P1, P2, P3, P4, P5] = F.points;
    const q3 = (mat) => {
      const q = quatRobotToThree(matToQuat(mat));
      return new THREE.Quaternion(q[1], q[2], q[3], q[0]); // [w,x,y,z]->three(x,y,z,w)
    };
    // servos at joint origins; links span joint->next joint
    // (link 0 = P0->P1 bracket, links 1..3 = P_i->P_{i+1} bones)
    for (let i = 0; i < 4; i++) {
      const pos = F.joints[i].pos;
      servos[i].position.set(...r2t(pos));
      servos[i].quaternion.copy(q3(F.joints[i].mat));
      setSpan(links[i], F.points[i], F.points[i + 1]);
      // STL skin rides the SAME joint frames (visible only after meshes load)
      stlGroups[i].position.set(...r2t(pos));
      stlGroups[i].quaternion.copy(q3(F.joints[i].mat));
    }
    roll.position.set(...r2t(P4));
    roll.quaternion.copy(q3(F.joints[4].mat));
    stlGroups[4].position.set(...r2t(P4));
    stlGroups[4].quaternion.copy(q3(F.joints[4].mat));

    palm.position.set(...r2t(vadd(P4, vscale(F.toolDir, 0.014))));
    palm.quaternion.copy(q3(F.joints[4].mat));
    const halfOpen = cfg.gripperWidth * 0.5;
    const sep = halfOpen - 0.001 - (halfOpen - 0.006) * state.close; // world-space inward slide
    const lPos = vadd(vadd(P4, vscale(F.toolDir, 0.014 + 0.02 + cfg.gripperLength / 2)), vscale(F.toolLeft, sep));
    const rPos = vadd(vadd(P4, vscale(F.toolDir, 0.014 + 0.02 + cfg.gripperLength / 2)), vscale(F.toolLeft, -sep));
    // fingers oriented along tool dir: build via quaternion from tool mat
    const toolQuat = q3(F.joints[4].mat);
    const align = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0), new THREE.Vector3(...r2t(F.toolDir)));
    fingerL.quaternion.copy(align);
    fingerR.quaternion.copy(align);
    fingerL.position.set(...r2t(lPos));
    fingerR.position.set(...r2t(rPos));

    // real moving jaw: hinge about JAW_AXIS, +100° open .. -10° closed (MJCF range)
    if (jawMesh && jawBaseQuat) {
      const jawTheta = JAW_OPEN_RAD + (JAW_CLOSE_RAD - JAW_OPEN_RAD) * Math.min(1, Math.max(0, state.close));
      const q = new THREE.Quaternion().setFromAxisAngle(jawAxisThree, jawTheta);
      jawMesh.quaternion.copy(jawBaseQuat).premultiply(q);
    }

    targetGizmo.position.set(...r2t(state.ikTargetWorld || F.tcp));
    eeDot.position.set(...r2t(F.tcp));

    return F;
  }

  return { group, apply, cfg, reach, targetGizmo, eeDot, meshes: { fingerL, fingerR, palm },
           meshState, meshesReady };
}
