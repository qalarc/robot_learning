// stall.js — in-sim stall detector (the "deterministic detector" of the learning loop).
// Stalled when: (a) best progress-so-far hasn't improved by > eps for N steps
// ("no_progress"), or (b) EE speed ~0 while a far command target remains unreached
// ("ee_stuck_far_target"). Pure function of the observation — no LLM, no model.

export class StallDetector {
  constructor(opts = {}) {
    this.eps = opts.eps ?? 0.003;              // m of progress that counts as improvement
    this.windowSteps = opts.windowSteps ?? 90; // ~1.5 s at 60 Hz
    this.vStuck = opts.vStuck ?? 0.02;         // m/s below which the EE is "not moving"
    this.far = opts.far ?? 0.08;               // m of remaining command distance = "far"
    this.stuckSteps = opts.stuckSteps ?? 45;
    this.reset();
  }

  reset() {
    this.best = Infinity;
    this.noProgress = 0;
    this.prevPos = null;
    this.stillSteps = 0;
    this.steps = 0;
  }

  update({ progressDist, eePos, eeTarget }) {
    this.steps++;
    const reasons = [];

    if (Number.isFinite(progressDist)) {
      if (progressDist < this.best - this.eps) {
        this.best = progressDist;
        this.noProgress = 0;
      } else {
        this.noProgress++;
      }
    }

    let still = false;
    if (eePos && this.prevPos) {
      const v = Math.hypot(eePos[0] - this.prevPos[0], eePos[1] - this.prevPos[1], eePos[2] - this.prevPos[2]) / (1 / 60);
      if (v < this.vStuck) { this.stillSteps++; } else { this.stillSteps = 0; }
      still = this.stillSteps >= this.stuckSteps;
    }
    if (eePos) this.prevPos = eePos.slice();

    const farTarget = eeTarget && eePos
      ? Math.hypot(eeTarget[0] - eePos[0], eeTarget[1] - eePos[1], eeTarget[2] - eePos[2]) > this.far
      : false;

    const stalledNoProgress = this.noProgress >= this.windowSteps;
    const stalledStuck = still && farTarget;
    if (stalledNoProgress) reasons.push("no_progress");
    if (stalledStuck) reasons.push("ee_stuck_far_target");

    const score = Math.max(
      Math.min(1, this.noProgress / this.windowSteps),
      stalledStuck ? 1 : Math.min(1, this.stillSteps / this.stuckSteps) * 0.6
    );
    const stalled = stalledNoProgress || stalledStuck;
    return { stalled, score: stalled ? Math.max(0.5, score) : score, steps: stalled ? this.noProgress : 0, reasons };
  }
}
