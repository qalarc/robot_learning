#!/usr/bin/env python3
"""test_tape.py — synthetic-frame tests for the HSV tape tracker (no camera).

Run:  sim/py/.venv/bin/python vision/tape_tracker/test_tape.py
Exit non-zero on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tape_tracker import PRESETS, PID, detect_tape, steer_from  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    PASS += 1
    print(f"ok   {name}")


def canvas_with_tape(cx_frac: float, width_frac: float = 0.18) -> np.ndarray:
    """640x480 grey office-desk-ish canvas with one vertical blue tape strip.

    The strip centre is at cx_frac*w; HSV picked to sit inside PRESETS['blue'].
    """
    w, h = 640, 480
    img = np.full((h, w, 3), (120, 120, 120), np.uint8)  # BGR grey
    # BGR for a strong blue: high B, low G/R → converts to HSV H≈110, S≈180
    x0 = int((cx_frac - width_frac / 2) * w)
    x1 = int((cx_frac + width_frac / 2) * w)
    cv2.rectangle(img, (x0, 40), (x1, h - 40), (210, 90, 30), -1)  # BGR blue
    # sprinkle low-sat noise blobs that must NOT be picked as "blue tape"
    cv2.circle(img, (80, 80), 25, (105, 108, 112), -1)
    cv2.circle(img, (560, 400), 20, (95, 100, 105), -1)
    return img


def main() -> None:
    # 1. detection: blue strip centred right of centre --------------------
    img = canvas_with_tape(cx_frac=0.62)  # target right of centre
    det = detect_tape(img, PRESETS["blue"])
    check("tape found", det["found"], f"{det}")
    check(
        "centroid lands on the strip",
        abs(det["cx"] - 0.62) < 0.05,
        f"cx={det['cx']:.3f}",
    )
    check(
        "steer positive for target right of centre",
        steer_from(det["cx"]) > 0.1,
        f"steer={steer_from(det['cx']):.3f}",
    )

    # 2. steer sign flips left of centre ----------------------------------
    img_l = canvas_with_tape(cx_frac=0.35)
    det_l = detect_tape(img_l, PRESETS["blue"])
    check(
        "steer negative for target left of centre",
        det_l["found"] and steer_from(det_l["cx"]) < -0.1,
        f"steer={steer_from(det_l['cx']):.3f}",
    )

    # 3. centred → steer ≈ 0 -----------------------------------------------
    det_c = detect_tape(canvas_with_tape(0.5), PRESETS["blue"])
    check(
        "steer ≈ 0 when centred",
        abs(steer_from(det_c["cx"])) < 0.08,
        f"steer={steer_from(det_c['cx']):.3f}",
    )

    # 4. no tape → found=False, steer 0 ------------------------------------
    plain = np.full((480, 640, 3), (120, 120, 120), np.uint8)
    det_n = detect_tape(plain, PRESETS["blue"])
    check("no tape → not found", not det_n["found"])

    # 5. bbox sane ----------------------------------------------------------
    img = canvas_with_tape(0.62)
    det = detect_tape(img, PRESETS["blue"])
    x, y, bw, bh = det["bbox"]
    strip_w = int(0.18 * 640)
    check(
        "bbox width ≈ strip width",
        abs(bw - strip_w) < strip_w * 0.4,
        f"bbox={det['bbox']} expected~{strip_w}",
    )

    # 6. red preset wraps hue (two-range OR) --------------------------------
    red = np.full((480, 640, 3), (40, 40, 215), np.uint8)  # BGR strong red
    strip = red.copy()
    cv2.rectangle(strip, (300, 40), (380, 440), (40, 40, 215), -1)
    det_r = detect_tape(strip, PRESETS["red"])
    check(
        "red preset detects red strip",
        det_r["found"],
        f"cx={det_r['cx']:.3f} area={det_r['area']:.0f}",
    )

    # 7. PID stays in [-1, 1] and integrates -------------------------------
    pid = PID(1.0, 0.5, 0.1)
    outs = [pid(0.8, 1 / 30) for _ in range(60)]
    check(
        "PID output clamped to [-1,1]",
        all(-1.0 <= o <= 1.0 for o in outs),
        f"max={max(outs)}",
    )

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
