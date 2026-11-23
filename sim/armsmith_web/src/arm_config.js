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
    { name: "shoulder_pan", axis: "yaw",   linkLength: 0.0540, linkRadius: 0.030,
      min: -110 * Math.PI / 180, max: 110 * Math.PI / 180, servoId: 1 },
    { name: "shoulder_lift", axis: "pitch", linkLength: 0.1126, linkRadius: 0.024,
      min: -100 * Math.PI / 180, max: 100 * Math.PI / 180, servoId: 2 },
    { name: "elbow_flex",   axis: "pitch", linkLength: 0.1349, linkRadius: 0.022,
      min: -96.84 * Math.PI / 180, max: 96.84 * Math.PI / 180, servoId: 3 },
    { name: "wrist_flex",   axis: "pitch", linkLength: 0.0631, linkRadius: 0.020,
      min: -95 * Math.PI / 180, max: 95 * Math.PI / 180, servoId: 4 },
    { name: "wrist_roll",   axis: "roll",  linkLength: 0.0981, linkRadius: 0.018,
      min: -157.2 * Math.PI / 180, max: 162.8 * Math.PI / 180, servoId: 5 },
  ],
  // Pitches measured from straight-up, positive = lean forward (see fabrik/arm_controller).
  home: [0, 20 * Math.PI / 180, 30 * Math.PI / 180, -50 * Math.PI / 180, 0],
  // IK FABRIK bones — the CONTROLLABLE chain. wrist_flex->wrist_roll (63.1 mm) and
  // gripper->TCP (98.1 mm) are rigidly collinear in this mechanism (wrist_roll spins
  // about that axis, position-only IK can't see it), so they form ONE 161.2 mm bone
  // ending at the TCP: chain = lift->elbow (112.6), elbow->wrist (134.9), wrist->TCP (161.2).
  fabrikLengths: [0.1126, 0.1349, 0.1612],
};

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
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
