// arm_config.js — data-driven SO-101 6-DOF arm config (port of ArmConfig.cs ideas),
// with joint limits / segment lengths taken from Assets/Meshes/SOARM100/kinematics.json
// (a copy ships in vendor/kinematics.json for provenance).
//
// Skeleton (ROBOT frame: x fwd, y left, z up — right-handed, matches URDF z-up):
//   pan pivot    P0 = [0.0388, 0, 0.0624]          (shoulder_pan origin, kinematics.json)
//   lift pivot   P1 = P0 + [ -0.0304, 0, +0.0450 ]  (~55mm diagonal bracket rise)
//   elbow        P2 = P1 + bone1 * 0.1126           (upper_arm 112.6 mm)
//   wrist flex   P3 = P2 + bone2 * 0.1349           (lower_arm 134.9 mm)
//   wrist roll   P4 = P3 + bone3 * 0.0631           (wrist->gripper ~63 mm)
//   TCP          P5 = P4 + bone4 * 0.0981           (gripper->TCP 98.1 mm)
//
// Servo zero pose = calibration pose (arm straight up), like the real arm's homing.
//
// REAL_SO101 below carries the physical ground truth parsed from the calibrated
// official MJCF (sim/mujoco/so101_official/so101_new_calib.xml, TheRobotStudio/
// SO-ARM100, so101_new_calib, verified 2026-11-24). The visual STL meshes shipped in
// assets/so101/ come from the same release (Apache-2.0).

export const ARM_CONFIG = {
  armName: "SO-101-follower",
  baseHeight: 0.0624,
  baseRadius: 0.055,
  panPivot: [0.0388, 0.0, 0.0624],
  liftOffset: [-0.0304, 0.0, 0.0450],   // pan pivot -> shoulder_lift pivot
  gripperWidth: 0.062,                  // max jaw opening (m)
  gripperLength: 0.055,                 // finger length (m)
  jawBaseToTCP: 0.0981,                 // gripper_link -> TCP (kinematics.json)
  joints: [
    // axis: 'yaw' rotates about robot +z; 'pitch' about the arm-plane left axis;
    //       'roll' about the link (forearm) direction.
    // min/max: from so101_new_calib.xml joint ranges (rad), verified 2026-11-24.
    // massKg: MJCF body mass carried by this joint's link (dynamic-mode physics).
    { name: "shoulder_pan", axis: "yaw",   linkLength: 0.0540, linkRadius: 0.030,
      min: -1.9198621771937616, max: 1.9198621771937634, servoId: 1,
      massKg: 0.100006 },
    { name: "shoulder_lift", axis: "pitch", linkLength: 0.1126, linkRadius: 0.024,
      min: -1.7453292519943224, max: 1.7453292519943366, servoId: 2,
      massKg: 0.103 },
    { name: "elbow_flex",   axis: "pitch", linkLength: 0.1349, linkRadius: 0.022,
      min: -1.69, max: 1.69, servoId: 3,
      massKg: 0.104 },
    { name: "wrist_flex",   axis: "pitch", linkLength: 0.0631, linkRadius: 0.020,
      min: -1.6580628494556928, max: 1.6580627293335335, servoId: 4,
      massKg: 0.079 },
    { name: "wrist_roll",   axis: "roll",  linkLength: 0.0981, linkRadius: 0.018,
      min: -2.7438472969992493, max: 2.841206309382605, servoId: 5,
      massKg: 0.087 },
  ],
  // Pitches measured from straight-up, positive = lean forward (see fabrik/arm_controller).
  home: [0, 20 * Math.PI / 180, 30 * Math.PI / 180, -50 * Math.PI / 180, 0],
  // IK FABRIK bones — the CONTROLLABLE chain. wrist_flex->wrist_roll (63.1 mm) and
  // gripper->TCP (98.1 mm) are rigidly collinear in this mechanism (wrist_roll spins
  // about that axis, position-only IK can't see it), so they form ONE 161.2 mm bone
  // ending at the TCP: chain = lift->elbow (112.6), elbow->wrist (134.9), wrist->TCP (161.2).
  fabrikLengths: [0.1126, 0.1349, 0.1612],
};

// ---- Real SO-101 physical properties (from so101_new_calib.xml, verified 2026-11-24) ----
// Every value below is read straight out of the calibrated official MJCF so the sim's
// "SPEC" panel, servo model and dynamic physics describe the real robot, not guesses.
export const REAL_SO101 = {
  source: "sim/mujoco/so101_official/so101_new_calib.xml (so101_new_calib, verified 2026-11-24)",
  servoModel: "Feetech STS3215",
  ticksPerRev: 4096,                       // STS3215 magnetic encoder
  degPerTick: 360 / 4096,                  // = 0.0879°/tick
  servoNoLoadSpeedDegPerSec: 270,          // datasheet no-load speed (also ServoModel)
  // <default class="sts3215"> <joint damping="0.60" frictionloss="0.052" armature="0.028"/>
  jointDamping: 0.60,                      // N·m·s/rad
  jointFrictionLoss: 0.052,                // N·m
  jointArmature: 0.028,                    // kg·m² (rotor inertia reflected at the joint)
  // <position kp="998.22" kv="2.731" forcerange="-2.94 2.94"/> (sts3215 class defaults;
  // the six <actuator> entries override forcerange to ±3.35 N·m — we use the override,
  // same as the MuJoCo model when simulated.)
  actuatorKp: 998.22,                      // position gain (from servo P-gain 16 mapping)
  actuatorKv: 2.731,                       // velocity damping gain
  actuatorForceRangeNm: 3.35,              // per-joint torque cap, ±3.35 N·m
  // Link masses (kg), MJCF <inertial mass=...> per body:
  //   base 0.147, shoulder 0.100006, upper_arm 0.103, lower_arm 0.104,
  //   wrist 0.079, gripper 0.087, moving_jaw 0.012
  massesKg: {
    base: 0.147,
    shoulder: 0.100006,
    upper_arm: 0.103,
    lower_arm: 0.104,
    wrist: 0.079,
    gripper: 0.087,
    moving_jaw: 0.012,
  },
  totalMassKg: 0.147 + 0.100006 + 0.103 + 0.104 + 0.079 + 0.087 + 0.012, // 0.632 kg
  // gripper jaw joint (single moving jaw, hinge): <joint name="gripper" range="-0.17453 1.74533"/>
  jawRangeRad: [-0.17453297762778586, 1.7453291995659765], // -10° closed .. +100° open
  // STL visual meshes + licence (assets/so101/)
  meshSource: "TheRobotStudio/SO-ARM100 (so101_new_calib meshes), Apache-2.0",
};

// Workspace safety box (robot frame) — mirrors control/robot_ops.schema.json.
// Lived in arm_controller.js; exported here so the HUD SPEC panel can show it too.
export const WORKSPACE_BOX = { x: [0.03, 0.32], y: [-0.20, 0.20], z: [0.02, 0.28] };

// Total reach from the pan pivot (for the IK safety envelope, like ArmController.cs).
export function totalReach(cfg = ARM_CONFIG) {
  return cfg.fabrikLengths.reduce((a, b) => a + b, 0) + 0.02;
}

// Seeded RNG (mulberry32) — deterministic scenario placement like `seed` in the protocol.
export function makeRng(seed) {
  let a = (seed >>> 0) || 0x9e3779b9;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) | 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
