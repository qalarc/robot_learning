// fabrik.js — faithful JS port of Unity ArmSmith/FabrikIK.cs.
// Position-only FABRIK (Forward And Backward Reaching Inverse Kinematics).
// Converges in 3-5 iterations for typical arm targets; no matrix inversion.
// points[0] = root (fixed), modified in place; lengths[i] = |points[i] -> points[i+1]|.

export function fabrikSolve(points, lengths, target, iterations = 5, tolerance = 0.001) {
  const n = points.length;
  if (n < 2) return;

  const root = points[0].slice();

  let totalLen = 0;
  for (let i = 0; i < lengths.length; i++) totalLen += lengths[i];

  // Target unreachable: stretch straight toward it.  [FabrikIK.cs L36-44]
  const dx = target[0] - root[0], dy = target[1] - root[1], dz = target[2] - root[2];
  const rootToTarget = Math.hypot(dx, dy, dz);
  if (rootToTarget > totalLen) {
    const dir = [dx / rootToTarget, dy / rootToTarget, dz / rootToTarget];
    points[0] = root.slice();
    for (let i = 1; i < n; i++)
      points[i] = [
        points[i - 1][0] + dir[0] * lengths[i - 1],
        points[i - 1][1] + dir[1] * lengths[i - 1],
        points[i - 1][2] + dir[2] * lengths[i - 1],
      ];
    return;
  }

  for (let iter = 0; iter < iterations; iter++) {
    const last = points[n - 1];
    if (Math.hypot(last[0] - target[0], last[1] - target[1], last[2] - target[2]) < tolerance) break;

    // --- Backward reaching: set end to target, work toward root.
    points[n - 1] = target.slice();
    for (let i = n - 2; i >= 0; i--) {
      const a = points[i], b = points[i + 1];
      const vx = a[0] - b[0], vy = a[1] - b[1], vz = a[2] - b[2];
      const d = Math.hypot(vx, vy, vz) || 1e-9;
      const L = lengths[i];
      points[i] = [b[0] + (vx / d) * L, b[1] + (vy / d) * L, b[2] + (vz / d) * L];
    }

    // --- Forward reaching: pin root, work toward end.
    points[0] = root.slice();
    for (let i = 1; i < n; i++) {
      const a = points[i], b = points[i - 1];
      const vx = a[0] - b[0], vy = a[1] - b[1], vz = a[2] - b[2];
      const d = Math.hypot(vx, vy, vz) || 1e-9;
      const L = lengths[i - 1];
      points[i] = [b[0] + (vx / d) * L, b[1] + (vy / d) * L, b[2] + (vz / d) * L];
    }
  }
}
