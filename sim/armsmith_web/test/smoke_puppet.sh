#!/usr/bin/env bash
# test/smoke_puppet.sh — headless test for PUPPET MODE (?view=puppet).
#
#   a) starts the REAL hub, isolated in /tmp (state files never touch the repo)
#   b) starts test/fake_publisher-style synthetic sim: sim/dashboard/test/fake_publisher.py
#      (src "mujoco-demo", 30 Hz sim.obs with a moving 5-joint arm + rising train.metrics)
#   c) dumps the DOM of  ?view=puppet  under headless Chromium; the page must NOT step
#      its own arm — it can only know steps from the bus.
#   d) checks: #status shows `puppet step=` with step > 50 from the EXTERNAL publisher,
#      src=mujoco-demo in the DOM (both text and the status element's data-* attrs,
#      which survive the 2 s "waiting for sim…" watchdog), no error overlay.
#
# Prints PASS/FAIL with diagnostics; kills everything it started. Repo files untouched.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WEB="$ROOT/sim/armsmith_web"
PY="$ROOT/sim/py/.venv/bin/python"
CHROME="/usr/bin/chromium"
OUT="/tmp/rl_t1b/smoke_puppet"
ISOHUB="$OUT/isohub/agents"
mkdir -p "$OUT" "$ISOHUB"
cp "$ROOT/agents/hub.py" "$ISOHUB/hub.py"   # relocated = isolated runs/ state

WPORT=""
HUB_PORT=""
WPID=""
HUB_PID=""
PUB_PID=""

