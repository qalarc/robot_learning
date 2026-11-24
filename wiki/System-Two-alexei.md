# System Two alexei

**alexei is the local GLM reasoner that wakes only on gated stalls — it diagnoses and returns a bounded symbolic recovery plan which a deterministic safety shield clamps before anything reaches the arm.**

## Model lineage

`glm-4.7-flash-abl:alexei-v3` via Ollama (`:11434`) — an **abliterated** GLM-4.7-Flash base with the alexei-v3 character fine-tune on top. The default model comes from `robot_ops.schema.json` (`s2.model_default`); `scripts/acceptance.sh` defaults to the resident base `glm-4.7-flash-abl:32k` ("same size") if `MODEL` isn't set. Swap via `--model` on `control/glm_s2.py --probe` / `control/stall_controller.py` or the `MODEL` env. **The model is abliterated: assume zero self-restraint.** That is why the shield is non-negotiable — all bounds live in code, never in the model.

## Dossier anatomy

`build_dossier` assembles a compact, line-oriented briefing: `STATE:` (the frozen template string) · `S1 TYPED VERDICT (calibrated):` (Laya's top probabilities per head) · `HISTORY:` (compact JSON) · `RECENT EVENTS:` (last 6) · `AVAILABLE SKILLS:` (the signature list) · and the output contract — minified JSON on one line: `{"diagnosis" (≤2 sentences), "root_cause" (one of the schema labels), "plan" (≤4 steps of {skill,args,why, why ≤10 words}), "abort_if", "confidence"}`. Request: temperature 0.3, `num_predict` 450, keep-alive 2h.

## The safety shield

`validate_plan` whitelists skills against `SKILL_SIGNATURES`, clamps every arg (workspace box x 0.05–0.30, y ±0.18, z 0.02–0.25 m; e.g. `backoff.metres` ≤ 0.05, `wiggle.amp` ≤ 0.01), drops unknown skills/args, caps plan length, and salvages truncated JSON (`loads_lenient`). Measured live: it silently cleaned `approach_from(from=side, target=-1.0)`. Empty plans fall back to the scripted bounded recovery (backoff + move-to-hover). Steps are paced 0.4 s apart and the takeover is announced on `ctl.recovery`.

## Skill vocabulary

`backoff, regrasp, move_ee, set_gripper, approach_from, wiggle, switch_camera, replan_scenario, request_teleop, abort` — symbolic only; **the model never emits joint angles**.

## Measured latencies (this machine)

| condition | number |
|---|---|
| uncontended decode | ~46 tok/s; 255-token plan ≈ 5.5 s; prompt eval < 1.5 s |
| blocking `ask()` under 3-model GTT contention | 12–38 s (~14 tok/s) — the "15–30 s" headline |
| streaming `ask_stream()` | ttfa **2.05 s mean** (1.79–2.22 warm); full plan 5.27 s mean |
| cold model load | ~50–70 s; 17–82 s seen when another session evicts the 18 GB weights |

## Use + feasibility

**FOR**: novel-failure diagnosis and multi-step recovery — nothing else in the stack reasons. **On the one-day clock**: pre-warm with `ollama run glm-4.7-flash-abl:alexei-v3 --keepalive 2h` at 9:00 (it's 18 GB); use streaming so recoveries act in ~2 s; keep ≤2 models resident (~40–60 GB of the shared 124 GB; check `free -g`). **Risk**: memory pressure and contention are the real failure modes — scripted fallback covers both, and the shield covers the model itself.

## See also

- [The Learning Loop](The-Learning-Loop.md) — L3 in the ladder, streaming details
- [System One Laya](System-One-Laya.md) — the student of every plan
- [FAQ](FAQ.md) — what the latency numbers really mean
