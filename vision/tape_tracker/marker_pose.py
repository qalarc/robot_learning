#!/usr/bin/env python3
"""marker_pose.py — ArUco 6DoF pose on the bus (cv2.aruco, DICT_6X6_250).

Pipeline: detectMarkers → solvePnP (SOLVEPNP_IPPE_SQUARE, exact for square
planar markers) → position in the CAMERA frame (metres) + yaw of the marker
normal. Published as vision.marker per docs/PROTOCOL.md.

⚠ DEFAULT INTRINSICS ARE UNCALIBRATED: unless you pass --calib (an .npz from
cv2.calibrateCamera) we assume fx=fy=frame_width, cx=w/2, cy=h/2 — a ~50°
horizontal FOV guess for a typical webcam. Positions will be roughly right
(z scales ~1/f) but are NOT metrology. For demo-day absolute placement,
print one marker at a known distance and eyeball-scale --marker-len, or do a
proper chessboard calibration (see vision/README.md workflow).

Prior-art note: the "render a marker, warp it, check the pose back" test
pattern comes from the ArUco sections of our earlier robot_vision tooling;
corner order convention (TL,TR,BR,BL ↔ object points (-s/2,s/2)…
counter-clockwise in marker frame) follows the OpenCV docs.

Usage:
  sim/py/.venv/bin/python vision/tape_tracker/marker_pose.py --source 2
  sim/py/.venv/bin/python vision/tape_tracker/marker_pose.py --calib calib.npz
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_REPO / "agents"))

DICT = cv2.aruco.DICT_6X6_250


def default_intrinsics(w: int, h: int) -> np.ndarray:
    """Guess K for an uncalibrated webcam: fx=fy=w (≈53° h-FOV), centre cx/cy."""
    f = float(w)
    return np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]], dtype=np.float64)


def load_calib(path: str) -> tuple[np.ndarray, np.ndarray]:
    """npz with 'mtx'/'dist' (cv2.calibrateCamera convention)."""
    d = np.load(path)
    return d["mtx"].astype(np.float64), d["dist"].astype(np.float64)


def object_points(marker_len_m: float) -> np.ndarray:
    """Marker corners in the marker frame: origin centre, z out of the plane,
    order TL, TR, BR, BL (matches detectMarkers corner order)."""
    s = marker_len_m / 2.0
    return np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], dtype=np.float64)


def marker_yaw(rmat: np.ndarray) -> float:
    """Yaw of the marker's FRONT-face normal in the camera frame, degrees.

    OpenCV's planar convention (IPPE_SQUARE + image-space corner order) yields
    R@[0,0,1] pointing AWAY from the camera for a marker facing us, so the
    front-face normal is -R@[0,0,1]. yaw = atan2(n_x, n_z): 0° head-on,
    ±90° edge-on. (Empirically verified in test_marker.py.)
    """
    n = -rmat @ np.array([0.0, 0.0, 1.0])
    return math.degrees(math.atan2(n[0], n[2]))


def detect_markers(
    frame_bgr: np.ndarray,
    marker_len_m: float = 0.06,
    mtx: np.ndarray | None = None,
    dist: np.ndarray | None = None,
) -> list[dict]:
    """Detect + PnP. PURE (no bus/camera). Returns [{id, pos_m, yaw_deg, corners}]."""
    h, w = frame_bgr.shape[:2]
    if mtx is None:
        mtx = default_intrinsics(w, h)
    if dist is None:
        dist = np.zeros((1, 5), dtype=np.float64)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(DICT), cv2.aruco.DetectorParameters()
    )
    corners, ids, _rej = detector.detectMarkers(gray)
    out: list[dict] = []
    if ids is None:
        return out
    objp = object_points(marker_len_m)
    for i, cid in enumerate(ids.flatten()):
        pts = corners[i].reshape(4, 2).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(
            objp, pts, mtx, dist, flags=cv2.SOLVEPNP_IPPE_SQUARE
        )
        if not ok:
            continue
        rmat, _ = cv2.Rodrigues(rvec)
        out.append(
            {
                "id": int(cid),
                "pos_m": [
                    round(float(tvec[0][0]), 4),
                    round(float(tvec[1][0]), 4),
                    round(float(tvec[2][0]), 4),
                ],
                "yaw_deg": round(marker_yaw(rmat), 1),
                "corners": pts.astype(int).tolist(),
            }
        )
    return out


def annotate(frame: np.ndarray, markers: list[dict]) -> np.ndarray:
    for m in markers:
        pts = np.array(m["corners"], dtype=np.int32)
        cv2.polylines(frame, [pts], True, (80, 255, 80), 2)
        c = pts.mean(axis=0).astype(int)
        cv2.putText(
            frame,
            f"id={m['id']} z={m['pos_m'][2]:.2f}m yaw={m['yaw_deg']:+.0f}°",
            (c[0] - 40, c[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (80, 255, 80),
            1,
            cv2.LINE_AA,
        )
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", default="0")
    ap.add_argument(
        "--marker-len",
        type=float,
        default=0.06,
        help="printed marker side length in metres",
    )
    ap.add_argument("--calib", default="", help=".npz with mtx/dist from calibration")
    ap.add_argument("--dict", type=int, default=DICT, help="cv2.aruco dict id")
    ap.add_argument("--marker-hz", type=float, default=30.0)
    ap.add_argument("--frame-hz", type=float, default=10.0)
    ap.add_argument("--jpeg-w", type=int, default=640)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--bus", default="")
    args = ap.parse_args()

    mtx = dist = None
    if args.calib:
        mtx, dist = load_calib(args.calib)
        print(f"calibration loaded from {args.calib}")
    else:
        print(
            "WARN: using DEFAULT (uncalibrated) intrinsics — pos_m is a rough "
            "estimate; calibrate for absolute scale (vision/README.md)"
        )

    bus = None
    try:
        from bus_client import SyncBus

        bus = SyncBus(
            "vision-marker", url=args.bus or None, roles=["tool"], caps=["aruco"]
        )
        print(f"bus: connected as {bus.name}")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: bus unreachable ({e}); running offline")

    def publish(topic: str, data: dict) -> None:
        if bus is not None:
            try:
                bus.send(topic, data)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: publish failed ({e}); continuing")

    try:
        idx = int(args.source)
        src, is_cam = idx, True
    except ValueError:
        src, is_cam = args.source, False
    backend = cv2.CAP_V4L2 if is_cam else cv2.CAP_FFMPEG
    cap = cv2.VideoCapture(src, backend)
    if is_cam and cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened() or (is_cam and not cap.read()[0]):
        cap.release()
        import find_cameras

        probe = find_cameras.probe_indices(list(range(0, 13)))
        usable = [c["index"] for c in probe if c.get("can_open")]
        sys.exit(
            f"error: cannot open source {args.source!r}; usable: {usable or 'NONE'}"
        )

    last_m_t = 0.0
    last_f_t = 0.0
    frame_count = 0
    fps = 0.0
    t_prev = time.perf_counter()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if not is_cam:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                print("WARN: camera read failed; retrying")
                time.sleep(0.2)
                continue
            now = time.perf_counter()
            dt = max(1e-3, now - t_prev)
            fps = 0.9 * fps + 0.1 / dt if frame_count > 5 else 1 / dt
            t_prev = now
            frame_count += 1

            markers = detect_markers(frame, args.marker_len, mtx, dist)
            h, w = frame.shape[:2]

            if now - last_m_t >= 1.0 / args.marker_hz:
                last_m_t = now
                publish(
                    "vision.marker",
                    {
                        "markers": [
                            {
                                "id": m["id"],
                                "pos_m": m["pos_m"],
                                "yaw_deg": m["yaw_deg"],
                            }
                            for m in markers
                        ],
                        "w": w,
                        "h": h,
                        "fps": round(fps, 1),
                        "t": time.time(),
                    },
                )

            if now - last_f_t >= 1.0 / args.frame_hz:
                last_f_t = now
                vis = annotate(frame.copy(), markers)
                s = min(1.0, args.jpeg_w / vis.shape[1])
                if s < 1.0:
                    vis = cv2.resize(
                        vis, (int(vis.shape[1] * s), int(vis.shape[0] * s))
                    )
                okj, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if okj:
                    publish(
                        "vision.frame",
                        {
                            "from": "marker",
                            "jpeg_b64": base64.b64encode(buf.tobytes()).decode(),
                            "w": vis.shape[1],
                            "h": vis.shape[0],
                        },
                    )
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{frame_count} frames, avg {fps:.1f} fps")
        cap.release()
        if bus is not None:
            bus.close()


if __name__ == "__main__":
    main()
