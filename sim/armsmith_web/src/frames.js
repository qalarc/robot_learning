// frames.js — robot frame <-> three.js frame conversion helpers.
// Robot frame (PROTOCOL.md): +x forward, +y left, +z up (right-handed).
// three.js page frame: Y-up. Conversion: three.x = x, three.y = z, three.z = -y.
// This is a change of basis B with B * v_robot expressed-in-three = (x, z, -y).

export function r2t(v) { return [v[0], v[2], -v[1]]; }          // robot -> three
export function t2r(v) { return [v[0], -v[2], v[1]]; }          // three -> robot

// ---- Quaternion basis conversion (robot <-> three) ----------------------
// Build the robot-frame rotation matrix from a three quaternion, map basis
// vectors through the axis permutation, and reconstruct the quaternion.
// M_robot = B * M_three * B^T  with B mapping three->robot coords.
export function quatThreeToRobot(q) {
  return _basisQuat(q, [[1, 0, 0], [0, 0, -1], [0, 1, 0]]); // robot = B * three
}

// inverse mapping: three = C * robot  (t.x = r.x, t.y = r.z, t.z = -r.y)
export function quatRobotToThree(q) {
  return _basisQuat(q, [[1, 0, 0], [0, 0, 1], [0, -1, 0]]);
}

function _basisQuat(q, B) {
  // rotation matrix from quaternion (three: x,y,z,w)
  const { x, y, z, w } = q;
  const m = [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ];
  // M_out[i][j] = sum_{a,b} B[i][a] M_in[a][b] B[j][b]
  const R = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++) {
      let s = 0;
      for (let a = 0; a < 3; a++)
        for (let b = 0; b < 3; b++) s += B[i][a] * m[a][b] * B[j][b];
      R[i][j] = s;
    }
  return matToQuat(R);
}

// standard Shepperd's method: rotation matrix -> [w, x, y, z]
export function matToQuat(m) {
  const tr = m[0][0] + m[1][1] + m[2][2];
  let w, x, y, z;
  if (tr > 0) {
    const s = Math.sqrt(tr + 1.0) * 2; w = 0.25 * s;
    x = (m[2][1] - m[1][2]) / s; y = (m[0][2] - m[2][0]) / s; z = (m[1][0] - m[0][1]) / s;
  } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2;
    w = (m[2][1] - m[1][2]) / s; x = 0.25 * s;
    y = (m[0][1] + m[1][0]) / s; z = (m[0][2] + m[2][0]) / s;
  } else if (m[1][1] > m[2][2]) {
    const s = Math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2;
    w = (m[0][2] - m[2][0]) / s; x = (m[0][1] + m[1][0]) / s; y = 0.25 * s;
    z = (m[1][2] + m[2][1]) / s;
  } else {
    const s = Math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2;
    w = (m[1][0] - m[0][1]) / s; x = (m[0][2] + m[2][0]) / s;
    y = (m[1][2] + m[2][1]) / s; z = 0.25 * s;
  }
  const n = Math.hypot(w, x, y, z) || 1;
  return [w / n, x / n, y / n, z / n];
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const DEG = Math.PI / 180, RAD = 180 / Math.PI;
