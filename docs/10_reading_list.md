# 10 — Reading List for the Learning-Loops Hackathon

*Prepared 2026-11-24. Ordered by priority for a 1-day event with an SO-101-style arm and unlimited Codex. All items verified to exist at the linked source on this date; "est. read" = focused reading time, not skim.*

---

## 🔴 Must read before the day (the 5)

1. **LeRobot — project README & policy docs** — https://github.com/huggingface/lerobot
   *Why:* the one library that implements ACT, Diffusion, VQ-BeT, HIL-SERL, SmolVLA, π0 family, GR00T and X-VLA against one dataset format; SO-101 is first-class supported hardware. *Est. read: 25 min (README + the policy/hardware doc links).*
2. **SmolVLA: Efficient VLA trained on community data (HF blog, Jun 2025)** — https://huggingface.co/blog/smolvla
   *Why:* the only 450M VLA that runs on CPU and trains on a consumer GPU, with SO-101 fine-tune commands and an async-inference stack — our realistic day-of VLA. *Est. read: 20 min.*
3. **ACT: Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware (Zhao et al.)** — https://arxiv.org/abs/2304.13705
   *Why:* 80–90% success on precise tasks from 10 minutes of demos on exactly our class of arm; the day's highest-yield training loop. *Est. read: 45 min (abstract + method + chunking/temporal-ensemble sections).*
4. **π\*0.6: a VLA That Learns From Experience / RECAP (Physical Intelligence)** — https://pi.website/blog/pistar06 and paper https://arxiv.org/abs/2511.14759
   *Why:* the canonical 2025 "learning loop" — demos → human corrections → RL from autonomous experience — and the mental model judges will expect for the theme. *Est. read: 30 min (blog) / 75 min (paper).*
5. **HIL-SERL — Precise Robotic Manipulation via Human-in-the-Loop RL (project page)** — https://hil-serl.github.io
   *Why:* proves a real-robot policy can go from demos to near-perfect in ~1 hour using BC + interventions + RL — the fastest real "loop" in the literature; implemented in LeRobot. *Est. read: 20 min (page + video).*

## High priority

6. **SERL: Sample-Efficient Robotic RL (repo)** — https://github.com/rail-berkeley/serl (paper: https://arxiv.org/abs/2401.16013)
   *Why:* its README literally prescribes online human interventions via SpaceMouse — the cheapest intervention loop to run day-of. *Est. read: 15 min.*
7. **HG-DAgger: Interactive Imitation Learning with Human Experts (Kelly et al.)** — https://arxiv.org/abs/1810.02890
   *Why:* intervention-when-human-wants beats expert-labelling; this is the loop our operator will actually run. *Est. read: 20 min.*
