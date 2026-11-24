#!/usr/bin/env bash
# serve.sh — bring up the local demo stack for the hackathon mission-control:
#
#   bash sim/dashboard/serve.sh          # ensure hub :8890, sim :8891, dashboard :8892
#   bash sim/dashboard/serve.sh --stop   # kill ONLY the pids recorded in runs/dashboard.pids
#
# Idempotent: anything already answering on its port (GET /health or /) is left alone —
# servers are only started when the port is quiet, and only then recorded in the pidfile.
# The hub is started with sim/py/.venv (websockets dep); static servers use system
# python3 -m http.server (stdlib only). Live demo recipe: sim/dashboard/README.md.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/sim/py/.venv/bin/python"
WEB_DIR="$ROOT/sim/armsmith_web"
DASH_DIR="$ROOT/sim/dashboard"
BUS_PORT=8890
WEB_PORT=8891
DASH_PORT=8892
PIDFILE="$ROOT/runs/dashboard.pids"
LOGDIR="$ROOT/runs"
mkdir -p "$LOGDIR"

port_up() { curl -s -m 1 "http://127.0.0.1:$1$2" >/dev/null 2>&1; }

record_pid() { echo "$1 $2" >> "$PIDFILE"; }

if [ "${1:-}" = "--stop" ]; then
  if [ -f "$PIDFILE" ]; then
    while read -r name pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null && echo "stopped $name (pid $pid)" || echo "could not stop $name (pid $pid)"
      fi
    done < "$PIDFILE"
    rm -f "$PIDFILE"
  else
    echo "nothing to stop ($PIDFILE missing)"
  fi
  exit 0
fi

echo "== robot_learning demo stack =="

# ---- 1) Robot Bus hub on :$BUS_PORT ------------------------------------------
if curl -s -m 1 "http://127.0.0.1:$BUS_PORT/health" 2>/dev/null | grep -q '"ok"'; then
  echo "hub       : already up on $BUS_PORT (not started by us — --stop won't kill it)"
else
  ( cd "$ROOT" && setsid nohup "$PY" agents/hub.py --port "$BUS_PORT" >> "$LOGDIR/dashboard-hub.log" 2>&1 & echo $! > /tmp/rl_dash_hub.pid )
  rm -f /tmp/rl_dash_hub.pid
  for _ in $(seq 1 40); do
    curl -s -m 1 "http://127.0.0.1:$BUS_PORT/health" 2>/dev/null | grep -q '"ok"' && break
    sleep 0.25
  done
  if curl -s -m 1 "http://127.0.0.1:$BUS_PORT/health" 2>/dev/null | grep -q '"ok"'; then
    # $! may be the bash wrapper of the backgrounded compound, not the hub python —
    # resolve the real hub pid so --stop actually stops it.
    record_pid "hub-$BUS_PORT" "$(pgrep -n -f "agents/hub.py --port $BUS_PORT")"
    echo "hub       : started on $BUS_PORT (log: runs/dashboard-hub.log)"
  else
    echo "hub       : WARN — did not answer /health on $BUS_PORT; check runs/dashboard-hub.log"
    echo "            (if another hub walked to a nearby port, see runs/bus.port)"
  fi
fi

# ---- 2) three.js sim dir on :$WEB_PORT (puppet view lives here) ---------------
if port_up "$WEB_PORT" /; then
  echo "sim       : already serving on $WEB_PORT (not started by us)"
else
  ( setsid nohup python3 -m http.server "$WEB_PORT" --bind 127.0.0.1 --directory "$WEB_DIR" >> "$LOGDIR/dashboard-web.log" 2>&1 & echo $! > /tmp/rl_dash_web.pid )
  rm -f /tmp/rl_dash_web.pid
  sleep 0.4
  if port_up "$WEB_PORT" /; then
    record_pid "sim-$WEB_PORT" "$(pgrep -n -f "http.server $WEB_PORT --bind 127.0.0.1 --directory $WEB_DIR")"
    echo "sim       : serving $WEB_DIR on $WEB_PORT"
  else
    echo "sim       : WARN — port $WEB_PORT did not come up"
  fi
fi

# ---- 3) dashboard on :$DASH_PORT ----------------------------------------------
if port_up "$DASH_PORT" /; then
  echo "dashboard : already serving on $DASH_PORT (not started by us)"
else
  ( setsid nohup python3 -m http.server "$DASH_PORT" --bind 127.0.0.1 --directory "$DASH_DIR" >> "$LOGDIR/dashboard-dash.log" 2>&1 & echo $! > /tmp/rl_dash_dash.pid )
  rm -f /tmp/rl_dash_dash.pid
  sleep 0.4
  if port_up "$DASH_PORT" /; then
    record_pid "dash-$DASH_PORT" "$(pgrep -n -f "http.server $DASH_PORT --bind 127.0.0.1 --directory $DASH_DIR")"
    echo "dashboard : serving $DASH_DIR on $DASH_PORT"
  else
    echo "dashboard : WARN — port $DASH_PORT did not come up"
  fi
fi

echo ""
echo "  mission control : http://127.0.0.1:$DASH_PORT/"
echo "  puppet viewer   : http://127.0.0.1:$WEB_PORT/?view=puppet"
echo "  local sim       : http://127.0.0.1:$WEB_PORT/          (drive it yourself)"
echo "  robot bus       : ws://127.0.0.1:$BUS_PORT/ws           (http /health /roster)"
echo ""
echo "  feed it fake training data:"
echo "  sim/py/.venv/bin/python sim/dashboard/test/fake_publisher.py"
