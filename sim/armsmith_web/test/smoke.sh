#!/usr/bin/env bash
# test/smoke.sh — headless Chromium smoke test for the ARMSMITH web sim.
#
#   a) serves this dir over http://127.0.0.1:<http_port>
#   b) starts the REAL hub (agents/hub.py — copied to scratch so its state files
#      (runs/bus.*) land in /tmp and never clobber a concurrently-running hub;
#      starts at 8893 — 8890-8892 are the standing dev bus/sim/Laya ports — and if
#      that is busy the hub walks upward; we read the real port it chose)
#   c) dumps the DOM of  ?autotest=1  under Chromium + SwiftShader (no GPU)
#   d) checks: #status shows `running step=` with step > 50; #busstat shows obs SENT
#      to the hub; no error-overlay text; a Python probe's ping gets a pong while
#      the page is alive on the bus; ?meshcheck=1 reports `meshcheck PASS` (FK lands
#      within ±15 mm on 5 probe targets) and which visual path loaded
#      (`meshes=stl|capsule` — capsule here is a VALID pass: STL fetch failures
#      silently fall back). smoke_meshes.sh is the one that asserts meshes=stl.
#
# Prints PASS/FAIL with diagnostics; kills everything it started. Repo files untouched.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WEB="$ROOT/sim/armsmith_web"
PY="$ROOT/sim/py/.venv/bin/python"
CHROME="/usr/bin/chromium"
OUT="/tmp/rl_b1/smoke"
ISOHUB="$OUT/isohub/agents"
mkdir -p "$OUT" "$ISOHUB"
cp "$ROOT/agents/hub.py" "$ISOHUB/hub.py"   # relocated = isolated runs/ state

HTTP_PORT=""
HUB_PORT=""
HTTP_PID=""
HUB_PID=""

