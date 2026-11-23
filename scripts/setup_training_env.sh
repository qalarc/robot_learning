#!/usr/bin/env bash
# Recreate training/.venv exactly: CPU-ONLY torch (no CUDA wheels), then lerobot[training],
# then the +cpu torchvision/torchcodec fix (uv otherwise resolves the PyPI wheels, which
# are built against CUDA torch and crash with "operator torchvision::nms does not exist").
# Idempotent: re-runs verify the existing venv first. No sudo. uv at ~/.local/bin/uv.
#
# Reference versions (2026-11-24): torch 2.15.0+cpu, torchvision 0.29.2+cpu,
# torchcodec 0.17.0+cpu, lerobot 0.7.0, python 3.12.13. Full pins: training/requirements-freeze.txt
# Memory note: install needs ~3 GB disk, <1 GB RAM; training runs are the heavy part —
# check `free -g` (want >14 GB available) before launching the trainer.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/training/.venv"
UV="${UV:-$HOME/.local/bin/uv}"
PYTORCH_CPU="https://download.pytorch.org/whl/cpu"

command -v "$UV" >/dev/null || { echo "uv not found at $UV (install: curl -LsSf https://astral.sh/uv/install.sh | sh)"; exit 1; }

# 0) fast path: if the venv already verifies, do nothing
verify() {
  "$VENV/bin/python" - <<'EOF' >/dev/null 2>&1 || return 1
import torch, torchvision, torchcodec, lerobot
assert torch.__version__.endswith("+cpu"), torch.__version__
assert not torch.cuda.is_available()
EOF
  local leak
  leak=$("$UV" pip list --python "$VENV/bin/python" 2>/dev/null | grep -i '^nvidia' || true)
  [ -z "$leak" ] || { echo "nvidia packages present: $leak"; return 1; }
  echo "training/.venv already OK: $( "$VENV/bin/python" -c 'import torch,lerobot; print(torch.__version__, lerobot.__version__)')"
}

if verify; then exit 0; fi

# 1) venv (python 3.12)
"$UV" venv "$VENV" --python 3.12

# 2) CPU torch FIRST — so nothing else can pull the CUDA build as a dependency
"$UV" pip install --python "$VENV/bin/python" torch --index-url "$PYTORCH_CPU"

# 3) lerobot + training extras (records its own torch requirement as satisfied)
"$UV" pip install --python "$VENV/bin/python" "lerobot[training]"

# 4) MANDATORY fix: lerobot's resolver picks torchvision/torchcodec from PyPI (CUDA builds
#    of the same version numbers). Force the +cpu wheels from the pytorch cpu index.
"$UV" pip install --python "$VENV/bin/python" \
  --reinstall-package torchvision --reinstall-package torchcodec \
  torchvision torchcodec --index-url "$PYTORCH_CPU"

# 5) drop the one nvidia-* package that can still leak (trackio[gpu] extra: NVML binding only)
"$UV" pip uninstall --python "$VENV/bin/python" nvidia-ml-py >/dev/null 2>&1 || true

# 6) verify: no nvidia-*, cpu torch, cuda off
leak=$("$UV" pip list --python "$VENV/bin/python" | grep -i '^nvidia' || true)
if [ -n "$leak" ]; then echo "FAIL: nvidia packages leaked in: $leak"; exit 1; fi
"$VENV/bin/python" - <<'EOF'
import torch, torchvision, torchcodec, lerobot
assert torch.__version__.endswith("+cpu"), torch.__version__
assert not torch.cuda.is_available(), "cuda unexpectedly available"
print(f"OK: torch {torch.__version__} | torchvision {torchvision.__version__} | "
      f"torchcodec {torchcodec.__version__} | lerobot {lerobot.__version__} | cuda={torch.cuda.is_available()}")
EOF

echo "Run the smoke test when ready: $VENV/bin/python $REPO/training/_smoke/smoke_dataset.py"
