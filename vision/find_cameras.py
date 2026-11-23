#!/usr/bin/env python3
"""find_cameras.py — enumerate /dev/video* and probe OpenCV camera indices.

Outputs ONE JSON object on stdout (and a human line on stderr) so scripts can
consume it:  [{"index": 2, "dev": "/dev/video2", "res": [1280, 720],
               "driver": "V4L2", "can_open": true}, ...]

Why: on this box V4L2 registers several nodes per physical camera
(metadata/hidden buses: video2, video10, video12), and only some open with
actual frames. OpenCV's index probe tells you which one has pixels.

    sim/py/.venv/bin/python vision/find_cameras.py            # JSON to stdout
    sim/py/.venv/bin/python vision/find_cameras.py --indices 0-8
"""

from __future__ import annotations

import argparse
import glob
import json
import sys

import cv2


def probe_indices(indices: list[int], frames_to_check: int = 1) -> list[dict]:
    """Try opening each index with V4L2 (Linux) and ANY as fallback."""
    # Silence OpenCV's per-index "can't open camera" spam — failures here are
    # EXPECTED (that is the whole point of probing) and we report via JSON.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    out: list[dict] = []
    backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
    for idx in indices:
        entry: dict = {"index": idx, "dev": f"/dev/video{idx}", "can_open": False}
        for be in backends:
            try:
                cap = cv2.VideoCapture(idx, be)
            except Exception:  # never crash the probe on one bad device
                continue
            if not cap.isOpened():
                cap.release()
                continue
            ok = 0
            for _ in range(frames_to_check):
                got, _frame = cap.read()
                ok += int(bool(got))
            entry["can_open"] = ok > 0
            entry["res"] = [
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            ]
            entry["driver"] = (
                "V4L2"
                if be == cv2.CAP_V4L2
                else cap.getBackendName()
                if hasattr(cap, "getBackendName")
                else "ANY"
            )
            cap.release()
            if entry["can_open"]:
                break
        out.append(entry)
    return out


def parse_indices(spec: str) -> list[int]:
    """'0-8' | '0,2,10' | mixed '0-2,10'."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indices", default="0-12", help="OpenCV indices to probe")
    ap.add_argument("--no-probe", action="store_true", help="only list /dev/video*")
    args = ap.parse_args()

    devs = sorted(glob.glob("/dev/video*"))
    result: dict = {"devices": devs, "cameras": []}
    if not args.no_probe:
        result["cameras"] = probe_indices(parse_indices(args.indices))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    usable = [c for c in result["cameras"] if c.get("can_open")]
    print(
        f"find_cameras: {len(devs)} device node(s), {len(usable)} usable index(es): "
        + (", ".join(str(c["index"]) for c in usable) or "NONE"),
        file=sys.stderr,
    )
    # exit 0 when the enumeration itself worked; callers decide if "none" is fatal
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
