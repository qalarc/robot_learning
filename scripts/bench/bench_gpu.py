#!/usr/bin/env python3
"""Local AMD iGPU (ROCm torch, gfx1151 via HSA override) vs CPU micro-benchmark.

    scripts/setup_gpu_env.sh
    scripts/gpu-python.sh scripts/bench/bench_gpu.py      # wrapper sets the override

Workloads chosen to mirror what we actually train: dense nets (Laya heads, PPO policy),
a small conv net (vision heads), a transformer block (ACT-style action chunking).
Writes bench_gpu_results.json next to this file.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import torch


def timeit(fn, warm: int, iters: int, sync=None) -> float:
    for _ in range(warm):
        fn()
    if sync:
        sync()
    t = time.perf_counter()
    for _ in range(iters):
        fn()
    if sync:
        sync()
    return (time.perf_counter() - t) / iters


def bench(dev: str) -> dict:
    sync = torch.cuda.synchronize if dev == "cuda" else None
    out: dict = {"device": dev, "torch_threads": torch.get_num_threads()}
    if dev == "cuda":
        out["name"] = torch.cuda.get_device_name(0)

    # dense matmul (the raw flops number)
    a = torch.randn(4096, 4096, device=dev)
    b = torch.randn(4096, 4096, device=dev)
    dt = timeit(lambda: a @ b, 3, 15, sync)
    out["matmul4096_fp32_ms"] = round(dt * 1000, 2)
    out["matmul4096_fp32_tflops"] = round(2 * 4096**3 / dt / 1e12, 2)

    def train_step(module, x, y, opt):
        loss = ((module(x) - y) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()

    # MLP: PPO-policy / Laya-head sized, Adam
    m = torch.nn.Sequential(
        torch.nn.Linear(128, 256), torch.nn.ReLU(), torch.nn.Linear(256, 128)
    ).to(dev)
    opt = torch.optim.Adam(m.parameters())
    x = torch.randn(4096, 128, device=dev)
    y = torch.randn(4096, 128, device=dev)
    dt = timeit(lambda: train_step(m, x, y, opt), 10, 100, sync)
    out["mlp_4096x128_train_step_ms"] = round(dt * 1000, 3)

    # small conv net: camera -> features
    c = torch.nn.Sequential(
        torch.nn.Conv2d(3, 32, 5, stride=2),
        torch.nn.ReLU(),
        torch.nn.Conv2d(32, 64, 3, stride=2),
        torch.nn.ReLU(),
        torch.nn.Flatten(),
        torch.nn.Linear(64 * 30 * 30, 128),
    ).to(dev)
    opt = torch.optim.Adam(c.parameters())
    xc = torch.randn(64, 3, 128, 128, device=dev)
    yc = torch.randn(64, 128, device=dev)
    dt = timeit(lambda: train_step(c, xc, yc, opt), 5, 30, sync)
    out["cnn_64x3x128x128_train_step_ms"] = round(dt * 1000, 3)

    # transformer block: ACT-style action chunking over a time sequence
    tr = torch.nn.TransformerEncoderLayer(
        d_model=256, nhead=4, dim_feedforward=512, batch_first=True
    ).to(dev)
    opt = torch.optim.Adam(tr.parameters())
    xt = torch.randn(256, 100, 256, device=dev)
    dt = timeit(lambda: train_step(tr, xt, torch.zeros_like(xt), opt), 3, 20, sync)
    out["transformer_256x100x256_train_step_ms"] = round(dt * 1000, 3)
    return out


def main() -> None:
    res = {
        "host": platform.node(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
    }
    if torch.cuda.is_available():
        res["gpu"] = bench("cuda")
    else:
        res["gpu"] = {
            "device": "cuda",
            "error": "torch.cuda.is_available() is False "
            "(run through scripts/gpu-python.sh so HSA_OVERRIDE_GFX_VERSION is set)",
        }
    res["cpu"] = bench("cpu")
    g, c = res["gpu"], res["cpu"]
    if "matmul4096_fp32_tflops" in g and "matmul4096_fp32_tflops" in c:
        res["gpu_speedup"] = {
            k: round(c[k] / g[k], 2)
            for k in g
            if k.endswith("_ms") and k in c and g[k] > 0
        }
        res["gpu_speedup"]["matmul_tflops"] = round(
            g["matmul4096_fp32_tflops"] / max(c["matmul4096_fp32_tflops"], 1e-9), 2
        )
    text = json.dumps(res, indent=2)
    print(text)
    Path(__file__).with_name("bench_gpu_results.json").write_text(text + "\n")


if __name__ == "__main__":
    main()
