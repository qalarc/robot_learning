# The Event

**The Alloy x OpenAI Physical AI Hackathon — Sat 5 Dec 2026, Sydney CBD; one day, >A$100k in prizes, and the brief stays secret until 10:00 on the day.**

All facts below are verified from the public event page and research docs (see [docs/00_hackathon_strategy.md](../docs/00_hackathon_strategy.md), [docs/06_vla_landscape.md](../docs/06_vla_landscape.md), [README](../README.md)).

## The clock

| when | what |
|---|---|
| Sun 29 Nov 23:59 (AEDT) | applications close — EVERY teammate applies individually |
| Tue 1 Dec | acceptances + starter kit + Discord invite arrive |
| Sat 5 Dec 9:00 | doors open |
| 10:00 | challenge brief released (under wraps until then) |
| 10:30–18:30 | build window |
| 18:30 | submit |
| 19:15 | judging (winners 20:15) |

20 teams, up to 6 people each (teams ≤ 6). Prizes: **1st A$70k Cloudflare + A$21k OpenAI credits; 2nd A$14k; 3rd A$7k OpenAI credits**. Unlimited **Codex** for every builder on the day; judges/mentors from OpenAI, Cloudflare and Alloy Robotics. Bring-your-own hardware is welcome; **simulation entries are judged the same as hardware**.

## The brief (public framing)

> "20 teams build robots that **learn from their own runs and fail less**, in simulation, on real hardware, or both."

The organisers frame it as the five-part learning loop — **run → capture → find the failure → fix → run again** — a *"march of nines"*: a robot that is 99% reliable per action finishes a 100-action task 37% of the time; 99.9% → 90%; 99.99% → 99%. Their exemplar is QT-Opt (580k self-grasps, 78% → 96% success). The implicit rubric is **reliability over capability**.

## Why our design fits the hosts

**Alloy Robotics** (Sydney-founded, now expanding to the US; $8M seed at an $80M valuation led by Square Peg, Aug 2026) builds the "AI Robotics Engineer": agents that debug robot fleets over captured data — MCAP/ROS/Parquet on Iceberg, with MCP servers so Codex/Claude can query fleet data. Their GitHub org ships `lerobot2mcap` (GPL-3.0). A repo that captures everything, has agents find the failure, fixes, and shows the failure-rate drop speaks their language natively. **OpenAI's** lens: Codex driving real engineering loops (their cookbook documents iterative repair loops).

Judging is likely to reward loop-ness, measurable improvement (a before/after nines table), engineering quality, and a live demo of the falling curve — see [docs/00_hackathon_strategy.md §6](../docs/00_hackathon_strategy.md) for the rubric guess and [Operations Runbook](Operations-Runbook.md) for the day plan.

## Use + feasibility

**What these facts are for**: the clock drives the prep window and the day plan ([Operations Runbook](Operations-Runbook.md)); the "march of nines" framing is the pitch skeleton; Alloy's data-flywheel lens is why bus-log capture and (pending) MCAP export matter for judging. **On the one-day clock**: applications are a hard stop (29 Nov); unlimited Codex is the team's builder leverage from 10:30; the brief lands at 10:00 and the scenario choice is frozen by 10:20. **Feasibility**: pure information — risk is missing the deadline or misreading the brief; mitigation is that every loop component already exists and is measured (see [Architecture](Architecture.md)).

## See also

- [Architecture](Architecture.md) — what we built and why it maps onto the brief
- [Operations Runbook](Operations-Runbook.md) — hour-by-hour day plan
- [The Learning Loop](The-Learning-Loop.md) — the five parts, implemented
