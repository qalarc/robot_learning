#!/usr/bin/env bash
# test/smoke_meshes.sh — asserts the sim loaded the REAL SO-101 STL meshes headless.
#
#   a) serves this dir over http://127.0.0.1:<http_port>   (STLs must be fetchable)
#   b) starts the REAL hub in /tmp scratch (state files never touch the repo);
#      starts at 8893 — 8890-8892 belong to the standing dev bus/sim/Laya processes
#   c) dumps the DOM of  ?autotest=1&meshcheck=1  under Chromium + SwiftShader
#   d) asserts:
#        - `meshes=stl` in the DOM  (the STL skin swapped in, not the capsule fallback)
#        - `meshcheck PASS`         (FK acceptance on 5 targets, ±15 mm, WITH meshes on)
#        - the http server actually served .stl files with 200s (proves the load path)
#        - the usual no-error-overlay check
#
# Prints PASS/FAIL with diagnostics; kills everything it started. Repo files untouched.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WEB="$ROOT/sim/armsmith_web"
PY="$ROOT/sim/py/.venv/bin/python"
CHROME="/usr/bin/chromium"
OUT="/tmp/rl_b4/smoke_meshes"
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

echo "== ARMSMITH web mesh smoke (real STL skin) =="

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

# ---- 3) headless chromium over the page ---------------------------------------
URL="http://127.0.0.1:$HTTP_PORT/?autotest=1&meshcheck=1&hub=ws://127.0.0.1:$HUB_PORT/ws"
# fresh profile per run — a reused profile serves CACHED src/*.js and would test
# yesterday's code (bit us once: identical DOM byte count to the baseline run)
CHROME_PROFILE="$(mktemp -d "$OUT/chrome-profile.XXXXXX")"
echo "chrome: $URL"
"$CHROME" --headless=new --disable-gpu --enable-unsafe-swiftshader --use-angle=swiftshader \
  --window-size=1280,800 --virtual-time-budget=25000 --no-first-run --no-default-browser-check \
  --user-data-dir="$CHROME_PROFILE" \
  --dump-dom "$URL" > "$OUT/dom.html" 2> "$OUT/chrome.err"
CHROME_RC=$?
echo "chrome: rc=$CHROME_RC dom=$(wc -c < "$OUT/dom.html") bytes"

# ---- 4) checks -----------------------------------------------------------------
FAIL=0

# the STL fetches settle without timers (allSettled semantics), so `meshes=` in the
# DOM is the deterministic verdict of which visual path is live.
MESH_PATH="$(grep -o 'meshes=\(stl\|capsule\)' "$OUT/dom.html" | tail -1)"
if [ "$MESH_PATH" = "meshes=stl" ]; then
  echo "real meshes: PASS (meshes=stl in DOM)"
else
  echo "real meshes: FAIL (got '${MESH_PATH:-none}', need meshes=stl)"
  grep -o 'meshes=[a-z]*' "$OUT/dom.html" | head -3
  FAIL=1
fi

MESHCHECK="$(grep -o 'meshcheck \(PASS\|FAIL\)[^"<]*' "$OUT/dom.html" | tail -1)"
case "$MESHCHECK" in
  meshcheck\ PASS*) echo "meshcheck (FK ±15mm with meshes): PASS ($MESHCHECK)" ;;
  "")               echo "meshcheck (FK ±15mm with meshes): FAIL (no line in DOM)"; FAIL=1 ;;
  *)                echo "meshcheck (FK ±15mm with meshes): FAIL ($MESHCHECK)"; FAIL=1 ;;
esac

# prove the STLs were really fetched: the page's own verdict could only say stl if
# every placement's fetch+parse succeeded, but cross-check the server log anyway.
STL_SERVED="$(grep -E 'assets/so101/.*\.stl' "$OUT/http.log" 2>/dev/null | grep -c ' 200 ' || true)"
if [ "${STL_SERVED:-0}" -ge 13 ]; then
  echo "stl served over http: PASS ($STL_SERVED .stl files, all 200)"
else
  echo "stl served over http: FAIL (only ${STL_SERVED:-0} .stl 200s in http.log)"
  grep 'assets/so101' "$OUT/http.log" | head -5
  FAIL=1
fi

if grep -qE 'errText">\[(boot|error|promise|event)\]' "$OUT/dom.html"; then
  echo "error overlay: FAIL — runtime error captured:"
  grep -oE 'errText">[^<]*' "$OUT/dom.html" | head -5
  FAIL=1
else
  echo "error overlay: PASS (empty)"
fi

echo "== diagnostics =="
echo "--- chrome.stderr (tail) ---"; tail -6 "$OUT/chrome.err" || true
echo "--- http 4xx/5xx ---"; grep -E '" 4[0-9][0-9] |" 5[0-9][0-9] ' "$OUT/http.log" | head -5 || echo none
echo "--- #status/#busstat in DOM ---"
grep -oE 'id="(status|busstat)"[^>]*>[^<]*' "$OUT/dom.html" | head -4

if [ "$FAIL" -eq 0 ]; then
  echo "MESH SMOKE PASS — real SO-101 STL skin loaded headless ($MESH_PATH, $MESHCHECK)"
  exit 0
else
  echo "MESH SMOKE FAIL — see diagnostics above ($OUT/)"
  exit 1
fi
