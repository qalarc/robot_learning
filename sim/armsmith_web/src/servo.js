// servo.js — faithful JS port of Unity ArmSmith/ServoModel.cs (Feetech STS3215).
// Every joint command passes through this so the sim is a true digital twin:
// commands are rate-limited to the no-load speed and quantised to servo ticks,
// exactly what the real motor would receive.

export class ServoModel {
  constructor(opts = {}) {
    this.servoId = opts.servoId ?? 1;
    this.ticksPerRev = opts.ticksPerRev ?? 4096;   // STS3215: 4096 ticks / 360 deg
    this.centerDeg = opts.centerDeg ?? 180;        // tick 2048 = 180 deg (mid-range)
    // Feetech 12V STS3215 no-load ~270 deg/s (0.222 s/60deg); 7.4V SO-101 follower slower.
    this.maxSpeedDegPerSec = opts.maxSpeedDegPerSec ?? 270;
    // 7.4V SO-101 follower stall torque ~16.5 kg.cm = 1.62 N.m (12V = 2.94 N.m).
    this.maxTorqueNm = opts.maxTorqueNm ?? 1.6;
    this.minDeg = opts.minDeg ?? -180;
    this.maxDeg = opts.maxDeg ?? 180;
    this.invert = opts.invert ?? false;
    this.offsetDeg = opts.offsetDeg ?? 0;
    this.deadbandTicks = opts.deadbandTicks ?? 1;  // < 1 tick of motion is not applied
  }

  /// Game joint angle (deg, 0=neutral) -> raw servo tick [0..ticksPerRev).  [ServoModel.cs]
  angleToTick(jointDeg) {
    let d = jointDeg;
    if (this.invert) d = -d;
    d += this.offsetDeg + this.centerDeg;
    let tick = Math.round((d / 360) * this.ticksPerRev);
    return Math.max(0, Math.min(this.ticksPerRev - 1, tick));
  }

  tickToAngle(tick) {
    let d = (tick / this.ticksPerRev) * 360 - this.centerDeg - this.offsetDeg;
    if (this.invert) d = -d;
    return d;
  }

  /// Rate-limit a commanded angle by the servo's max speed over dt (digital-twin fidelity).
  rateLimit(currentDeg, commandedDeg, dt) {
    const maxStep = this.maxSpeedDegPerSec * dt;
    const delta = Math.max(-maxStep, Math.min(maxStep, commandedDeg - currentDeg));
    return Math.max(this.minDeg, Math.min(this.maxDeg, currentDeg + delta));
  }

  /// F-r1: available torque falls linearly stall -> 0 at no-load speed.
  availableTorque(speedDegPerSec) {
    const frac = 1 - Math.abs(speedDegPerSec) / Math.max(1, this.maxSpeedDegPerSec);
    return Math.max(0, Math.min(1, frac)) * this.maxTorqueNm;
  }
  saturateTorque(requestedNm, speedDegPerSec) {
    const cap = this.availableTorque(speedDegPerSec);
    return Math.max(-cap, Math.min(cap, requestedNm));
  }

  /// Full digital-twin path: rate-limit + tick quantise (+ deadband).
  /// Returns the angle the real motor would actually hold (deg).
  command(currentDeg, targetDeg, dt) {
    const rl = this.rateLimit(currentDeg, targetDeg, dt);
    let tick = this.angleToTick(rl);
    // deadband: if the quantised step is within deadbandTicks of the current held tick, hold
    const curTick = this.angleToTick(currentDeg);
    if (Math.abs(tick - curTick) < this.deadbandTicks) tick = curTick;
    return this.tickToAngle(tick);
  }
}

/// One servo per joint (like ProceduralArm.cs: ids 1..N map to the real bus).
export function makeServos(cfg, ticksPerRev = 4096) {
  return cfg.joints.map((j) => new ServoModel({
    servoId: j.servoId,
    minDeg: j.min * 180 / Math.PI,
    maxDeg: j.max * 180 / Math.PI,
    ticksPerRev,
    maxSpeedDegPerSec: 270,
    maxTorqueNm: 1.6,
  }));
}
