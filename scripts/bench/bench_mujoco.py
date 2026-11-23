#!/usr/bin/env python3
"""MuJoCo 4.0.1 local benchmark for the robot_learning repo.

Machine target: AMD Ryzen AI Max+ 395 (32 threads), Radeon 8060S iGPU, Linux, no CUDA.

Measures, with REAL numbers printed as a table and dumped to JSON next to this script:
  1. GL backend probe (egl / glfw / osmesa): offscreen Renderer creation at 640x480.
  2. Physics steps/sec (no render) for humanoid, two-link, so101_simple, so101_official.
  3. Offscreen render FPS at 640x480 and 1280x720 with the best working backend.
  4. Multithreaded rollout scaling (mujoco.rollout, N envs on N threads) for N in [1,8,32].

Run:  sim/py/.venv/bin/python scripts/bench/bench_mujoco.py [--quick]
GL probing runs in subprocesses so a broken backend can never crash the whole bench.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent.parent
MODELS = {
    "humanoid": REPO / "sim/mujoco/bench/humanoid_simple.xml",
    "two_link": REPO / "sim/mujoco/bench/two_link.xml",
    "so101_simple": REPO / "sim/mujoco/so101_simple/so101_simple.xml",
    "so101_official": REPO / "sim/mujoco/so101_official/so101_new_calib.xml",
}
BACKENDS = ["egl", "glfw", "osmesa"]
SCALING_WORKERS = [1, 8, 32]


# ---------------------------------------------------------------- hardware info
def hw_info() -> dict:
    info = {
        "hostname": platform.node(),
        "kernel": platform.release(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.strip().split()[0]) // (1024 * 1024)  # GB
    except OSError:
        pass
    info["mem_total_gb"] = mem.get("MemTotal")
    info["mem_available_gb"] = mem.get("MemAvailable")
    # GPU identity: mujoco 4.x dropped the GL string convenience API, so ask
    # Mesa directly (glxinfo -B).
    try:
        out = subprocess.run(
            ["glxinfo", "-B"], capture_output=True, text=True, timeout=15
        ).stdout
        for line in out.splitlines():
            if "OpenGL renderer string" in line:
                info["gpu"] = line.split(":", 1)[1].strip()
                break
    except (OSError, subprocess.SubprocessError):
        pass
    if "gpu" not in info:
        try:
            out = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=15
            ).stdout
            gpus = [
                l.split(":", 2)[-1].strip()
                for l in out.splitlines()
                if "VGA" in l or "Display controller" in l
            ]
            if gpus:
                info["gpu"] = gpus[0]
        except (OSError, subprocess.SubprocessError):
            pass
    return info


# ------------------------------------------------------------ GL probe (child)
def probe_child(backend: str, width: int, height: int, model_path: str) -> int:
    """Runs in a subprocess: try one GL backend, print a JSON line, exit 0/1."""
    os.environ["MUJOCO_GL"] = backend
    os.environ.pop("PYOPENGL_PLATFORM", None)
    out: dict = {"backend": backend, "width": width, "height": height}
    try:
        import mujoco  # deferred: MUJOCO_GL must be set first

        model = mujoco.MjModel.from_xml_path(model_path)
        data = mujoco.MjData(model)
        t0 = time.perf_counter()
        renderer = mujoco.Renderer(model, height=height, width=width)
        create_s = time.perf_counter() - t0
        cam = mujoco.MjvCamera()
        cam.lookat[:] = [0, 0, 0.3]
        cam.distance = 1.5
        renderer.update_scene(data, camera=cam)
        frame = renderer.render()
        out.update(
            ok=True,
            create_s=round(create_s, 3),
            frame_shape=list(frame.shape),
            dtype=str(frame.dtype),
        )
        # mujoco 4.x: MjrRendererInfo only reports backend style ("opengl");
        # real GPU identity comes from hw_info()'s glxinfo query.
        try:
            from mujoco._render import MjrRendererInfo

            rinfo = MjrRendererInfo()
            mujoco.mjr_getRendererInfo(rinfo)
            out["render_backend"] = rinfo.backend
        except Exception as e:  # noqa: BLE001 - best effort only
            out["render_backend"] = f"unavailable ({type(e).__name__})"
        renderer.close()
        print(json.dumps(out))
        return 0
    except Exception as e:  # noqa: BLE001 - report, don't crash
        out.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(json.dumps(out))
        return 1


def probe_backends(model_path: str, width: int, height: int, timeout: int = 90) -> dict:
    results = {}
    for backend in BACKENDS:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_probe",
            backend,
            str(width),
            str(height),
            model_path,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "MUJOCO_GL": backend},
            )
            line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            results[backend] = (
                json.loads(line)
                if line
                else {
                    "backend": backend,
                    "ok": False,
                    "error": f"no output, rc={proc.returncode}",
                    "stderr": proc.stderr.strip()[-300:],
                }
            )
        except subprocess.TimeoutExpired:
            results[backend] = {
                "backend": backend,
                "ok": False,
                "error": f"timeout after {timeout}s (hard crash)",
            }
        except Exception as e:  # noqa: BLE001
            results[backend] = {
                "backend": backend,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }
        status = "OK " if results[backend].get("ok") else "FAIL"
        detail = results[backend].get("render_backend") or results[backend].get(
            "error", ""
        )
        print(f"  [{status}] {backend:7s} {width}x{height}: {str(detail)[:100]}")
    return results


# --------------------------------------------------------------- stepping bench
def bench_steps(
    model_path: str | Path, n_steps: int, repeats: int, low_mem: bool
) -> dict:
    import mujoco
    import numpy as np

    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    nstep = min(n_steps, 2500) if low_mem else n_steps
    rep_sps = []
    for _ in range(repeats):
        mujoco.mj_resetData(model, data)
        t = 0.0
        t0 = time.perf_counter()
        for i in range(nstep):
            # smooth sinusoids so actuators/constraints do real work every step
            phase = 2.0 * np.pi * t
            for j in range(model.nu):
                data.ctrl[j] = 0.5 * np.sin(phase * (0.7 + 0.1 * j) + j)
            mujoco.mj_step(model, data)
            t += model.opt.timestep
        rep_sps.append(nstep / (time.perf_counter() - t0))
    rep_sps.sort()
    return {
        "model": str(model_path),
        "name": Path(model_path).stem,
        "nq": int(model.nq),
        "nv": int(model.nv),
        "nu": int(model.nu),
        "nbody": int(model.nbody),
        "ngeom": int(model.ngeom),
        "timestep": float(model.opt.timestep),
        "steps": nstep,
        "repeats": repeats,
        "steps_per_s_best": round(rep_sps[-1], 1),
        "steps_per_s_median": round(rep_sps[len(rep_sps) // 2], 1),
        "ms_per_step_best": round(1000.0 / rep_sps[-1], 4),
        "warnings_after": int(np.sum(data.warning.number)),
    }


# --------------------------------------------------------------- render fps
def bench_render(
    model_path: str | Path,
    backend: str,
    width: int,
    height: int,
    warmup: int,
    frames: int,
) -> dict:
    assert frames >= 1, "need at least 1 timed frame"
    os.environ["MUJOCO_GL"] = backend
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=height, width=width)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.1, 0.0, 0.25]
    cam.distance = 1.0
    t0 = time.perf_counter()
    frame_shape = [0, 0, 0]
    for i in range(warmup + frames):
        cam.azimuth = (i * 360.0 / (warmup + frames)) % 360.0  # force real redraws
        if i == warmup:
            t0 = time.perf_counter()
        renderer.update_scene(data, camera=cam)
        frame_shape = list(renderer.render().shape)
    dt = time.perf_counter() - t0
    renderer.close()
    return {
        "backend": backend,
        "width": width,
        "height": height,
        "warmup": warmup,
        "frames": frames,
        "fps": round(frames / dt, 1),
        "ms_per_frame": round(1000.0 * dt / frames, 2),
        "frame_shape": frame_shape,
    }


# ------------------------------------------------------- multithreaded scaling
def bench_scaling(
    model_path: str | Path, n_step: int, workers_list: list[int], low_mem: bool
) -> list[dict]:
    """N parallel rollouts on N threads via mujoco.rollout (4.x native)."""
    os.environ.setdefault("MUJOCO_GL", "egl")  # GL irrelevant for pure stepping
    import mujoco
    import numpy as np
    from mujoco import rollout as mjrollout

    model = mujoco.MjModel.from_xml_path(str(model_path))
    spec = mujoco.mjtState.mjSTATE_FULLPHYSICS
    nstate = mujoco.mj_stateSize(model, spec)
    nstep = min(n_step, 1000) if low_mem else n_step

    # build one honest initial state from a reset MjData (qpos0 reference pose;
    # a zeros state would teleport free bodies to the origin)
    probe_data = mujoco.MjData(model)
    mujoco.mj_resetData(model, probe_data)
    init1 = np.zeros(nstate)
    mujoco.mj_getState(model, probe_data, init1, spec)

    rows = []
    for n in workers_list:
        datas = [mujoco.MjData(model) for _ in range(n)]
        init = np.tile(init1, (n, 1))
        # per-env phase-shifted sinusoidal controls -> every thread does real work
        tgrid = np.arange(nstep) * model.opt.timestep
        ctrl = np.zeros((n, nstep, model.nu))
        for e in range(n):
            for j in range(model.nu):
                ctrl[e, :, j] = 0.5 * np.sin(
                    2 * np.pi * tgrid * (0.7 + 0.1 * j) + 1.0 * e + j
                )
        t0 = time.perf_counter()
        state, _ = mjrollout.rollout(
            model, datas, init, ctrl, control_spec=int(mujoco.mjtState.mjSTATE_CTRL)
        )
        dt = time.perf_counter() - t0
        rows.append(
            {
                "workers": n,
                "nstep": nstep,
                "wall_s": round(dt, 3),
                "agg_steps_per_s": round(n * nstep / dt, 1),
                "per_env_steps_per_s": round(nstep / dt, 1),
                "speedup_vs_1": None,  # filled below
            }
        )
        print(
            f"  N={n:3d}: {n * nstep / dt:12,.0f} steps/s aggregate "
            f"({dt:.2f}s wall for {n * nstep:,} steps)"
        )
    base = rows[0]["agg_steps_per_s"]
    for r in rows:
        r["speedup_vs_1"] = round(r["agg_steps_per_s"] / base, 2)
    return rows


# ------------------------------------------------------------------- reporting
def print_table(
    title: str, rows: list[dict], cols: list[tuple[str, Callable[[dict], str]]]
) -> None:
    """cols: (header, formatter taking the full row dict)."""
    print(f"\n== {title} ==")
    widths = [max([len(key)] + [len(fmt(r)) for r in rows]) for key, fmt in cols]
    print(" | ".join(key.ljust(w) for (key, _), w in zip(cols, widths)))
    print("-|-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(fmt(r).ljust(w) for (_, fmt), w in zip(cols, widths)))


# ------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--steps",
        type=int,
        default=10000,
        help="steps per repeat for the physics bench (default 10000)",
    )
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument(
        "--scaling-steps",
        type=int,
        default=3000,
        help="steps per env in the multithread rollout bench",
    )
    ap.add_argument("--render-frames", type=int, default=200)
    ap.add_argument("--render-warmup", type=int, default=10)
    ap.add_argument("--sizes", nargs="+", default=["640x480", "1280x720"])
    ap.add_argument("--model", choices=list(MODELS) + ["all"], default="all")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--skip-scaling", action="store_true")
    ap.add_argument(
        "--quick",
        action="store_true",
        help="shorthand: steps=2000, scaling-steps=800, render-frames=50",
    )
    args = ap.parse_args()

    if args.quick:
        args.steps, args.scaling_steps, args.render_frames = 2000, 800, 50

    hw = hw_info()
    low_mem = (hw.get("mem_available_gb") or 0) < 12
    print("=== MuJoCo local benchmark ===")
    print(
        f"host: {hw['hostname']} | {hw.get('cpu_model', '?')} | "
        f"{hw['cpu_count']} threads | RAM total {hw['mem_total_gb']} GB, "
        f"available {hw['mem_available_gb']} GB | GPU: {hw.get('gpu', '?')}"
    )
    if low_mem:
        print(
            "!! available RAM < 12 GB -> running REDUCED workloads "
            "(steps->2500 max, scaling-steps->1000 max)"
        )
    import mujoco

    print(f"mujoco: {mujoco.__version__}  numpy: {__import__('numpy').__version__}")

    results = {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hardware": hw,
        "mujoco": mujoco.__version__,
    }

    # -- 1. GL backend probe -------------------------------------------------
    print("\n[1/4] GL backend probe (offscreen Renderer, subprocess-isolated)")
    probe_w, probe_h = 640, 480
    gl = probe_backends(str(MODELS["so101_simple"]), probe_w, probe_h)
    ok_backends = [b for b, r in gl.items() if r.get("ok")]
    best_backend = next(
        (b for b in ("egl", "glfw", "osmesa") if b in ok_backends), None
    )
    results["gl_backends"] = gl
    results["best_backend"] = best_backend
    print(f"  -> working: {ok_backends or 'NONE'}; best: {best_backend}")

    # -- 2. steps/sec ---------------------------------------------------------
    print(
        f"\n[2/4] Physics steps/sec (no render, {args.steps} steps "
        f"x {args.repeats} repeats, best & median)"
    )
    names = list(MODELS) if args.model == "all" else [args.model]
    for k in list(names):
        if not MODELS[k].exists():
            print(f"  -- skipping {k}: {MODELS[k]} not found")
            names.remove(k)
    step_rows = []
    for k in names:
        print(f"  benching {k} ...")
        step_rows.append(
            {"name": k, **bench_steps(MODELS[k], args.steps, args.repeats, low_mem)}
        )
    results["steps"] = step_rows
    print_table(
        "steps/sec (best of repeats)",
        step_rows,
        [
            ("model", lambda r: str(r["name"])),
            ("nq/nv/nu", lambda r: f"{r['nq']}/{r['nv']}/{r['nu']}"),
            ("steps/s best", lambda r: f"{r['steps_per_s_best']:,.0f}"),
            ("steps/s median", lambda r: f"{r['steps_per_s_median']:,.0f}"),
            ("ms/step", lambda r: f"{r['ms_per_step_best']:.4f}"),
        ],
    )

    # -- 3. render fps ---------------------------------------------------------
    if args.skip_render or best_backend is None:
        print(
            "\n[3/4] render FPS: SKIPPED "
            f"({args.skip_render and '--skip-render' or 'no working GL backend'})"
        )
        results["render"] = []
    else:
        print(
            f"\n[3/4] Offscreen render FPS, backend={best_backend} "
            f"({args.render_warmup} warmup + {args.render_frames} timed frames)"
        )
        render_rows = []
        for size in args.sizes:
            w, h = (int(x) for x in size.lower().split("x"))
            print(f"  rendering {w}x{h} ...")
            render_rows.append(
                bench_render(
                    str(MODELS["so101_simple"]),
                    best_backend,
                    w,
                    h,
                    args.render_warmup,
                    args.render_frames,
                )
            )
        results["render"] = render_rows
        print_table(
            "render FPS (so101_simple scene)",
            render_rows,
            [
                ("size", lambda r: f"{r['width']}x{r['height']}"),
                ("fps", lambda r: f"{r['fps']:,.1f}"),
                ("ms/frame", lambda r: f"{r['ms_per_frame']:.2f}"),
            ],
        )

    # -- 4. multithread scaling -----------------------------------------------
    if args.skip_scaling:
        print("\n[4/4] multithread scaling: SKIPPED (--skip-scaling)")
        results["scaling"] = []
    else:
        scaling_model = (
            MODELS["so101_official"]
            if MODELS["so101_official"].exists()
            else MODELS["so101_simple"]
        )
        print(
            f"\n[4/4] Multithread rollout scaling, model={scaling_model.name}, "
            f"{args.scaling_steps} steps/env, workers {SCALING_WORKERS} "
            "(mujoco.rollout, one MjData per thread)"
        )
        rows = bench_scaling(
            str(scaling_model), args.scaling_steps, SCALING_WORKERS, low_mem
        )
        results["scaling"] = rows
        print_table(
            "rollout scaling (aggregate)",
            rows,
            [
                ("workers", lambda r: str(r["workers"])),
                ("steps/s total", lambda r: f"{r['agg_steps_per_s']:,.0f}"),
                ("steps/s per env", lambda r: f"{r['per_env_steps_per_s']:,.0f}"),
                ("speedup vs N=1", lambda r: f"{r['speedup_vs_1']}x"),
            ],
        )

    # -- write JSON next to this script ---------------------------------------
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_main = SCRIPT_DIR / "bench_results.json"
    out_stamp = SCRIPT_DIR / f"bench_results_{stamp}.json"
    for path in (out_main, out_stamp):
        path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nresults written: {out_main}\n                 {out_stamp}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--_probe":
        rc = probe_child(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
        sys.exit(rc)
    sys.exit(main())
