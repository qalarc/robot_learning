#!/usr/bin/env python3
"""test_retarget.py — plain-assert unit tests, SYNTHETIC landmarks only (no camera).

Run:  sim/py/.venv/bin/python vision/hand_tracking/test_retarget.py
Exit code non-zero on failure.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retarget as R  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    PASS += 1
    print(f"ok   {name}")


# ---- synthetic landmarks -------------------------------------------------
def synthetic_world(open_hand: bool = True, shift=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Crude 21x3 world landmarks in metres, hand-centred, camera axes.

    x right, y down, z away. Fingers extend -y (up) when open, curl to +z
    when fisted. Wrist sits below centre, hand points up.
    """
    lm = np.zeros((21, 3))
    lm[R.WRIST] = (0.0, 0.05, 0.0)
    lm[R.MIDDLE_MCP] = (0.0, -0.03, 0.0)  # palm ~8 cm
    tips = [R.THUMB_TIP, R.INDEX_TIP, R.MIDDLE_TIP, R.RING_TIP, R.PINKY_TIP]
    mcps = [2, R.INDEX_MCP, R.MIDDLE_MCP, 13, 17]
    x_off = [-0.06, -0.03, 0.0, 0.03, 0.06]  # fingers spread across x
    for x, tip, mcp in zip(x_off, tips, mcps):
        if open_hand:
            lm[tip] = (x, -0.10, 0.0)  # straight out, 7 cm above knuckle
        else:  # fist: tip folds back to the palm
            lm[tip] = (x * 0.5, -0.005, 0.045)
        lm[mcp] = (x * 0.6, -0.03, 0.0)
    lm[R.INDEX_TIP] += np.array(shift)
    lm[R.INDEX_MCP] += np.array(shift)
    return lm


