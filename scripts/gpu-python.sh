#!/usr/bin/env bash
# torch-on-iGPU wrapper: MUST run through this so the gfx override is set.
export HSA_OVERRIDE_GFX_VERSION=11.0.0
exec "$(dirname "$0")/../sim/gpu/.venv/bin/python" "$@"
