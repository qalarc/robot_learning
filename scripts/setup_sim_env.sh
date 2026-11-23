#!/usr/bin/env bash
# Recreate the light sim Python environment for robot_learning, idempotently.
#
# This venv is the LIGHT one (bus + vision + MuJoCo tooling): mujoco, opencv-headless,
# mediapipe, websockets, gymnasium, imageio. The HEAVY training env lives in
# training/.venv (CPU torch + lerobot) — see scripts/setup_training_env.sh.
#
# Rules it follows:
#   - no sudo, no system package manager — user-local uv only
#   - exact pins come from sim/py/requirements-freeze.txt (regenerate after upgrades
#     with: uv pip freeze --python sim/py/.venv/bin/python > sim/py/requirements-freeze.txt)
#   - safe to re-run: verifies an existing healthy venv instead of rebuilding it
#
# Usage: ./scripts/setup_sim_env.sh [--rebuild]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO/sim/py/.venv"
FREEZE="$REPO/sim/py/requirements-freeze.txt"
PYVER="3.12"

step() { printf '\n==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 0. uv present? ----------------------------------------------------------
step "checking uv (user-local, no sudo needed)"
if ! command -v uv >/dev/null 2>&1; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    export PATH="$HOME/.local/bin/uv:$PATH"
    echo "found uv at ~/.local/bin/uv"
  else
    die "uv not found. Install WITHOUT sudo: curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi
fi
echo "uv: $(command -v uv) ($(uv --version))"

# --- 1. fast path: existing healthy venv -------------------------------------
venv_healthy() {
  local py="$1"
  [[ -x "$py" ]] || return 1
  "$py" -c 'import mujoco, numpy, cv2, gymnasium, websockets' >/dev/null 2>&1
}

if [[ "${1:-}" != "--rebuild" ]] && venv_healthy "$VENV_DIR/bin/python"; then
  step "existing venv is healthy — verifying pins only (use --rebuild to force)"
  want_mj="$(sed -n 's/^mujoco==//p' "$FREEZE" | head -1)"
  got_mj="$("$VENV_DIR/bin/python" -c 'import mujoco; print(mujoco.__version__)')"
  echo "mujoco: want $want_mj, have $got_mj"
  if [[ "$want_mj" != "$got_mj" ]]; then
    die "venv mujoco ($got_mj) != freeze ($want_mj). Re-run with --rebuild."
  fi
  "$VENV_DIR/bin/python" - <<'EOF'
import mujoco
m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type="plane" size="1 1 .1"/></worldbody></mujoco>')
d = mujoco.MjData(m)
mujoco.mj_step(m, d)
print(f"smoke step OK: mujoco {mujoco.__version__}, nv={m.nv}")
EOF
  echo "venv OK — nothing to do."
  exit 0
fi

# --- 2. (re)create the venv ---------------------------------------------------
if [[ -d "$VENV_DIR" ]]; then
  step "removing stale venv at $VENV_DIR (archived, not deleted)"
  mkdir -p "$HOME/.qalcode-archive"
  ts="$(date +%Y%m%d_%H%M%S)"
  mv "$VENV_DIR" "$HOME/.qalcode-archive/sim_py_venv_$ts"
  echo "moved to ~/.qalcode-archive/sim_py_venv_$ts"
fi

step "creating venv with uv (python $PYVER)"
uv venv --python "$PYVER" "$VENV_DIR"

# --- 3. install exact pins from the freeze ------------------------------------
step "installing pinned packages from requirements-freeze.txt"
uv pip install --python "$VENV_DIR/bin/python" -r "$FREEZE"

# --- 4. verify -----------------------------------------------------------------
step "verifying imports + a physics step + offscreen EGL render"
"$VENV_DIR/bin/python" - <<'EOF'
import sys
print(f"python {sys.version.split()[0]}")
import numpy, cv2, gymnasium, websockets, imageio, mediapipe  # noqa: F401
import mujoco
print(f"mujoco {mujoco.__version__}, numpy {numpy.__version__}, cv2 {cv2.__version__}")
m = mujoco.MjModel.from_xml_string(
    '<mujoco><worldbody><geom type="plane" size="1 1 .1"/></worldbody></mujoco>')
d = mujoco.MjData(m)
mujoco.mj_step(m, d)
print("physics step OK")
import os
os.environ["MUJOCO_GL"] = "egl"  # AMD iGPU via Mesa; falls back gracefully
try:
    r = mujoco.Renderer(m, height=240, width=320)
    r.close()
    print("EGL offscreen render OK")
except Exception as e:
    print(f"EGL render unavailable on this box ({type(e).__name__}: {e}) — stepping still works")
EOF

echo
echo "DONE. Activate with:  source sim/py/.venv/bin/activate"
echo "or call binaries directly: sim/py/.venv/bin/python agents/cli.py roster"
