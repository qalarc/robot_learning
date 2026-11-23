#!/usr/bin/env python3
"""retarget.py — PURE landmark → robot-frame math (numpy only, no camera, no bus).

Everything in here is importable and unit-testable without hardware; see
test_retarget.py. The live loop that feeds these functions is hand_tracker.py.

IMPORTANT — what MediaPipe world landmarks actually are (documented for the
hackathon, learned the hard way in the gesture-control / robot_hand lineage):
  * MediaPipe's ``hand_world_landmarks`` are in METRES, but the origin is the
    hand's own geometric centre — they are NOT an absolute position in the
    camera or in the room. Axes follow the camera convention: +x image right,
    +y image DOWN, +z away from the camera.
  * Therefore the only robust robot target is RELATIVE motion: take a hand-
    relative point (wrist 0 / index MCP 8 average), scale it to comfortable
    arm-reach metres (``scale``), add a fixed workspace anchor (``offset``),
    and mirror depending on handedness. Absolute placement comes from a quick
    calibration (hold hand at workspace centre while --offset is captured).
  * Prior art: relative-motion + mirror-for-handedness idea from
    ~/projects/robot_hand/python/hand_mirror.py (landmark→servo mirroring,
    SMOOTHING/EMA idea) and finger-tip distance ratios from
    ~/projects/gesture-control/python/gesture_tracker.py (lm_dist /
    classify_gesture normalise by hand size); camera→rig axis flip
    (y-down→y-up) pattern from
    ~/projects/github_repos/long-wind/tools/mocap/retarget.py (``V()`` flips
    y/z to get a right-handed y-up frame).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np

# MediaPipe Hands landmark indices (same in Tasks API 1.x and legacy 0.10).
WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
INDEX_MCP = 5
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_TIP = 20
MIDDLE_MCP = 9

# Pose landmarks (PoseLandmarker, 33 points) — subset used here.
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12
POSE_LEFT_ELBOW = 13
POSE_RIGHT_ELBOW = 14
POSE_LEFT_WRIST = 15
POSE_RIGHT_WRIST = 16


def _lm_to_array(lm: Iterable) -> np.ndarray:
    """Accept list-of-[x,y,z], list-of-objects with .x/.y/.z, or ndarray → (21,3)."""
    if isinstance(lm, np.ndarray):
        a = np.asarray(lm, dtype=float)
        return a.reshape(-1, 3)
    out = []
    for p in lm:
        if isinstance(p, (list, tuple, np.ndarray)):
            out.append((float(p[0]), float(p[1]), float(p[2])))
        else:  # Tasks-API Landmark / NormalizedLandmark dataclass
            out.append((float(p.x), float(p.y), float(p.z)))
    return np.asarray(out, dtype=float).reshape(-1, 3)


def palm_size(world: np.ndarray) -> float:
    """Wrist→middle-MCP distance in the same units as ``world`` (metres-ish).

    Same 'normalise by hand size' trick as gesture_tracker.py's lm_dist /
    palm-relative ratios, so scores are distance-to-camera invariant.
    """
    return float(np.linalg.norm(world[MIDDLE_MCP] - world[WRIST]))


def pinch_score(world_landmarks, thr: float = 0.35) -> float:
    """0..1, 1.0 = thumb-index tips touching (pinched), 0 = far apart.

    Raw measure: thumb-tip→index-tip distance divided by palm size
    (wrist→middle-MCP), exactly the normalisation gesture_tracker.py uses for
    its gesture thresholds. ``thr`` (ratio) maps to score 0.
    """
    w = _lm_to_array(world_landmarks)
    ps = palm_size(w)
    if ps < 1e-6:
        return 0.0
    ratio = float(np.linalg.norm(w[THUMB_TIP] - w[INDEX_TIP])) / ps
    return float(max(0.0, min(1.0, 1.0 - ratio / thr)))


def fist_score(world_landmarks) -> float:
    """0..1, 1.0 = closed fist, 0 = open hand.

    A finger counts as curled when its tip is closer to the wrist than its
    MCP knuckle (the folded-finger test hand_mirror.py's finger-angles
    approximate with joint angles; this is the cheap vector version).
    Score = mean over index/middle/ring/pinky, weighted to ignore the thumb
    (thumb stays tucked in many open grips).
    """
    w = _lm_to_array(world_landmarks)
    tips = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)
    mcps = (INDEX_MCP, MIDDLE_MCP, 13, 17)
    curled = []
    for tip, mcp in zip(tips, mcps):
        d_tip = float(np.linalg.norm(w[tip] - w[WRIST]))
        d_mcp = float(np.linalg.norm(w[mcp] - w[WRIST]))
        curled.append(1.0 if d_tip < d_mcp * 1.1 else 0.0)
    return float(np.mean(curled))


# ---------------------------------------------------------------- frames ---


def _world_to_robot_axes(world: np.ndarray, scale: float) -> np.ndarray:
    """Camera-axis world landmarks → robot-frame deltas.

    World landmark axes: +x image right, +y image down, +z away from camera.
    Robot base frame (docs/PROTOCOL.md): +x forward into workspace, +y left,
    +z up, right-handed. Same flip as long-wind retarget.py ``V()``:
      robot_x = -z   (reaching toward camera = pulling back)
      robot_y = -x   (image right = operator's right = robot -y)
      robot_z = -y   (image down is negative height)
    """
    d = world - world.mean(axis=0)  # hand-centred
    return np.stack([-d[:, 2], -d[:, 0], -d[:, 1]], axis=1) * scale


def landmarks_to_ee(
    world_landmarks,
    handedness: str,
    scale: float = 0.6,
    offset: "Sequence[float] | np.ndarray" = (0.0, 0.0, 0.0),
) -> np.ndarray:
    """21 world landmarks → EE position target [x,y,z] in the ROBOT base frame.

    Uses the hand-relative wrist/index-MCP midpoint (a stable "pointing"
    centre — hand_mirror.py mirrors finger motion hand-relative for the same
    reason: world landmarks have no absolute origin, see module docstring).

    ``scale``   : metres of robot travel per hand-relative metre (0.6 default:
                  full comfortable hand sweep ≈ arm reach).
    ``offset``  : workspace anchor [x,y,z] where the neutral hand maps to.
    ``handedness``: "Left"/"Right" from MediaPipe. We mirror **Right** hands
                  on the robot's y axis: in a selfie (unmirrored) camera the
                  user's right hand drifts to image-left as they reach "right",
                  so without the flip the arm would move the wrong way — the
                  same correction hand_mirror.py applies before servo output.
    """
    w = _lm_to_array(world_landmarks)
    r = _world_to_robot_axes(w, float(scale))
    centre = (r[WRIST] + r[INDEX_MCP]) / 2.0
    if str(handedness).strip().lower().startswith("right"):
        centre = centre * np.array([1.0, -1.0, 1.0])
    return centre + np.asarray(offset, dtype=float)


def clamp_to_workspace(
    target: "Sequence[float] | np.ndarray",
    box: "dict | Sequence | np.ndarray | None" = None,
) -> np.ndarray:
    """Clamp an EE target into the reachable box.

    ``box`` forms:
      * dict {"min": [x,y,z], "max": [x,y,z]}  (SI metres, robot base frame)
      * sequence [min_x,min_y,min_z, max_x,max_y,max_z]
      * None → the conservative demo default (±0.30 m around a 0.25 m-high
        shoulder-ish pivot) so a runaway teleop can never smash the table.
    """
    if box is None:
        mn = np.array([-0.30, -0.30, 0.05])
        mx = np.array([0.30, 0.30, 0.45])
    elif isinstance(box, dict):
        mn = np.asarray(box["min"], dtype=float)
        mx = np.asarray(box["max"], dtype=float)
    else:
        a = np.asarray(box, dtype=float).reshape(6)
        mn, mx = a[:3], a[3:]
    t = np.clip(np.asarray(target, dtype=float), mn, mx)
    return t


def arm_keypoints_to_ee(
    pose_landmarks,
    scale: float = 0.8,
    offset: Sequence[float] = (0.0, 0.0, 0.0),
    side: str = "right",
) -> dict:
    """PoseLandmarker 33 keypoints → {position, yaw, pitch} for body teleop.

    Approach direction = shoulder→wrist (the "reaching" vector); position is
    the shoulder→wrist delta scaled + offset. Angles in radians, robot frame:
      yaw   = atan2(dy, dx)     heading of the reach around +z
      pitch = atan2(dz, hypot(dx, dy))  elevation above the shoulder plane
    Left/right chosen via ``side`` (MediaPipe labels are anatomical, but in a
    selfie view "Right" is the operator's right — mirror y exactly like
    landmarks_to_ee so both paths agree).
    """
    p = _lm_to_array(pose_landmarks)
    ls, rs, le, re, lw, rw = (
        POSE_LEFT_SHOULDER,
        POSE_RIGHT_SHOULDER,
        POSE_LEFT_ELBOW,
        POSE_RIGHT_ELBOW,
        POSE_LEFT_WRIST,
        POSE_RIGHT_WRIST,
    )
    if side.lower().startswith("left"):
        sh, wr, el = p[ls], p[lw], p[le]
        mirror = 1.0
    else:
        sh, wr, el = p[rs], p[rw], p[re]
        mirror = -1.0
    # world landmarks here are also hand/person-centred metres, camera axes
    d = (wr - sh) * float(scale)
    x, y, z = -d[2], -d[0] * mirror, -d[1]
    yaw = math.atan2(y, x)
    pitch = math.atan2(z, math.hypot(x, y))
    return {
        "position": [x + offset[0], y + offset[1], z + offset[2]],
        "yaw": yaw,
        "pitch": pitch,
        "elbow_bent": float(np.linalg.norm(el - sh)) > 0.0,
    }


class LowPass:
    """Scalar EMA — the alpha=0.5 smoother from hand_mirror.py SMOOTHING."""

    def __init__(self, alpha: float = 0.5):
        self.alpha = float(alpha)
        self._y: float | None = None

    def reset(self) -> None:
        self._y = None

    def __call__(self, x: float, dt: float = 1 / 30) -> float:
        if self._y is None:
            self._y = float(x)
            return self._y
        a = min(1.0, self.alpha * dt * 30.0) if dt > 0 else self.alpha
        self._y = a * float(x) + (1 - a) * self._y
        return self._y


class OneEuro:
    """One-Euro filter (Casiez et al., CHI 2012) — adaptive-cutoff EMA.

    Chosen over hand_mirror.py's fixed EMA because teleop needs low lag when
    the hand moves fast AND low jitter when it rests; ``--mincutoff 1.0
    --beta 0.007`` (CLI defaults) reproduces the feel of the MediaPipe demo
    loops while staying pure-python. Per-axis instance: OneEuro(vec[0]) etc.
    """

    def __init__(
        self, mincutoff: float = 1.0, beta: float = 0.007, dcutoff: float = 1.0
    ):
        if mincutoff <= 0:
            raise ValueError("mincutoff must be > 0")
        self.mincutoff = float(mincutoff)
        self.beta = float(beta)
        self.dcutoff = float(dcutoff)
        self._x_prev: float | None = None
        self._dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0

    def __call__(self, x: float, dt: float = 1 / 30) -> float:
        if dt <= 0:
            dt = 1 / 30
        if self._x_prev is None:
            self._x_prev = float(x)
            return self._x_prev
        dx = (float(x) - self._x_prev) / dt
        edx = (
            dx * self._alpha(self.dcutoff, dt)
            + (1 - self._alpha(self.dcutoff, dt)) * self._dx_prev
        )
        cutoff = self.mincutoff + self.beta * abs(edx)
        y = (
            float(x) * self._alpha(cutoff, dt)
            + (1 - self._alpha(cutoff, dt)) * self._x_prev
        )
        self._x_prev, self._dx_prev = y, edx
        return y


class Vec3Filter:
    """OneEuro per axis for a 3-vector (ee_target smoothing)."""

    def __init__(self, mincutoff: float = 1.0, beta: float = 0.007):
        self.f = [OneEuro(mincutoff, beta) for _ in range(3)]

    def reset(self) -> None:
        for f in self.f:
            f.reset()

    def __call__(self, v: Sequence[float], dt: float = 1 / 30) -> np.ndarray:
        return np.array([self.f[i](float(v[i]), dt) for i in range(3)])
