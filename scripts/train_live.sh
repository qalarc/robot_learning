#!/usr/bin/env bash
# Train PPO live, watch it in the browser:
#   bash scripts/train_live.sh                 # 2.5M steps, reach env
#   bash scripts/train_live.sh 1000000 push    # custom steps / env
#
# Starts TWO processes: the trainer (flat-out, publishes train.metrics) and a
# follower showcase that hot-reloads best.zip and streams sim.obs at 30 Hz for
# the puppet viewer. They must be separate: a second thread inside the trainer
# corrupts SB3's rollout batches.
# View:   http://127.0.0.1:8892/   (nines + curves)   http://127.0.0.1:8891/?view=puppet
set -u
cd "$(dirname "$0")/.."
STEPS="${1:-2500000}"
ENV="${2:-reach}"
RUN="live_${ENV}_$(date +%H%M%S)"
PY=training/.venv/bin/python

curl -s -m 2 http://127.0.0.1:8890/health >/dev/null || bash sim/dashboard/serve.sh

mkdir -p runs/rl/$RUN
setsid nohup $PY training/train_rl.py --timesteps "$STEPS" --n-envs 32 \
    --eval-freq 25000 --eval-episodes 100 --run-id "$RUN" \
    > runs/rl/$RUN/train.log 2>&1 &
echo $! > runs/rl/$RUN/train.pid
sleep 25   # let the first eval write best.zip
setsid nohup $PY training/train_rl.py --env "$ENV" --demo runs/rl/$RUN \
    > runs/rl/$RUN/demo.log 2>&1 &
echo $! > runs/rl/$RUN/demo.pid

echo "training  : run_id=$RUN  log runs/rl/$RUN/train.log"
echo "showcase  : follows runs/rl/$RUN/best.zip  log runs/rl/$RUN/demo.log"
echo "dashboard : http://127.0.0.1:8892/"
echo "puppet    : http://127.0.0.1:8891/?view=puppet"
echo "stop      : kill \$(cat runs/rl/$RUN/train.pid runs/rl/$RUN/demo.pid)"
