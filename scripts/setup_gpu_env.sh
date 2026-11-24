#!/usr/bin/env bash
# Local AMD iGPU (Radeon 8060S, gfx1151) training env — torch ROCm.
# The rocm6.2 wheels ship no gfx1151 kernels; HSA_OVERRIDE_GFX_VERSION=11.0.0
# loads gfx1100 kernels instead (RDNA3.5-compatible). Proven working 2026-11-24:
# 8.7 TFLOPS fp32 matmul, 0.78 ms MLP train steps. Always run via scripts/gpu-python.sh.
set -e
cd "$(dirname "$0")/.."
uv venv --python 3.11 --allow-existing sim/gpu/.venv
uv pip install --python sim/gpu/.venv/bin/python numpy
uv pip install --python sim/gpu/.venv/bin/python torch==2.5.1 \
    --index-url https://download.pytorch.org/whl/rocm6.2
