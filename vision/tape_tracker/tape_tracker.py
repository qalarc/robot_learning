#!/usr/bin/env python3
"""tape_tracker.py — the "blue tape" colour tracker, generalised + on the bus.

Lineage: our earlier line-following robots steered on blue electrical tape
 HSV threshold → biggest blob → centroid error → steer). This version keeps
the same pipeline but:
  * colour is a flag: --blue | --red | --green | --custom H0 H1 S0 S1 V0 V1
  * morphology open→close kills noise/speckles before contour pick
  * steer = 2*(cx/w)-1 ∈ [-1,1], positive = target right of centre
  * optional --pid turns the raw proportional steer into a PID heading
  * publishes vision.tape (per PROTOCOL.md) + annotated vision.frame (≤10 fps)
  * --learn: click a pixel in the preview window to adopt its HSV — needs a
    display; headless runs print how-to-tune and keep the preset.

Tuning wisdom from the tape lineage that still applies: threshold in HSV
(illumination lives mostly in V), morph-open BEFORE contour, and trust the
biggest blob only when its area clears a floor (--min-area fraction of frame).

Usage:
  sim/py/.venv/bin/python vision/tape_tracker/tape_tracker.py --source 2 --blue
  sim/py/.venv/bin/python vision/tape_tracker/tape_tracker.py --source vid.mp4 \
      --custom 100 130 80 255 60 255 --pid 0.8 0.05 0.1
  sim/py/.venv/bin/python vision/tape_tracker/tape_tracker.py --source 2 --learn
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE.parent))  # vision/ (for find_cameras import)
sys.path.insert(0, str(_REPO / "agents"))

# HSV presets, OpenCV scale (H 0-179). Blue tape classic: H≈100-130.
PRESETS = {
    "blue": ((95, 130), (70, 255), (50, 255)),
    "red": ((160, 10), (70, 255), (50, 255)),  # wraps past 180
    "green": ((45, 85), (60, 255), (40, 255)),
}


class PID:
    """Tiny PID on the normalised centroid error → heading ∈ [-1, 1].

    The tape lineage ran pure P (steer = k * err); --pid adds I to kill
    steady-state offset and D to damp zig-zag. Integrator is clamped
    (anti-windup) because demo-day tape gaps would otherwise wind it up.
    """

    def __init__(self, kp: float, ki: float, kd: float):
        self.kp, self.ki, self.kd = kp, ki, kd
        self._i = 0.0
        self._prev: float | None = None

    def reset(self) -> None:
        self._i = 0.0
        self._prev = None

    def __call__(self, err: float, dt: float) -> float:
        self._i = float(np.clip(self._i + err * max(dt, 1e-3), -1.0, 1.0))
        d = 0.0
        if self._prev is not None and dt > 0:
            d = (err - self._prev) / dt
        self._prev = err
        u = self.kp * err + self.ki * self._i + self.kd * d
        return float(np.clip(u, -1.0, 1.0))


def detect_tape(
    frame_bgr: np.ndarray,
    hsv_lo_hi: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    min_area_frac: float = 0.0005,
    morph: int = 5,
) -> dict:
    """HSV inRange → open/close → largest contour. PURE (no bus, no camera).

    Returns {"found", "cx", "cy", "area", "bbox", "mask"} with cx/cy normalised
    to frame size, bbox = [x, y, w, h] pixels.
    """
    (h0, h1), (s0, s1), (v0, v1) = hsv_lo_hi
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    if h0 <= h1:  # normal hue window
        lo, hi = np.array([h0, s0, v0]), np.array([h1, s1, v1])
        mask = cv2.inRange(hsv, lo, hi)
    else:  # hue wraps (red): two ranges OR-ed
        lo1 = np.array([h0, s0, v0])
        hi1 = np.array([179, s1, v1])
        lo2 = np.array([0, s0, v0])
        hi2 = np.array([h1, s1, v1])
        mask = cv2.bitwise_or(cv2.inRange(hsv, lo1, hi1), cv2.inRange(hsv, lo2, hi2))

    # open removes speckles, close fills tape gaps (both 3x3, `morph` iters)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=morph)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=morph)

    h, w = mask.shape[:2]
    min_area = min_area_frac * w * h
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found, cx, cy, area, bbox = False, 0.5, 0.5, 0.0, [0, 0, 0, 0]
    if contours:
        big = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(big))
        if area >= min_area:
            m = cv2.moments(big)
            if m["m00"] > 0:
                cx = float(m["m10"] / m["m00"]) / w
                cy = float(m["m01"] / m["m00"]) / h
                bbox = [int(v) for v in cv2.boundingRect(big)]
                found = True
    return {
        "found": found,
        "cx": cx,
        "cy": cy,
        "area": area,
        "bbox": bbox,
        "mask": mask,
    }


def steer_from(cx: float) -> float:
    """Normalised centroid → steer ∈ [-1,1], +ve = target right of centre."""
    return 2.0 * float(cx) - 1.0


def annotate(frame: np.ndarray, det: dict, steer: float) -> np.ndarray:
    h, w = frame.shape[:2]
    if det["found"]:
        x, y, bw, bh = det["bbox"]
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), (255, 160, 60), 2)
        cx, cy = int(det["cx"] * w), int(det["cy"] * h)
        cv2.circle(frame, (cx, cy), 6, (80, 255, 80), -1, cv2.LINE_AA)
        cv2.line(frame, (w // 2, 0), (w // 2, h), (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(
        frame,
        f"steer={steer:+.2f} area={det['area']:.0f}",
        (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (80, 255, 80) if det["found"] else (60, 60, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", default="0", help="camera index or video/image path")
    ap.add_argument("--blue", action="store_true", help="blue tape preset (default)")
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--green", action="store_true")
    ap.add_argument(
        "--custom",
        nargs=6,
        type=int,
        metavar=("H0", "H1", "S0", "S1", "V0", "V1"),
        help="explicit HSV range, OpenCV scale",
    )
    ap.add_argument(
        "--min-area", type=float, default=0.0005, help="min blob area as frame fraction"
    )
    ap.add_argument(
        "--pid",
        nargs=3,
        type=float,
        metavar=("KP", "KI", "KD"),
        help="PID heading instead of raw proportional steer",
    )
    ap.add_argument("--tape-hz", type=float, default=30.0)
    ap.add_argument("--frame-hz", type=float, default=10.0)
    ap.add_argument("--jpeg-w", type=int, default=640)
    ap.add_argument(
        "--learn",
        action="store_true",
        help="click the preview to adopt HSV at that pixel (needs display)",
    )
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--bus", default="")
    args = ap.parse_args()

    if args.custom:
        h0, h1, s0, s1, v0, v1 = args.custom
        rng = ((h0, h1), (s0, s1), (v0, v1))
    elif args.red:
        rng = PRESETS["red"]
    elif args.green:
        rng = PRESETS["green"]
    else:
        rng = PRESETS["blue"]  # the lineage default

    pid = PID(*args.pid) if args.pid else None

    # ---------------------------------------------------------------- bus
    bus = None
    try:
        from bus_client import SyncBus

        bus = SyncBus("vision-tape", url=args.bus or None, roles=["tool"], caps=["hsv"])
        print(f"bus: connected as {bus.name}")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: bus unreachable ({e}); running offline")

    def publish(topic: str, data: dict) -> None:
        if bus is not None:
            try:
                bus.send(topic, data)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: publish failed ({e}); continuing")

    # ----------------------------------------------------------- capture
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
            f"error: cannot open source {args.source!r}; usable indices: {usable or 'NONE'}"
        )

    display = args.learn  # --learn needs a window
    if args.learn:
        try:
            cv2.namedWindow("tape_tracker", cv2.WINDOW_NORMAL)
        except cv2.error as e:
            print(
                f"WARN: no display available ({e}); --learn disabled, "
                "tune with --custom instead (see README HSV workflow)"
            )
            display = False

    # --learn state: latest frame is shared with the mouse callback; a click
    # adopts that pixel's HSV ±window as the new range and prints the
    # equivalent --custom line so the tuned colour survives the session.
    shared = {"frame": None, "rng": rng}
    learn_range: list | None = None

    def on_click(event, x, y, _flags, _param) -> None:  # pragma: no cover
        nonlocal learn_range
        if event != cv2.EVENT_LBUTTONDOWN or shared["frame"] is None:
            return
        hsv = cv2.cvtColor(shared["frame"][None, :, :], cv2.COLOR_BGR2HSV)[0, y, x]
        h, s, v = int(hsv[0]), int(hsv[1]), int(hsv[2])
        learn_range = [
            max(0, h - 12),
            min(179, h + 12),
            max(0, s - 60),
            min(255, s + 60),
            max(0, v - 60),
            min(255, v + 60),
        ]
        shared["rng"] = (
            (learn_range[0], learn_range[1]),
            (learn_range[2], learn_range[3]),
            (learn_range[4], learn_range[5]),
        )
        print(
            f"--learn: clicked HSV=({h},{s},{v}) → --custom "
            + " ".join(str(c) for c in learn_range)
        )

    if display:
        cv2.setMouseCallback("tape_tracker", on_click)

    print(f"HSV range: {rng} | pid={args.pid} | source={args.source}")

    last_tape_t = 0.0
    last_frame_t = 0.0
    frame_count = 0
    t_prev = time.perf_counter()
    fps = 0.0

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

            shared["frame"] = frame
            det = detect_tape(frame, shared["rng"], args.min_area)
            err = steer_from(det["cx"]) if det["found"] else 0.0
            if det["found"] and not det.get("_err"):
                pass
            steer = (
                pid(err, dt)
                if (pid and det["found"])
                else (err if det["found"] else 0.0)
            )

            if now - last_tape_t >= 1.0 / args.tape_hz:
                last_tape_t = now
                h, w = frame.shape[:2]
                publish(
                    "vision.tape",
                    {
                        "targets": (
                            [
                                {
                                    "id": 1,
                                    "cx": round(det["cx"], 4),
                                    "cy": round(det["cy"], 4),
                                    "area": round(det["area"] / (w * h), 5),
                                    "bbox": det["bbox"],
                                }
                            ]
                            if det["found"]
                            else []
                        ),
                        "w": w,
                        "h": h,
                        "steer": round(steer, 4),
                        "fps": round(fps, 1),
                        "t": time.time(),
                    },
                )

            if now - last_frame_t >= 1.0 / args.frame_hz or (
                display and frame_count % 3 == 0
            ):
                last_frame_t = now
                vis = annotate(frame.copy(), det, steer)
                if display:
                    if learn_range is None:
                        hint = "click the TAPE colour to adopt its HSV"
                    else:
                        hint = f"adopted {learn_range}"
                    cv2.putText(
                        vis,
                        hint,
                        (8, vis.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
                    cv2.imshow("tape_tracker", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
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
                            "from": "tape",
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
        if display:
            cv2.destroyAllWindows()
        if bus is not None:
            bus.close()


if __name__ == "__main__":
    main()
