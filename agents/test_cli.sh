#!/usr/bin/env bash
# test_cli.sh -- end-to-end test of agents/cli.py + agents/fake_sim.py + agents/replay.py
# against a scratch hub on port 8896. Starts the hub and the fake sim, runs every
# CLI subcommand asserting exit 0, prints a PASS/FAIL summary, and kills only the
# processes it started (trap on EXIT).
#
#   bash agents/test_cli.sh
#
# Isolation: ROBOT_BUS_URL pins everything to the scratch hub so the repo's
# runs/bus.port file and any production hub are left alone. The scratch hub still
# writes its own log under runs/bus/ (that is the hub's designed behaviour).
set -u
cd "$(dirname "$0")/.."

PY="sim/py/.venv/bin/python"
PORT=8896
BUS_URL="ws://127.0.0.1:${PORT}/ws"
export ROBOT_BUS_URL="$BUS_URL"
export ROBOT_SIM_NAME="fake-sim"
OUT=/tmp/rl_b2
mkdir -p "$OUT"

HUB_PID=""
SIM_PID=""
cleanup() {
    [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null
    [ -n "$HUB_PID" ] && kill "$HUB_PID" 2>/dev/null
    [ -n "$SIM_PID" ] && wait "$SIM_PID" 2>/dev/null
    [ -n "$HUB_PID" ] && wait "$HUB_PID" 2>/dev/null
}
trap cleanup EXIT

PASS=0
FAIL=0
run() { # run <case-name> <cmd...>  ; asserts exit 0
    local name="$1"; shift
    if "$@" >"$OUT/last.out" 2>"$OUT/last.err"; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name  (exit $?)"
        sed 's/^/        err: /' "$OUT/last.err" | head -5
        head -c 300 "$OUT/last.out" | sed 's/^/        out: /'
        echo
        FAIL=$((FAIL + 1))
    fi
}
run_fails() { # run_fails <case-name> <cmd...>  ; asserts exit != 0
    local name="$1"; shift
    if "$@" >"$OUT/last.out" 2>"$OUT/last.err"; then
        echo "  [FAIL] $name  (expected nonzero exit, got 0)"
        FAIL=$((FAIL + 1))
    else
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    fi
}

echo "== starting hub on port $PORT =="
"$PY" agents/hub.py --port "$PORT" >"$OUT/hub.log" 2>&1 &
HUB_PID=$!
for i in $(seq 1 30); do
    if "$PY" -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:${PORT}/health',timeout=1)" 2>/dev/null; then
        break
    fi
    sleep 0.3
done
echo "== starting fake-sim =="
"$PY" agents/fake_sim.py --url "$BUS_URL" --hz 30 --ep-len 3000 --seed 1234 >"$OUT/sim.log" 2>&1 &
SIM_PID=$!
sleep 1.5

CLI=("$PY" agents/cli.py --url "$BUS_URL" --to fake-sim)

echo "== cli subcommands =="
run roster      "${CLI[@]}" roster
run ping        "${CLI[@]}" cmd --json '{"cmd":"ping"}'
run obs         "${CLI[@]}" obs --n 2 --hz 30 --timeout 8
run ee          "${CLI[@]}" ee --x 0.30 --y 0.05 --z 0.10 --grip 1.0
run ee-relative "${CLI[@]}" ee --x 0 --y 0 --z 0.05 --relative
run joint       "${CLI[@]}" joint --q 0.1 0.2 0.3 0.4 0.5 0.6
run grip        "${CLI[@]}" grip 0.3
run scenario    "${CLI[@]}" scenario pick_place
run reset       "${CLI[@]}" reset --seed 7
run mode        "${CLI[@]}" mode ik
run snapshot    bash -c "\"$PY\" agents/cli.py --url \"$BUS_URL\" --to fake-sim snapshot --cam wrist --out $OUT/frame.jpg && test -s $OUT/frame.jpg"
run stall       "${CLI[@]}" stall
run tail        "${CLI[@]}" tail --topic sim.event --n 1 --timeout 6
run pretty      "${CLI[@]}" --pretty obs --n 1 --hz 30 --timeout 8

echo "== replay =="
NEWEST_LOG="$(ls -t runs/bus/*.jsonl 2>/dev/null | head -1)"
if [ -n "$NEWEST_LOG" ]; then
    run replay-dry   "$PY" agents/replay.py "$NEWEST_LOG" --dry-run
    run replay-csv   "$PY" agents/replay.py "$NEWEST_LOG" --export-csv "$OUT/actions.csv"
    test -s "$OUT/actions.csv" && { echo "  [PASS] csv-written"; PASS=$((PASS + 1)); } || { echo "  [FAIL] csv-written"; FAIL=$((FAIL + 1)); }
else
    echo "  [FAIL] replay (no hub log found under runs/bus/)"
    FAIL=$((FAIL + 1))
fi

echo "== demo (scripted reach-grasp-lift, ~5 s) =="
run demo        "${CLI[@]}" demo --seed 7 --timeout 8

echo "== flag-position + bad-target regressions =="
# flags BEFORE the subcommand must reach the subparser (argparse SUPPRESS fix);
# run with ROBOT_SIM_NAME unset so only --to can resolve the target.
run to-before-sub env -u ROBOT_SIM_NAME "$PY" agents/cli.py --url "$BUS_URL" \
    --to fake-sim --timeout 5 cmd --json '{"cmd":"ping"}'
run to-after-sub  env -u ROBOT_SIM_NAME "$PY" agents/cli.py cmd --json '{"cmd":"ping"}' \
    --url "$BUS_URL" --to fake-sim --timeout 5
# a typo'd target must fail loudly (hub's "no connected client" warn -> exit 1)
run_fails bad-target env -u ROBOT_SIM_NAME "$PY" agents/cli.py --url "$BUS_URL" \
    --to no-such-sim ee --x 0.2 --y 0 --z 0.1

echo "== fault injection smoke =="
FAULT_LOG="$OUT/fault.log"
"$PY" agents/fake_sim.py --url "$BUS_URL" --name fake-sim-fault --hz 30 --ep-len 3000 --fault ik_residual --seed 1234 >"$FAULT_LOG" 2>&1 &
FAULT_PID=$!
sleep 1.5
run fault-stall "${CLI[@]}" --to fake-sim-fault cmd --json '{"cmd":"ee","args":{"pos":[0.3,0.1,0.05]}}'
sleep 3   # let the stall detector fire (30 steps no progress)
run fault-saw-stall bash -c "\"$PY\" -c\"
import json,urllib.request
r=json.load(urllib.request.urlopen('http://127.0.0.1:${PORT}/recent'))
obs=[e['data'] for e in r.get('sim.obs',[])]
stalls=[o.get('stall',{}).get('stalled') for o in obs]
sys_=any(stalls); print('stalled seen:',sys_); exit(0 if sys_ else 1)
\""
kill "$FAULT_PID" 2>/dev/null; wait "$FAULT_PID" 2>/dev/null

TOTAL=$((PASS + FAIL))
echo
echo "CLI TEST: $PASS/$TOTAL passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
