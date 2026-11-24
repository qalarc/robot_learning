#!/usr/bin/env bash
# test/smoke_dashboard.sh — headless test for the mission-control dashboard.
#
#   a) starts the REAL hub, isolated in /tmp
#   b) starts sim/dashboard/test/fake_publisher.py (rising success curve,
#      baseline_failure_rate 0.97, src "mujoco-demo")
#   c) serves sim/dashboard/ on a test port, dumps its DOM under headless Chromium
#   d) checks: the nines element holds a number (from -log10(failure_rate) of the
#      fake train.metrics), the run header is filled, and no "bus offline" banner.
#
# Prints PASS/FAIL with diagnostics; kills everything it started.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DASH="$ROOT/sim/dashboard"
PY="$ROOT/sim/py/.venv/bin/python"
CHROME="/usr/bin/chromium"
OUT="/tmp/rl_t1b/smoke_dashboard"
ISOHUB="$OUT/isohub/agents"
mkdir -p "$OUT" "$ISOHUB"
cp "$ROOT/agents/hub.py" "$ISOHUB/hub.py"

DPORT=""
HUB_PORT=""
DPID=""
HUB_PID=""
PUB_PID=""

cleanup() {
  [ -n "$PUB_PID" ] && kill "$PUB_PID" 2>/dev/null
  [ -n "$DPID" ] && kill "$DPID" 2>/dev/null
  [ -n "$HUB_PID" ] && kill "$HUB_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

echo "== dashboard smoke =="

# ---- 1) isolated hub on 8898 ---------------------------------------------------
( cd "$ISOHUB" && exec "$PY" hub.py --port 8898 ) > "$OUT/hub.log" 2>&1 &
HUB_PID=$!
for _ in $(seq 1 50); do
  sleep 0.2
  HUB_PORT="$(cat "$OUT/isohub/runs/bus.port" 2>/dev/null || true)"
  [ -n "$HUB_PORT" ] && break
done
if [ -z "$HUB_PORT" ]; then echo "FAIL: hub did not start"; tail -5 "$OUT/hub.log"; exit 1; fi
curl -s -m 1 "http://127.0.0.1:$HUB_PORT/health" 2>/dev/null | grep -q '"ok"' \
  && echo "hub: up on port $HUB_PORT" || { echo "FAIL: hub unhealthy"; exit 1; }

# ---- 2) fake trainer ------------------------------------------------------------
export ROBOT_BUS_URL="ws://127.0.0.1:$HUB_PORT/ws"
"$PY" "$ROOT/sim/dashboard/test/fake_publisher.py" --url "$ROBOT_BUS_URL" \
  > "$OUT/publisher.log" 2>&1 &
PUB_PID=$!
for _ in $(seq 1 60); do
  curl -s -m 1 "http://127.0.0.1:$HUB_PORT/roster" 2>/dev/null | grep -q 'mujoco-demo' && break
  sleep 0.25
done
curl -s -m 1 "http://127.0.0.1:$HUB_PORT/roster" 2>/dev/null | grep -q 'mujoco-demo' \
  && echo "fake trainer: publishing" || { echo "FAIL: fake_publisher not on bus"; tail -5 "$OUT/publisher.log"; exit 1; }
sleep 1.5   # let the first train.metrics + roster settle before chromium starts

# ---- 3) serve the dashboard dir on a test port ----------------------------------
for p in $(seq 8950 8969); do
  if ! curl -s -m 1 "http://127.0.0.1:$p/" >/dev/null 2>&1; then DPORT="$p"; break; fi
done
[ -z "$DPORT" ] && { echo "FAIL: no free http port 8950-8969"; exit 1; }
( cd "$DASH" && exec python3 -m http.server "$DPORT" --bind 127.0.0.1 ) > "$OUT/http.log" 2>&1 &
DPID=$!
sleep 0.7
echo "http: serving $DASH on port $DPORT"

# ---- 4) headless chromium --------------------------------------------------------
URL="http://127.0.0.1:$DPORT/?hub=ws://127.0.0.1:$HUB_PORT/ws"
echo "chrome: $URL"
"$CHROME" --headless=new --disable-gpu --enable-unsafe-swiftshader \
  --window-size=1440,900 --virtual-time-budget=15000 --no-first-run --no-default-browser-check \
  --user-data-dir="$OUT/chrome-profile" \
  --dump-dom "$URL" > "$OUT/dom.html" 2> "$OUT/chrome.err"
CHROME_RC=$?
echo "chrome: rc=$CHROME_RC dom=$(wc -c < "$OUT/dom.html") bytes"

# ---- 5) checks -------------------------------------------------------------------
FAIL=0
NINES="$(grep -o 'id="nines" class="nines">[-0-9.]*' "$OUT/dom.html" | tail -1 | sed 's/.*>//')"
case "$NINES" in
  ''|'—') echo "nines number: FAIL (got '${NINES:-nothing}')"; FAIL=1 ;;
  *) echo "nines number: PASS (nines=$NINES)" ;;
esac
BASE="$(grep -o 'id="ninesBase" class="nines">[-0-9.]*' "$OUT/dom.html" | tail -1 | sed 's/.*>//')"
case "$BASE" in
  ''|'—') echo "baseline nines: FAIL (got '${BASE:-nothing}')"; FAIL=1 ;;
  *) echo "baseline nines: PASS (baseline=$BASE)" ;;
esac
RUNF="$(grep -o 'id="runField">[^<]*' "$OUT/dom.html" | tail -1 | sed 's/.*>//')"
if [ -n "$RUNF" ] && [ "$RUNF" != "—" ]; then
  echo "run header:    PASS (run=$RUNF)"
else
  echo "run header:    FAIL (run='${RUNF:-none}')"; FAIL=1
fi
if grep -q 'id="busBanner" class="banner ok"' "$OUT/dom.html"; then
  echo "bus banner:    PASS (online)"
else
  echo "bus banner:    FAIL — not online:"; grep -o 'id="busBanner"[^>]*>[^<]*' "$OUT/dom.html" | head -2; FAIL=1
fi
if grep -q 'mujoco-demo' "$OUT/dom.html"; then
  echo "roster:        PASS (mujoco-demo listed)"
else
  echo "roster:        FAIL (no mujoco-demo)"; FAIL=1
fi

echo "== diagnostics =="
echo "--- chrome.stderr (tail) ---"; tail -6 "$OUT/chrome.err" || true
echo "--- header fields in DOM ---"
grep -oE 'id="(runField|policyField|stageField|fpsField|tsField|elapsedField)"[^>]*>[^<]*' "$OUT/dom.html" | head -8

if [ "$FAIL" -eq 0 ]; then
  echo "DASHBOARD SMOKE PASS — nines=$NINES baseline=$BASE run=$RUNF"
  exit 0
else
  echo "DASHBOARD SMOKE FAIL — see diagnostics above ($OUT/)"
  exit 1
fi
