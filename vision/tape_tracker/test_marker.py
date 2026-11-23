#!/usr/bin/env python3
"""test_marker.py — synthetic ArUco tests: render → warp → detect → pose back.

No camera. Renders id=7 from DICT_6X6_250 with generateImageMarker, composes
it into scenes (fronto-parallel + perspective-warped), then asserts the
detector's ID and a ROUGH pose (default intrinsics ⇒ loose tolerances).

Run:  sim/py/.venv/bin/python vision/tape_tracker/test_marker.py
Exit non-zero on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_pose import DICT, default_intrinsics, detect_markers, marker_yaw  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    PASS += 1
    print(f"ok   {name}")


def render_marker(marker_id: int = 7, px: int = 200) -> np.ndarray:
    return cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(DICT), marker_id, px
    )


def scene_fronto(marker_px_on_scene: int = 80, at=(400, 240)) -> np.ndarray:
    """640x480 scene, marker pasted flat (no rotation) → z ≈ len*f/px."""
    scene = np.full((480, 640, 3), (128, 128, 128), np.uint8)
    m = render_marker(7, 200)
    m2 = cv2.resize(m, (marker_px_on_scene, marker_px_on_scene))
    x, y = at
    x0, y0 = x - marker_px_on_scene // 2, y - marker_px_on_scene // 2
    scene[y0 : y0 + marker_px_on_scene, x0 : x0 + marker_px_on_scene] = (
        m2[:, :, None].repeat(3, axis=2) if m2.ndim == 2 else m2
    )
    return scene


def scene_warped(yaw_like: float = 0.35) -> np.ndarray:
    """Marker pasted then perspective-warped → detector must still find it.

    Warp shifts the right edge closer (like the marker turned away), which
    produces a non-zero yaw in the PnP estimate.
    """
    scene = scene_fronto(200, (320, 240))
    h, w = scene.shape[:2]
    src = np.array([[120, 140], [520, 140], [520, 340], [120, 340]], dtype=np.float32)
    dx = int(200 * yaw_like)  # right edge pushed in → foreshortened
    dst = np.array(
        [[90, 130], [520 - dx, 150], [520 - dx, 330], [90, 350]], dtype=np.float32
    )
    H = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(scene, H, (w, h))


def main() -> None:
    # 1. render + direct detect -------------------------------------------
    m = render_marker(7, 200)
    check(
        "generateImageMarker renders",
        m.shape == (200, 200) and set(np.unique(m)) <= {0, 255},
    )

    scene = scene_fronto(80, (400, 240))
    found = detect_markers(scene, marker_len_m=0.06)
    check("fronto-parallel marker detected", len(found) == 1, f"n={len(found)}")
    if found:
        mk = found[0]
        check("id recovered", mk["id"] == 7, f"id={mk['id']}")

        # expected distance with default K (fx=w=640): z = len_m * fx / px
        z_exp = 0.06 * 640 / 80
        check(
            "rough distance via uncalibrated K",
            0.5 * z_exp < mk["pos_m"][2] < 1.8 * z_exp,
            f"z={mk['pos_m'][2]:.3f} expected≈{z_exp:.3f}",
        )
        check(
            "marker right of centre → +x",
            mk["pos_m"][0] > 0.02,
            f"x={mk['pos_m'][0]:.3f}",
        )
        check(
            "fronto-parallel → yaw ≈ 0",
            abs(mk["yaw_deg"]) < 12,
            f"yaw={mk['yaw_deg']:.1f}°",
        )
        check("camera-frame z positive (in front)", mk["pos_m"][2] > 0)

    # 2. perspective-warped marker ----------------------------------------
    warp = scene_warped(0.35)
    fw = detect_markers(warp, marker_len_m=0.06)
    check("warped marker still detected", len(fw) >= 1, f"n={len(fw)}")
    if fw:
        check("warped id recovered", fw[0]["id"] == 7, f"id={fw[0]['id']}")

    # 3. yaw math (front-face normal convention: -R@[0,0,1] faces camera) ---
    check(
        "identity R ⇒ normal away ⇒ yaw≈±180",
        abs(abs(marker_yaw(np.eye(3))) - 180.0) < 1e-6,
        f"{marker_yaw(np.eye(3)):.1f}",
    )
    ry = cv2.Rodrigues(np.array([0.0, 0.5, 0.0]))[0]
    check(
        "yaw sign: marker rotated +y ⇒ yaw<0",
        marker_yaw(ry) < -20,
        f"{marker_yaw(ry):.1f}",
    )

    # 4. empty scene → no markers ------------------------------------------
    blank = np.full((480, 640, 3), (128, 128, 128), np.uint8)
    check("blank scene → none", detect_markers(blank) == [])

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
