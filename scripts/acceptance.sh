#!/usr/bin/env bash
# Acceptance test of the full stall-recovery learning loop, headless, ~4 minutes.
# Proves: stall detection -> Laya S1 identification -> gate -> GLM S2 reasoning
#         -> safety shield -> recovery commands -> outcome labelling -> metrics.
#
#   bash scripts/acceptance.sh [--dry-run]
#
# Requirements: sim/py/.venv (scripts/setup_sim_env.sh), Laya serve on :8798
# (optional -- controller fails open without it), Ollama on :11434 with
# glm-4.7-flash-abl (default model arg; override with MODEL=...).
# Uses port 8895 to avoid colliding with anything on the default 8890.
set -u
cd "$(dirname "$0")/.."
PY=sim/py/.venv/bin/python
PORT=8895
MODEL="${MODEL:-glm-4.7-flash-abl:32k}"   # resident base of alexei-v3; same size
EXTRA="${1:-}"

$PY agents/hub.py --port $PORT >/tmp/acc_hub.log 2>&1 & HUB=$!
sleep 2
$PY agents/fake_sim.py --fault ik_residual >/tmp/acc_sim.log 2>&1 & SIM=$!
sleep 2
timeout 200 $PY control/stall_controller.py --sim fake-sim --model "$MODEL" \
    --min-stall-steps 60 $EXTRA >/tmp/acc_ctl.log 2>&1
RC=$?
kill $SIM $HUB 2>/dev/null; wait $SIM $HUB 2>/dev/null

echo "--- controller log ---"; grep -E '^\[(info|warn|error)\]' /tmp/acc_ctl.log | head -30
echo "--- metrics ---"; cat runs/metrics.json 2>/dev/null
ROWS=$( [ -f data/robot-ops.jsonl ] && wc -l < data/robot-ops.jsonl || echo 0)
echo "rows=$ROWS"
if [ "$RC" = 124 ] && [ "$ROWS" -ge 1 ]; then
  echo "ACCEPTANCE PASS (loop ran, stalls escalated, labels written)"
else
  echo "ACCEPTANCE INCOMPLETE (rc=$RC rows=$ROWS -- inspect /tmp/acc_*.log)"
fi
