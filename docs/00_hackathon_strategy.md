# 00 — Hackathon strategy

*Alloy × OpenAI Physical AI Hackathon · Sat 5 Dec 2026 · Sydney CBD · verified from the
[public event page](https://hackathonsaustralia.com.au/events/alloy-openai-physical-ai-hackathon)
on 24 Nov 2026. Challenge brief itself is secret until 10:00 on the day.*

## 0. The clock (act now)

| date | action |
|---|---|
| **Sun 29 Nov 23:59** | applications close. EVERY teammate applies individually (LinkedIn, work/study, robotics experience, hardware you'll bring, "future you want to create"). Tell them we bring an SO-101-class arm + a full sim stack. |
| Tue 1 Dec | acceptances + starter kit + Discord invite arrive |
| 24 Nov – 4 Dec | prep window (below) |
| 5 Dec 9:00 doors · 10:00 brief · **10:30–18:30 build** · 18:30 submit · 19:15 judge · 20:15 winners |

Prizes: 1st A$70k Cloudflare + A$21k OpenAI credits, 2nd A$14k, 3rd A$7k OpenAI credits.
Unlimited **Codex** for every builder on the day. Judged by OpenAI, Cloudflare, Alloy.

## 1. What they actually want (public framing, quote-level)

> "20 teams build robots that **learn from their own runs and fail less**, in simulation,
> on real hardware, or both."

The five-part loop: **run → capture → find the failure → fix → run again** — a "march of
nines" (a 99%-per-action robot finishes a 100-action task 37% of the time; 99.9% → 90%;
99.99% → 99%). Their exemplar: QT-Opt, 580k self-grasps, 78% → 96%. Simulation entries
are judged the same as hardware. Reliability > capability.

**Host lens:** Alloy's product is AI agents that debug robot fleets over captured data
(MCAP/ROS/Parquet-on-Iceberg; MCP servers for Codex/Claude). A project that *captures
everything, has agents find the failure, fixes, and shows the failure rate drop* speaks
their language natively. OpenAI's lens: Codex driving real engineering loops.

## 2. Our thesis (built, verified, in this repo)

**A live failure-recovery learning loop** — the five parts, mapped:

| loop part | ours | status |
|---|---|---|
| run | SO-101 arm in Three.js/Rapier sim (+ MuJoCo for training; real arm if the venue/BYO works) | built |
| capture | Robot Bus blackboard: every obs/cmd/event/stall/dossier → `runs/bus/*.jsonl` (+ LeRobot + MCAP export) | built |
| find the failure | deterministic stall detector (30 Hz) → **Laya S1** typed identification (1.35 s) → **GLM 4.7 S2** diagnosis (15–30 s, on stall only) | built, measured |
| fix | S2's bounded symbolic recovery plan (safety-shielded) + corrective demos for the policy | built |
| run again | re-run + `runs/metrics.json`: failure rate, escalation rate, time-to-recover — before/after = the "nines" table | built |

**The visible flywheel (the demo):** every successful S2 recovery is labelled into
`data/robot-ops.jsonl`; Laya fine-tunes (GUT protocol) so S1 catches that stall class
next time *without* S2. Escalation rate falls over the day. In parallel, ACT/SmolVLA
trains on the growing episode set so the base policy itself fails less. Two loops, one
log, both measured.

**Pitch line:** "Our robot fails, explains itself, fixes itself, and needs the big brain
less each time — here's the curve."

## 3. Prep schedule (24 Nov → 4 Dec)

Week 1 (by 30 Nov): everyone applies · repo cloned by all teammates, quickstart runs on
their laptops · MuJoCo bench numbers confirmed · hand teleop → sim works (MediaPipe) ·
fake-sim headless loop demo recorded (screencast as the day-0 fallback) · RGBmocap
reviewed for demo-capture on borrowed NVIDIA kit (optional).
Week 2 (by 4 Dec): a real Laya `robot-ops` checkpoint trained on a few hundred labelled
stalls from fake-sim + web-sim runs (gate: agreement ≥0.85, ECE ≤0.10; a FAIL is honest,
report it) · ACT trained on a first episode set (CPU-tiny or Kaggle T4) · MCAP export
path tested (`alloyrobotics/lerobot2mcap`) · pack list (below) · dry-run the full day
once, timed.

## 4. The day, hour by hour

| time | who | what |
|---|---|---|
| 9:00 | all | in, network, hub + sim up on the big machine, roster check |
| 10:00 | lead | read brief; map onto the five parts; freeze scenario choice by 10:20 |
| 10:30–12:00 | Codex A + dev | wire the brief's task as a `sim/armsmith_web` scenario; teleport demo collecting |
| | Codex B | eval harness: run-N-episodes script → failure taxonomy table |
| 12:00–14:00 | all | turn loop 1: collect 50–100 eps → train ACT (tiny) → eval → record delta |
| 14:00–16:30 | all | failure-driven loop: let stalls happen → S1/S2 recover → labels accumulate → Laya retrain (T4/Kaggle if venue net allows; else local) → escalation rate falls |
| 16:30–17:30 | stretch | MCAP export + Alloy-MCP-flavoured "agent investigates the fleet log" screen; hand teleop if hardware present |
| 17:30–18:30 | lead + Codex C | freeze code; metrics table "nines before/after"; 3-min demo video as backup; submit |
| 19:15 | lead | pitch: loop diagram → live demo → the falling curve → what breaks at scale |

Decision rules on the day: if venue Wi-Fi is bad → everything is local already (no CDN in
the web sim, CPU MuJoCo, local models) — we planned for this. If they provide RTX boxes
or credits → move ACT training there (doc 04/05 have the commands). If real hardware is
available (ours or theirs) → run the same bus against it; the protocol is hardware-neutral.

## 5. Risk register

| risk | mitigation |
|---|---|
| Brief demands something exotic (e.g. specific platform) | the bus protocol absorbs new sims; Codex's whole day-job |
| WebGL blocked on venue machines | fake_sim + MuJoCo path (headless) demos the loop identically |
| Laya fails GUT gate on the day | show untrained-vs-trained curve anyway; honesty is on-thesis |
| GLM S2 too slow under load | cap tokens (450), scripted fallback recovery, pre-warm model at 9:00 |
| Machine memory (Strix Halo, 124 GB, shared) | close Ollama extras; keep ≤2 models resident; `free -g` check in scripts |
| Dataset too small for ACT | that's fine: the *loop*, not the policy, is the entry; report learning curve honestly |

## 6. Judging rubric guess → our evidence

Likely judged on: loop-ness (we have 2), measurable improvement (metrics.json + nines
table), engineering quality (protocol, tests, shield), demo (live sim + falling curve),
story (march of nines). Keep `runs/metrics.json` authoritative from minute one.

## 7. Pack list

Laptops + chargers · the arm + PSU + cables (if BYO) · webcam (teleop) · phone hotspot ·
USB stick with the repo + vendored deps + a rendered demo video · this repo's SSH keys ·
powerboard · printed one-pager of the pitch.