cleanup() {
  [ -n "$PUB_PID" ] && kill "$PUB_PID" 2>/dev/null
  [ -n "$WPID" ] && kill "$WPID" 2>/dev/null
  [ -n "$HUB_PID" ] && kill "$HUB_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

echo "== puppet-mode smoke =="

# ---- 1) isolated hub on 8893 (8890-8892 + 8894-8898 are other standing services) --
( cd "$ISOHUB" && exec "$PY" hub.py --port 8893 ) > "$OUT/hub.log" 2>&1 &
HUB_PID=$!
for _ in $(seq 1 50); do
  sleep 0.2
  HUB_PORT="$(cat "$OUT/isohub/runs/bus.port" 2>/dev/null || true)"
  [ -n "$HUB_PORT" ] && break
done
if [ -z "$HUB_PORT" ]; then echo "FAIL: hub did not start"; tail -5 "$OUT/hub.log"; exit 1; fi
if curl -s -m 1 "http://127.0.0.1:$HUB_PORT/health" 2>/dev/null | grep -q '"ok"'; then
  echo "hub: up on port $HUB_PORT"
else
  echo "FAIL: hub port $HUB_PORT unhealthy"; tail -5 "$OUT/hub.log"; exit 1
fi

# ---- 2) fake external simulator (30 Hz sim.obs + train.metrics) ----------------
export ROBOT_BUS_URL="ws://127.0.0.1:$HUB_PORT/ws"
"$PY" "$ROOT/sim/dashboard/test/fake_publisher.py" --url "$ROBOT_BUS_URL" --start-step 400 \
  > "$OUT/publisher.log" 2>&1 &
PUB_PID=$!
JOINED=0
for _ in $(seq 1 60); do
  if curl -s -m 1 "http://127.0.0.1:$HUB_PORT/roster" 2>/dev/null | grep -q 'mujoco-demo'; then JOINED=1; break; fi
  sleep 0.25
done
if [ "$JOINED" -eq 1 ]; then echo "fake sim: publishing as mujoco-demo"; else
  echo "FAIL: fake_publisher never joined the bus"; tail -5 "$OUT/publisher.log"; exit 1
fi

# ---- 3) http server for the sim dir --------------------------------------------
for p in $(seq 8930 8949); do
  if ! curl -s -m 1 "http://127.0.0.1:$p/" >/dev/null 2>&1; then WPORT="$p"; break; fi
done
[ -z "$WPORT" ] && { echo "FAIL: no free http port 8930-8949"; exit 1; }
( cd "$WEB" && exec python3 -m http.server "$WPORT" --bind 127.0.0.1 ) > "$OUT/http.log" 2>&1 &
WPID=$!
sleep 0.7
echo "http: serving $WEB on port $WPORT"

# ---- 4) headless chromium over the puppet page ---------------------------------
URL="http://127.0.0.1:$WPORT/?view=puppet&hub=ws://127.0.0.1:$HUB_PORT/ws"
# fresh profile per run — a reused profile serves CACHED src/*.js and would test
# yesterday's code (bit us once: identical DOM byte count to the baseline run)
CHROME_PROFILE="$(mktemp -d "$OUT/chrome-profile.XXXXXX")"
echo "chrome: $URL"
"$CHROME" --headless=new --disable-gpu --enable-unsafe-swiftshader --use-angle=swiftshader \
  --window-size=1280,800 --virtual-time-budget=15000 --no-first-run --no-default-browser-check \
  --user-data-dir="$CHROME_PROFILE" \
  --dump-dom "$URL" > "$OUT/dom.html" 2> "$OUT/chrome.err"
CHROME_RC=$?
echo "chrome: rc=$CHROME_RC dom=$(wc -c < "$OUT/dom.html") bytes"

# ---- 5) checks ------------------------------------------------------------------
FAIL=0
# authoritative: status element data-attrs, written on every obs, untouched by the watchdog
DSTEP="$(grep -o 'data-step="[0-9]*"' "$OUT/dom.html" | tail -1 | cut -d'"' -f2)"
DSRC="$(grep -o 'data-src="[^"]*"' "$OUT/dom.html" | tail -1 | cut -d'"' -f2)"
if [ -n "$DSTEP" ] && [ "$DSTEP" -gt 50 ] 2>/dev/null; then
  echo "external step: PASS (data-step=$DSTEP)"
else
  echo "external step: FAIL (data-step='${DSTEP:-none}')"; FAIL=1
fi
if [ "$DSRC" = "mujoco-demo" ]; then
  echo "external src:  PASS (data-src=$DSRC)"
else
  echo "external src:  FAIL (data-src='${DSRC:-none}')"; FAIL=1
fi
# spec text: `puppet step=` with step > 50 in the status line, plus the HUD source line
STEP="$(grep -o 'puppet step=[0-9]*' "$OUT/dom.html" | tail -1 | cut -d= -f2)"
if [ -n "$STEP" ] && [ "$STEP" -gt 50 ] 2>/dev/null; then
  echo "status text:   PASS (puppet step=$STEP)"
else
  echo "status text:   FAIL (puppet step='${STEP:-none}')"; FAIL=1
fi
if grep -q 'source: mujoco-demo · reach' "$OUT/dom.html"; then
  echo "hud label:     PASS (source: mujoco-demo · reach …)"
else
  echo "hud label:     FAIL — expected 'source: mujoco-demo · reach …'"; grep -o 'source:[^<]*' "$OUT/dom.html" | head -2; FAIL=1
fi
if grep -qE 'errText">\[(boot|error|promise|event|puppet)\]' "$OUT/dom.html"; then
  echo "error overlay: FAIL — runtime error captured:"
  grep -oE 'errText">[^<]*' "$OUT/dom.html" | head -5
  FAIL=1
else
  echo "error overlay: PASS (empty)"
fi

echo "== diagnostics =="
echo "--- chrome.stderr (tail) ---"; tail -6 "$OUT/chrome.err" || true
echo "--- publisher.log (tail) ---"; tail -3 "$OUT/publisher.log" || true
echo "--- #status/#busstat/puppetSrc in DOM ---"
grep -oE 'id="(status|busstat|puppetSrc|puppetMetrics|puppetObs)"[^>]*>[^<]*' "$OUT/dom.html" | head -8

if [ "$FAIL" -eq 0 ]; then
  echo "PUPPET SMOKE PASS — external sim mirrored headless: step=$STEP src=$DSRC"
  exit 0
else
  echo "PUPPET SMOKE FAIL — see diagnostics above ($OUT/)"
  exit 1
fi