8. **DAgger: A Reduction of Imitation Learning to No-Regret Online Learning (Ross et al.)** — https://arxiv.org/abs/1011.0686
   *Why:* the two-page idea (learn on the learner's own state distribution) that explains *why* intervention loops fix BC. *Est. read: 15 min.*
9. **RT-H: Action Hierarchies Using Language (Belkhale et al.)** — https://arxiv.org/abs/2403.01823 (site: https://rt-hierarchy.github.io)
   *Why:* a middle "language-motion" layer that can be *corrected in language* mid-run — a template for Laya as the intervention arbiter. *Est. read: 25 min.*
10. **Hi Robot: Open-Ended Instruction Following with Hierarchical VLA Models (PI/Stanford, ICML 2025)** — https://arxiv.org/abs/2502.19417 (https://www.pi.website/research/hirobot)
    *Why:* slow reasoner handles complex prompts + live feedback, fast policy executes — the System 1/2 shape to demo. *Est. read: 30 min.*
11. **Helix: a VLA for Generalist Humanoid Control (Figure)** — https://www.figure.ai/news/helix
    *Why:* the cleanest System 1/System 2 writeup (7B @7–9 Hz + 80M @200 Hz) plus the "% task completion" action for self-termination — trivially portable to a typed head. *Est. read: 20 min.*
12. **ConRFT: Reinforced Fine-tuning of VLAs via Consistency Policy** — https://arxiv.org/abs/2502.05450
    *Why:* shows a VLA reaching ~96% success in 45–90 min of online fine-tuning with human-supervised exploration — sets a realistic "loop converges" bar. *Est. read: 30 min.*
13. **LeRobot robot-learning tutorial (free hands-on course)** — https://huggingface.co/spaces/lerobot/robot-learning-tutorial
    *Why:* the shortest path from unboxing to a trained SO-101 policy; pre-read this and you skip setup pain on the day. *Est. read: 30 min (follow along later).*

## Background / context

14. **openpi README (π0 / π0-FAST / π0.5)** — https://github.com/Physical-Intelligence/openpi
    *Why:* exact GPU requirements (>8GB inference, >22.5GB LoRA) and the websocket policy-server pattern for cloud inference. *Est. read: 15 min.*
15. **OpenVLA repo & OFT paper (Kim, Finn, Liang 2025)** — https://github.com/openvla/openvla ; https://arxiv.org/abs/2502.19645
    *Why:* the 7B reference point, its data-collection best practices (~100 demos, 5–10 Hz, no pauses), and OFT's parallel-decoding fix. *Est. read: README 15 min / paper 45 min.*
16. **GR00T N1.7 README (NVIDIA)** — https://github.com/NVIDIA/Isaac-GR00T
    *Why:* where closed-ecosystem VLA + synthetic data is heading; relative-EEF action space is a good default for us too. *Est. read: 20 min.*
17. **X-VLA: Soft-Prompted Transformer (THU Air Dream, ICLR 2026)** — https://github.com/2toinf/X-VLA (paper: https://arxiv.org/abs/2510.10274)
    *Why:* 0.9B cross-embodiment model, LeRobot-native, LoRA adapters released — proof small+open VLAs keep converging. *Est. read: 20 min.*
18. **MiniVLA: A Better VLA with a Smaller Footprint (Stanford SAIL blog)** — https://ai.stanford.edu/blog/minivla (repo: https://github.com/Stanford-ILIAD/openvla-mini)
    *Why:* 7B→1B distillation with VQ action tokens; thinking about size/speed trade-offs. *Est. read: 15 min.*
19. **RLDG: Robotic Generalist Policy Distillation via RL** — https://arxiv.org/abs/2412.09858 (https://generalist-distillation.github.io)
    *Why:* use RL only where it matters, then BC the rollouts into a generalist — a loop you can half-run in one day (BC on scripted-success runs). *Est. read: 25 min.*
20. **VQ-BeT: Behavior Generation with Latent Actions (Park et al., ICML 2024)** — https://arxiv.org/abs/2403.03181 (code: https://github.com/jayLEE0301/vq_bet_official)
    *Why:* action decision-tokens — the conceptual cousin of Laya's typed choices inside a policy. *Est. read: 30 min.*
21. **Diffusion Policy (Chi et al., RSS 2023)** — https://arxiv.org/abs/2303.04137
    *Why:* why multimodal action distributions matter; read the receding-horizon + action-chunking setup. *Est. read: 35 min.*
22. **Domain Randomisation (Tobin et al., 2017)** — https://arxiv.org/abs/1710.06437
    *Why:* the canonical sim-to-real trick, worth one line in any sim pitch. *Est. read: 15 min.*
23. **GR00T-Mimic & GR00T-Dreams synthetic-data blog (NVIDIA)** — https://developer.nvidia.com/blog/enhance-robot-learning-with-synthetic-trajectory-data-generated-by-world-foundation-models/
    *Why:* the industrial-strength version of the data flywheel theme; compare with our "log every run" flywheel. *Est. read: 15 min.*
24. **Build iterative repair loops with Codex (OpenAI cookbook)** — https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex
    *Why:* Codex is unlimited on the day — this is OpenAI's own pattern for act→validate→repair loops, ready to map onto robot logs. *Est. read: 15 min.* `[URL seen via search listing, not fetched — verify it opens]`
25. **Gemini Robotics 1.5 blog (Google DeepMind)** — https://deepmind.google/blog/gemini-robotics-15-brings-ai-agents-into-the-physical-world
    *Why:* the agentic ER-orchestrator/VLA-executor split and motion transfer — the closed frontier's answer to the same theme. *Est. read: 12 min.*

---

**Not included (could not verify existence):** any paper titled "Mitigating the Human-Robot Interaction Partition Problem"; "RoboReflect"; an MIT paper titled simply "Interventions"; the hackathon's official registration page; OpenAI "GPT-6/6.2 Astra robot-control" benchmark claims (only low-authority aggregator posts).