def main() -> None:
    # 1. scaling is applied on the RELATIVE (hand-centred) position ------
    lm = synthetic_world()
    off = np.array([0.10, 0.05, -0.05])
    base = R.landmarks_to_ee(lm, "Left", scale=1.0, offset=off)
    half = R.landmarks_to_ee(lm, "Left", scale=0.5, offset=off)
    # wrist/index midpoint for this synthetic hand maps to ~ (0, +? , -?) scaled
    check(
        "scaling halves the relative target",
        np.allclose((base - off) * 0.5, half - off, atol=1e-9),
        f"base={base} half={half}",
    )
    # offset must shift the target one-for-one (anchor semantics)
    base0 = R.landmarks_to_ee(lm, "Left", scale=1.0, offset=(0, 0, 0))
    check(
        "offset shifts target one-for-one",
        bool(np.allclose(base, base0 + off, atol=1e-9)),
        f"base={base} base0={base0}",
    )

    # 2. Right-mirroring flips y ----------------------------------------
    l = R.landmarks_to_ee(lm, "Left", scale=0.6, offset=(0, 0, 0))
    r = R.landmarks_to_ee(lm, "Right", scale=0.6, offset=(0, 0, 0))
    check(
        "Right-mirroring flips y",
        math.isclose(l[0], r[0], abs_tol=1e-9)
        and math.isclose(l[1], -r[1], abs_tol=1e-9)
        and math.isclose(l[2], r[2], abs_tol=1e-9),
        f"L={l} R={r}",
    )

    # move the index tip right in image space → robot y must go NEGATIVE,
    # and mirrored for a Right hand → positive
    lm_r = synthetic_world(shift=(0.03, 0, 0))
    t_l = R.landmarks_to_ee(lm_r, "Left", 0.6)
    check("image-right → robot -y (left hand)", t_l[1] < l[1], f"{t_l} vs {l}")

    # 3. pinch / fist scores --------------------------------------------
    open_lm, fist_lm = synthetic_world(True), synthetic_world(False)
    check(
        "open hand → pinch score low",
        R.pinch_score(open_lm) < 0.2,
        f"{R.pinch_score(open_lm)}",
    )
    tips_touch = open_lm.copy()
    tips_touch[R.THUMB_TIP] = tips_touch[R.INDEX_TIP]
    check(
        "tips together → pinch score high",
        R.pinch_score(tips_touch) > 0.9,
        f"{R.pinch_score(tips_touch)}",
    )
    check(
        "open hand → fist score 0",
        R.fist_score(open_lm) == 0.0,
        f"{R.fist_score(open_lm)}",
    )
    check(
        "curled hand → fist score 1",
        R.fist_score(fist_lm) == 1.0,
        f"{R.fist_score(fist_lm)}",
    )

    # 4. clamp honours bounds -------------------------------------------
    box = {"min": [-0.3, -0.3, 0.05], "max": [0.3, 0.3, 0.45]}
    wild = np.array([9.0, -7.0, -5.0])
    c = R.clamp_to_workspace(wild, box)
    check(
        "clamp honours explicit bounds",
        bool(np.all(c >= box["min"]) and np.all(c <= box["max"])),
        f"{c}",
    )
    check(
        "clamp passes interior points",
        bool(np.allclose(R.clamp_to_workspace([0.1, 0.1, 0.2], box), [0.1, 0.1, 0.2])),
    )
    d = R.clamp_to_workspace(wild)  # default demo box
    check(
        "clamp default box",
        bool(np.all(d >= [-0.30, -0.30, 0.05]) and np.all(d <= [0.30, 0.30, 0.45])),
    )

    # 5. OneEuro reduces jitter on a noisy constant series ---------------
    rng = np.random.default_rng(7)
    truth = 0.35
    noisy = truth + rng.normal(0, 0.05, 400)
    f = R.OneEuro(mincutoff=1.0, beta=0.007)
    out = np.array([f(x, 1 / 30) for x in noisy])
    check(
        "OneEuro shrinks max deviation vs raw",
        np.abs(out - truth).max() < np.abs(noisy - truth).max(),
        f"filt={np.abs(out - truth).max():.4f} raw={np.abs(noisy - truth).max():.4f}",
    )
    check(
        "OneEuro converges near truth",
        abs(out[-1] - truth) < 0.02,
        f"end={out[-1]:.4f}",
    )
    # lag check: a fast ramp should track better than a hard low-pass
    ramp = np.linspace(0, 1, 90)
    fr = R.OneEuro(mincutoff=1.0, beta=0.007)
    tr = np.array([fr(x, 1 / 30) for x in ramp])
    check(
        "OneEuro tracks a ramp (beta keeps lag bounded)",
        tr[-1] > 0.9,
        f"end={tr[-1]:.3f}",
    )
    v = R.Vec3Filter(1.0, 0.007)
    vout = v([0.2, 0.2, 0.2])
    check("Vec3Filter per-axis", bool(np.allclose(vout, 0.2)))

    # 6. arm_keypoints_to_ee geometry ------------------------------------
    pose = np.zeros((33, 3))
    pose[R.POSE_RIGHT_SHOULDER] = (0, 0, 0)
    # reach "forward" in camera space means -z (toward camera) → robot +x
    pose[R.POSE_RIGHT_WRIST] = (0, 0, -0.5)
    ee = R.arm_keypoints_to_ee(pose, scale=1.0, side="right")
    check(
        "shoulder→wrist forward → robot +x, yaw≈0",
        ee["position"][0] > 0.4 and abs(ee["yaw"]) < 0.2,
        f"{ee}",
    )
    pose2 = pose.copy()
    pose2[R.POSE_RIGHT_WRIST] = (0, -0.5, 0)  # reach up in camera space
    ee2 = R.arm_keypoints_to_ee(pose2, scale=1.0, side="right")
    check(
        "shoulder→wrist upward → +z, pitch≈+90°",
        ee2["position"][2] > 0.4 and ee2["pitch"] > math.radians(60),
        f"{ee2}",
    )

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
