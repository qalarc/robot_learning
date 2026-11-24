#!/usr/bin/env bash
# pack_for_colab.sh — build robot_learning_colab_bundle.zip, the one-file handoff for
# training/colab/robot_learning_colab.ipynb (free Colab/Kaggle T4 GPUs).
#
# Why: the team can't run GPU training on superlocal (no NVIDIA), so a hackathon-day
# push needs ONE upload containing everything the cloud notebook needs: repo
# essentials + the converted LeRobot dataset + a manifest.
#
# Idempotent: every run rebuilds from git HEAD into a fresh staging dir and
# overwrites the output zip. Safe to re-run.
#
# Usage:
#   scripts/pack_for_colab.sh                                    # repo + MANIFEST only
#   scripts/pack_for_colab.sh --bus-log runs/bus/20261124-034854.jsonl
#   scripts/pack_for_colab.sh --episodes-dir runs/rl/live_reach_1 --action-space ee
#   scripts/pack_for_colab.sh --out /tmp/test.zip --bus-log training/colab/_fixture/bus_log.jsonl
#
# Options:
#   --bus-log PATH        hub log to convert (training/to_lerobot_dataset.py, training venv)
#   --episodes-dir DIR    web-recorder *.jsonl episode dir to convert (alternative)
#   --action-space ee|joint   converter action space (default ee)
#   --repo-id ID          dataset repo_id (default: converter's local/so101)
#   --out PATH            output zip (default: <repo>/robot_learning_colab_bundle.zip)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUS_LOG=""
EPISODES_DIR=""
ACTION_SPACE="ee"
REPO_ID=""
OUT="$REPO/robot_learning_colab_bundle.zip"

while [ $# -gt 0 ]; do
  case "$1" in
    --bus-log) BUS_LOG="$2"; shift 2 ;;
    --episodes-dir) EPISODES_DIR="$2"; shift 2 ;;
    --action-space) ACTION_SPACE="$2"; shift 2 ;;
    --repo-id) REPO_ID="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1 (see header)" >&2; exit 2 ;;
  esac
done

if [ -n "$BUS_LOG" ] && [ -n "$EPISODES_DIR" ]; then
  echo "--bus-log and --episodes-dir are mutually exclusive" >&2; exit 2
fi
case "$ACTION_SPACE" in ee|joint) ;; *) echo "--action-space must be ee|joint" >&2; exit 2 ;; esac

PY="$REPO/training/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "training venv missing at $PY — run scripts/setup_training_env.sh first" >&2; exit 1
fi

STAGE="$(mktemp -d /tmp/colab-pack.XXXXXX)"
mkdir -p "$STAGE/repo"

# 1) Repo essentials — `git archive HEAD` carries only tracked files, so venvs,
#    runs/ and caches can never leak into the bundle. Then strip vendor-heavy sim
#    assets (three.js/rapier bundles + STL meshes): the cloud notebook only needs
#    training/, control/, agents/, docs — not 10 MB of meshes.
git -C "$REPO" archive HEAD | tar -x -C "$STAGE/repo"
rm -rf "$STAGE/repo/sim/armsmith_web/vendor"
rm -rf "$STAGE/repo/sim/armsmith_web/assets"
rm -rf "$STAGE/repo/sim/mujoco/so101_official/assets"
rm -rf "$STAGE/repo/vision/hand_tracking/models"

# 2) Dataset (optional) — convert with the training venv, then zip as dataset.zip
#    inside the bundle so the notebook can unzip it to /content/datasets.
CONVERT_LOG="$STAGE/convert.log"
DATASET_NOTE="none (no --bus-log/--episodes-dir given)"
if [ -n "$BUS_LOG$EPISODES_DIR" ]; then
  mkdir -p "$STAGE/ds"
  DS_DIR="$STAGE/ds/so101"
  CONV_ARGS=(--out "$DS_DIR" --action-space "$ACTION_SPACE")
  [ -n "$REPO_ID" ] && CONV_ARGS+=(--repo-id "$REPO_ID")
  if [ -n "$BUS_LOG" ]; then
    [ -f "$BUS_LOG" ] || { echo "bus log not found: $BUS_LOG" >&2; exit 1; }
    "$PY" "$REPO/training/to_lerobot_dataset.py" --bus-log "$BUS_LOG" "${CONV_ARGS[@]}" 2>&1 | tee "$CONVERT_LOG"
  else
    [ -d "$EPISODES_DIR" ] || { echo "episodes dir not found: $EPISODES_DIR" >&2; exit 1; }
    "$PY" "$REPO/training/to_lerobot_dataset.py" --episodes-dir "$EPISODES_DIR" "${CONV_ARGS[@]}" 2>&1 | tee "$CONVERT_LOG"
  fi
  DATASET_NOTE="action-space=$ACTION_SPACE, repo_id=${REPO_ID:-local/so101}"
  (cd "$STAGE/ds" && zip -qr "$STAGE/dataset.zip" so101)
fi

# 3) MANIFEST — what's inside, built from what, versions.
LEROBOT_V="$("$PY" -c 'import lerobot; print(lerobot.__version__)' 2>/dev/null || echo unknown)"
TORCH_V="$("$PY" -c 'import torch; print(torch.__version__)' 2>/dev/null || echo unknown)"
{
  echo "robot_learning colab bundle"
  echo "built_utc : $(date -u +%FT%TZ)"
  echo "git_head  : $(git -C "$REPO" rev-parse HEAD)"
  echo "dataset   : $DATASET_NOTE"
  echo "lerobot   : $LEROBOT_V"
  echo "torch     : $TORCH_V"
  echo "python    : $("$PY" --version 2>&1) (training venv)"
  echo ""
  echo "contents  : repo/ (git archive HEAD; venvs/runs never included — untracked),"
  echo "            dataset.zip (LeRobot v3 dataset: repo_id local/so101, unpack to"
  echo "            /content/datasets in the notebook), MANIFEST.txt"
  echo ""
  echo "stripped to keep the bundle small: sim/armsmith_web/vendor, STL asset dirs,"
  echo "vision/hand_tracking/models (the notebook trains, it does not run the sim)"
  echo ""
  echo "conversion output:"
  cat "$CONVERT_LOG" 2>/dev/null | sed 's/^/  /' || echo "  (no dataset conversion)"
} > "$STAGE/MANIFEST.txt"

# 4) Zip it up.
mkdir -p "$(dirname "$OUT")"
if [ -f "$STAGE/dataset.zip" ]; then
  (cd "$STAGE" && zip -qr "$OUT" repo dataset.zip MANIFEST.txt)
else
  (cd "$STAGE" && zip -qr "$OUT" repo MANIFEST.txt)
fi

echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo "note: the bundle holds git HEAD — commit before packing if you want new repo files inside."
echo "      the notebook itself is uploaded to Colab separately (training/colab/robot_learning_colab.ipynb)."

# Standalone cleanup of the throwaway staging dir (safe: qalcode archives rm targets).
rm -rf "$STAGE"
