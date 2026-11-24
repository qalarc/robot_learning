// bus.js — Robot Bus protocol client (docs/PROTOCOL.md v1).
// Publishes sim.obs at obs_hz + sim.event; handles every sim.cmd; snapshot replies
// carry the request's id + to. High-rate topics are opt-in per protocol, so we publish
// but never subscribe sim.obs by default; we subscribe vision.hands for mocap control.
// `subscribe` (ctor) opts in to EXTRA high-rate topics (puppet mode: sim.obs) and
// handlers.onObs/onMsg receive sim.obs / every other non-cmd topic (train.metrics…).

export class BusClient {
  constructor({ url, handlers, subscribe }) {
    this.url = url || "ws://127.0.0.1:8890/ws";
    this.handlers = handlers; // { onCmd, onRoster, onHands, onObs, onMsg, onStatus }
    this.subscribe = Array.isArray(subscribe) ? subscribe : [];
    this.name = "armsmith-web";
    this.connected = false;
    this.sent = 0;
    this.recv = 0;
    this.recvCmds = 0;
    this.obsSent = 0;
    this.eventsSent = 0;
    this.repliesSent = 0;
    this.obsRecv = 0;
    this.metricsRecv = 0;
    this.obsHz = 30;
    this.record = false;
    this._obsAcc = 0;
    this._retry = 0;
    this._closed = false;
    this.connect();
  }

  connect() {
    if (this._closed) return;
    let ws;
    try { ws = new WebSocket(this.url); } catch (e) { this.scheduleRetry(); return; }
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this._retry = 0;
      this.send({ topic: "bus.hello", data: { name: "armsmith-web", roles: ["sim"], caps: ["ik", "rapier", "servo"] } });
      this.send({ topic: "bus.sub", data: { topics: [...new Set(["vision.hands", ...this.subscribe])] } });
      this.handlers.onStatus && this.handlers.onStatus(`bus: connected ${this.url}`);
    };
    ws.onmessage = (ev) => {
      this.recv++;
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (!msg || typeof msg !== "object") return;
      const topic = msg.topic || "";
      if (topic === "bus.roster") {
        const you = (msg.data || {}).you;
        if (you) this.name = you; // hub may rename us (armsmith-web#2) — always use this
        this.handlers.onRoster && this.handlers.onRoster(msg.data);
        return;
      }
      if (topic === "bus.sub_ack" || topic === "bus.join" || topic === "bus.leave") return;
      if (topic === "vision.hands") { this.handlers.onHands && this.handlers.onHands(msg.data || {}); return; }
      if (topic === "sim.obs") {
        this.obsRecv++;
        this.handlers.onObs && this.handlers.onObs(msg.data || {}, msg);
        return;
      }
      if (topic === "train.metrics") {
        this.metricsRecv++;
        this.handlers.onMetrics && this.handlers.onMetrics(msg.data || {}, msg);
        return;
      }
      if (topic === "sim.cmd") {
        this.recvCmds++;
        this.handlers.onCmd && this.handlers.onCmd(msg.data || {}, msg);
        return;
      }
      if (this.handlers.onMsg) { this.handlers.onMsg(msg); return; } // generic catch-all (must stay after cmd routes)
      if (topic === "log") { console.log("[bus log]", msg.data); return; }
    };
    ws.onclose = () => {
      this.connected = false;
      this.handlers.onStatus && this.handlers.onStatus("bus: disconnected — retrying");
      this.scheduleRetry();
    };
    ws.onerror = () => { try { ws.close(); } catch { /* ignore */ } };
  }

  scheduleRetry() {
    if (this._closed) return;
    this._retry++;
    const delay = Math.min(5000, 800 * this._retry);
    setTimeout(() => this.connect(), delay);
  }

  send(obj) {
    if (!this.ws || this.ws.readyState !== 1) return false;
    this.ws.send(JSON.stringify(obj));
    this.sent++;
    return true;
  }

  envelope(topic, data, to = undefined, id = undefined) {
    return { v: 1, id: id || crypto.randomUUID(), ts: Date.now() / 1000, src: this.name, topic, ...(to ? { to } : {}), data };
  }

  publishObs(obs, dt) {
    this._obsAcc += dt;
    const period = 1 / this.obsHz;
    if (this._obsAcc >= period) {
      this._obsAcc = this._obsAcc % period;
      if (this.send(this.envelope("sim.obs", obs))) this.obsSent++;
    }
  }

  publishEvent(data) { if (this.send(this.envelope("sim.event", data))) this.eventsSent++; }

  reply(request, data) {
    // request/reply: same id, to=request.src, topic = data.reply_to || "<src>.reply"
    const replyTo = (request.data && request.data.reply_to) || `${request.src || "anon"}.reply`;
    if (this.send(this.envelope(replyTo, data, request.src, request.id))) this.repliesSent++;
  }

  publishLog(level, msg) { this.send(this.envelope("log", { level, msg })); }

  close() { this._closed = true; try { this.ws && this.ws.close(); } catch { /* ignore */ } }
}
