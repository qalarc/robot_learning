// recorder.js — per-episode {step, t, obs, action} capture; last 20 episodes kept in
// memory; export as JSONL (the hub's runs/bus/*.jsonl stays the master dataset — this
// exporter gives per-episode action+obs pairs for training/).

export class Recorder {
  constructor() {
    this.enabled = false;
    this.episodes = [];   // [{ep, scenario, seed, outcome, rows:[...]}]
    this.current = null;
    this.maxEpisodes = 20;
  }

  start(ep, scenario, seed) {
    if (!this.enabled) return;
    this.current = { ep, scenario, seed, outcome: null, rows: [] };
  }

  row(step, t, obs, action) {
    if (!this.enabled || !this.current) return;
    this.current.rows.push({ step, t, obs, action });
  }

  end(ep, outcome) {
    if (!this.current) return;
    this.current.outcome = outcome;
    this.episodes.push(this.current);
    if (this.episodes.length > this.maxEpisodes) this.episodes.shift();
    this.current = null;
  }

  toEpisodeJsonl(idx) {
    const ep = this.episodes[idx];
    if (!ep) return "";
    const lines = [];
    for (const r of ep.rows) lines.push(JSON.stringify({ ep: ep.ep, scenario: ep.scenario, outcome: ep.outcome, ...r }));
    return lines.join("\n") + "\n";
  }

  toAllJsonl() {
    return this.episodes.map((_, i) => this.toEpisodeJsonl(i)).join("");
  }
}

export function downloadText(filename, text) {
  const blob = new Blob([text], { type: "application/x-ndjson" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
}