cleanup() {
  [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null
  [ -n "$HUB_PID" ]  && kill "$HUB_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

echo "== ARMSMITH web smoke =="

# ---- 1) the real hub, isolated state ----------------------------------------
( cd "$ISOHUB" && exec "$PY" hub.py --port 8893 ) > "$OUT/hub.log" 2>&1 &
HUB_PID=$!
for i in $(seq 1 50); do
  sleep 0.2
  HUB_PORT="$(cat "$OUT/isohub/runs/bus.port" 2>/dev/null || true)"
  [ -n "$HUB_PORT" ] && break
done
if [ -z "$HUB_PORT" ]; then echo "FAIL: hub did not start"; tail -5 "$OUT/hub.log"; exit 1; fi
if curl -s -m 1 "http://127.0.0.1:$HUB_PORT/health" 2>/dev/null | grep -q '"ok"'; then
  echo "hub: up on port $HUB_PORT (pid $HUB_PID)"
else
  echo "FAIL: hub port $HUB_PORT unhealthy"; tail -5 "$OUT/hub.log"; exit 1
fi

# ---- 2) http server for the sim dir ------------------------------------------
for p in $(seq 8910 8929); do
  if ! curl -s -m 1 "http://127.0.0.1:$p/" >/dev/null 2>&1; then HTTP_PORT="$p"; break; fi
done
[ -z "$HTTP_PORT" ] && { echo "FAIL: no free http port 8910-8929"; exit 1; }
( cd "$WEB" && exec python3 -m http.server "$HTTP_PORT" --bind 127.0.0.1 ) > "$OUT/http.log" 2>&1 &
HTTP_PID=$!
sleep 0.7
echo "http: serving $WEB on port $HTTP_PORT"

# ---- 3) headless chromium over the page (runs in bg; probe rides along) ------
URL="http://127.0.0.1:$HTTP_PORT/?autotest=1&meshcheck=1&hub=ws://127.0.0.1:$HUB_PORT/ws"
# fresh profile per run — a reused profile serves CACHED src/*.js and would test
# yesterday's code (bit us once: identical DOM byte count to the baseline run)
CHROME_PROFILE="$(mktemp -d "$OUT/chrome-profile.XXXXXX")"
echo "chrome: $URL"
"$CHROME" --headless=new --disable-gpu --enable-unsafe-swiftshader --use-angle=swiftshader \
  --window-size=1280,800 --virtual-time-budget=20000 --no-first-run --no-default-browser-check \
  --user-data-dir="$CHROME_PROFILE" \
  --dump-dom "$URL" > "$OUT/dom.html" 2> "$OUT/chrome.err" &
CHROME_PID=$!

# wait until the page has joined the bus (hub /roster lists clients), then poke it live
SIM_ON_BUS=0
for i in $(seq 1 160); do
  if curl -s -m 1 "http://127.0.0.1:$HUB_PORT/roster" 2>/dev/null | grep -q 'armsmith-web'; then
    SIM_ON_BUS=1; break
  fi
  kill -0 $CHROME_PID 2>/dev/null || break
  sleep 0.25
done
if [ "$SIM_ON_BUS" -eq 1 ]; then
  echo "page joined the bus (waited ~$((i / 4))s)"
else
  echo "WARN: page never joined the bus"
fi

# ---- 4) python probe: ping/pong + obs over the real bus ----------------------
"$PY" "$WEB/test/sanity_pub.py" "ws://127.0.0.1:$HUB_PORT/ws" | tee "$OUT/sanity.txt"
SANITY_RC=${PIPESTATUS[0]}

wait $CHROME_PID
CHROME_RC=$?
echo "chrome: rc=$CHROME_RC dom=$(wc -c < "$OUT/dom.html") bytes"

# ---- 5) checks on the DOM -----------------------------------------------------
FAIL=0
STEP="$(grep -o 'running step=[0-9]*' "$OUT/dom.html" | tail -1 | cut -d= -f2)"
if [ -n "$STEP" ] && [ "$STEP" -gt 50 ] 2>/dev/null; then
  echo "status ticking: PASS (running step=$STEP)"
else
  echo "status ticking: FAIL (step='${STEP:-none}')"; FAIL=1
fi

OBS_SENT="$(grep -o 'obs [0-9]*' "$OUT/dom.html" | tail -1 | cut -d' ' -f2)"
if [ -n "$OBS_SENT" ] && [ "$OBS_SENT" -gt 0 ] 2>/dev/null && grep -q 'busstat' "$OUT/dom.html"; then
  echo "bus obs sent: PASS (obs=$OBS_SENT)"
else
  echo "bus obs sent: FAIL (obs='${OBS_SENT:-none}')"; FAIL=1
fi

if grep -q 'sent=' "$OUT/dom.html"; then
  echo "busstat line: PASS"
else
  echo "busstat line: FAIL (no sent= in DOM)"; FAIL=1
fi

if grep -qE 'errText">\[(boot|error|promise|event)\]' "$OUT/dom.html"; then
  echo "error overlay: FAIL — runtime error captured:"
  grep -oE 'errText">[^<]*' "$OUT/dom.html" | head -5
  FAIL=1
else
  echo "error overlay: PASS (empty)"
fi

if [ "$SANITY_RC" -eq 0 ]; then
  echo "bus probe (ping/pong + obs): PASS"
else
  echo "bus probe (ping/pong + obs): FAIL"; FAIL=1
fi

# meshcheck: FK acceptance probe (?meshcheck=1 writes PASS/FAIL into #status).
# Both visual paths are accepted here; smoke_meshes.sh asserts the STL path.
MESHCHECK="$(grep -o 'meshcheck \(PASS\|FAIL\)[^"<]*' "$OUT/dom.html" | tail -1)"
case "$MESHCHECK" in
  meshcheck\ PASS*)
    echo "meshcheck (FK ±15mm, 5 targets): PASS ($MESHCHECK)"
    MESH_PATH="$(grep -o 'meshes=\(stl\|capsule\)' "$OUT/dom.html" | tail -1)"
    echo "visual path: $MESH_PATH (both accepted by this test)"
    ;;
  "")
    echo "meshcheck (FK ±15mm, 5 targets): FAIL (no meshcheck line in DOM)"; FAIL=1 ;;
  *)
    echo "meshcheck (FK ±15mm, 5 targets): FAIL ($MESHCHECK)"; FAIL=1 ;;
esac

echo "== diagnostics =="
echo "--- chrome.stderr (tail) ---"; tail -6 "$OUT/chrome.err" || true
echo "--- hub.log (tail) ---";        tail -3 "$OUT/hub.log" 2>/dev/null || true
echo "--- http 4xx/5xx ---";           grep -E '" 4[0-9][0-9] |" 5[0-9][0-9] ' "$OUT/http.log" | head -5 || echo none
echo "--- #status/#busstat in DOM ---"
grep -oE 'id="(status|busstat)"[^>]*>[^<]*' "$OUT/dom.html" | head -4

if [ "$FAIL" -eq 0 ]; then
  echo "SMOKE PASS — sim runs headless: step=$STEP obs_sent=$OBS_SENT sanity_ok=yes"
  exit 0
else
  echo "SMOKE FAIL — see diagnostics above ($OUT/)"
  exit 1
fi
