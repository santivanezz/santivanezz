"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => SergioBrainPlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian3 = require("obsidian");

// src/api.ts
var import_obsidian = require("obsidian");
var DEFAULT_SETTINGS = {
  engineUrl: "http://127.0.0.1:8765",
  token: "",
  notifyOnChange: true,
  briefingOnStartup: false,
  useLlm: true,
  recallOnStartup: true
};
var BrainClient = class {
  constructor(settings) {
    this.settings = settings;
  }
  headers() {
    const h = { "Content-Type": "application/json" };
    const t = this.settings().token;
    if (t) h["X-Brain-Token"] = t;
    return h;
  }
  url(path, params) {
    const base = this.settings().engineUrl.replace(/\/$/, "");
    const qs = params ? Object.entries(params).filter(([, v]) => v !== void 0 && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&") : "";
    return base + path + (qs ? "?" + qs : "");
  }
  async get(path, params) {
    var _a;
    const r = await (0, import_obsidian.requestUrl)({ url: this.url(path, params), method: "GET", headers: this.headers(), throw: false });
    if (r.status >= 400) throw new Error(`Engine ${r.status}: ${(_a = r.text) == null ? void 0 : _a.slice(0, 200)}`);
    return r.json;
  }
  async post(path, body) {
    var _a;
    const r = await (0, import_obsidian.requestUrl)({ url: this.url(path), method: "POST", headers: this.headers(), body: JSON.stringify(body), throw: false });
    if (r.status >= 400) throw new Error(`Engine ${r.status}: ${(_a = r.text) == null ? void 0 : _a.slice(0, 200)}`);
    return r.json;
  }
  health() {
    return this.get("/health");
  }
  ask(q, useLlm) {
    return this.post("/ask", { q, use_llm: useLlm });
  }
  search(q, k = 12) {
    return this.get("/search", { q, k });
  }
  related(path) {
    return this.get("/related", { path });
  }
  capture(text, extra = {}) {
    return this.post("/capture", { text, ...extra });
  }
  notify(path, deleted = false) {
    return this.post("/notify", { path, deleted });
  }
  recall() {
    return this.get("/recall");
  }
  briefing() {
    return this.get("/briefing");
  }
  dashboard() {
    return this.get("/dashboard");
  }
  health_note() {
    return this.get("/brain-health", { write: 1 });
  }
  review(period) {
    return this.get("/review", { period });
  }
  why(q) {
    return this.get("/why", { q });
  }
  changed(path, q) {
    return this.get("/changed", { path, q });
  }
  feedback(target_type, target_id, verdict) {
    return this.post("/feedback", { target_type, target_id, verdict });
  }
  reindex() {
    return this.post("/reindex", {});
  }
  backup() {
    return this.post("/backup", { kind: "snapshot" });
  }
  timeline(days = 14) {
    return this.get("/timeline", { days });
  }
  tasks() {
    return this.get("/tasks");
  }
  suggestions() {
    return this.get("/suggestions");
  }
  contradictions() {
    return this.get("/contradictions");
  }
};

// src/views.ts
var import_obsidian2 = require("obsidian");
var VIEW_TYPE = "sergio-brain-panel";
function openNote(app, path) {
  const file = app.vault.getAbstractFileByPath(path);
  if (file) app.workspace.openLinkText(path, "", false);
  else new import_obsidian2.Notice("Nota no encontrada: " + path);
}
var BrainPanelView = class extends import_obsidian2.ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
  }
  getViewType() {
    return VIEW_TYPE;
  }
  getDisplayText() {
    return "Sergio Brain";
  }
  getIcon() {
    return "brain";
  }
  async onOpen() {
    await this.refresh();
  }
  async refresh() {
    var _a, _b, _c, _d, _e;
    const root = this.contentEl;
    root.empty();
    root.addClass("sb-panel");
    const file = this.app.workspace.getActiveFile();
    root.createEl("h3", { text: "SERGIO BRAIN" });
    if (!file) {
      root.createEl("p", { text: "Abre una nota para ver su memoria.", cls: "sb-muted" });
      return;
    }
    root.createEl("p", { text: file.basename, cls: "sb-muted" });
    let data;
    try {
      data = await this.plugin.client.related(file.path);
    } catch (e) {
      root.createEl("p", { text: "Motor no disponible: " + e.message, cls: "sb-status-bad" });
      return;
    }
    if (data.message) root.createEl("p", { text: data.message, cls: "sb-muted" });
    root.createEl("h4", { text: "Related notes" });
    if (!((_a = data.related) == null ? void 0 : _a.length)) root.createEl("p", { text: "(ninguna todav\xEDa)", cls: "sb-muted" });
    for (const r of (_b = data.related) != null ? _b : []) {
      const d = root.createDiv({ cls: "sb-item" });
      const a = d.createEl("a", { text: r.title });
      a.onclick = () => openNote(this.app, r.path);
      d.createSpan({ text: String(r.score), cls: "sb-score" });
      d.createDiv({ text: ((_c = r.reasons) != null ? _c : []).join(" \xB7 "), cls: "sb-muted" });
    }
    root.createEl("h4", { text: "Memories" });
    for (const m of (_d = data.memories) != null ? _d : []) {
      const d = root.createDiv({ cls: "sb-item" });
      d.createSpan({ text: m.memory_type, cls: "sb-badge" });
      d.createSpan({ text: m.content.slice(0, 140) });
      const fb = d.createSpan({ cls: "sb-fb" });
      for (const v of ["IMPORTANT", "NOT_USEFUL", "WRONG"]) {
        const b = fb.createEl("button", { text: v === "IMPORTANT" ? "\u2605" : v === "NOT_USEFUL" ? "\u2715" : "!", title: v });
        b.onclick = async () => {
          await this.plugin.client.feedback("memory", m.id, v);
          new import_obsidian2.Notice("Feedback: " + v);
        };
      }
      if (m.importance_reason) d.createDiv({ text: m.importance_reason, cls: "sb-muted" });
    }
    root.createEl("h4", { text: "Entities" });
    root.createEl("p", { text: ((_e = data.entities) != null ? _e : []).slice(0, 20).map((e) => `${e.name} (${e.entity_type})`).join(", ") || "(ninguna)", cls: "sb-muted" });
  }
};
var OmnibarModal = class extends import_obsidian2.Modal {
  constructor(app, plugin, initial = "") {
    super(app);
    this.mode = "ask";
    this.plugin = plugin;
    this.initial = initial;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Ask Sergio Brain" });
    const tabs = contentEl.createDiv({ cls: "sb-tabs" });
    const modes = [["ask", "Ask"], ["search", "Search"], ["why", "Why do I know this?"], ["changed", "What changed?"]];
    const buttons = [];
    for (const [m, label] of modes) {
      const b = tabs.createEl("button", { text: label });
      b.onclick = () => {
        this.mode = m;
        buttons.forEach((x) => x.removeClass("mod-cta"));
        b.addClass("mod-cta");
      };
      if (m === this.mode) b.addClass("mod-cta");
      buttons.push(b);
    }
    const input = contentEl.createEl("textarea", { placeholder: "\xBFQu\xE9 tengo pendiente? \xBFQu\xE9 s\xE9 sobre Erlang C? \xBFPor qu\xE9 decid\xED X?" });
    input.value = this.initial;
    const out = contentEl.createDiv();
    const run = async () => {
      const q = input.value.trim();
      if (!q) return;
      out.empty();
      out.createEl("p", { text: "Pensando\u2026", cls: "sb-muted" });
      try {
        if (this.mode === "ask") await this.renderAsk(out, await this.plugin.client.ask(q, this.plugin.settings.useLlm));
        else if (this.mode === "search") this.renderSearch(out, await this.plugin.client.search(q));
        else if (this.mode === "why") this.renderWhy(out, await this.plugin.client.why(q));
        else this.renderChanged(out, await this.plugin.client.changed(void 0, q));
      } catch (e) {
        out.empty();
        out.createEl("p", { text: "Error: " + e.message, cls: "sb-status-bad" });
      }
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        void run();
      }
    });
    const go = contentEl.createEl("button", { text: "Preguntar (Enter)", cls: "mod-cta" });
    go.onclick = () => void run();
    setTimeout(() => input.focus(), 30);
    if (this.initial) void run();
  }
  link(el, title, path) {
    const a = el.createEl("a", { text: title });
    a.onclick = () => {
      openNote(this.app, path);
      this.close();
    };
  }
  async renderAsk(out, res) {
    var _a, _b, _c, _d, _e, _f, _g;
    out.empty();
    out.createDiv({ text: `${res.evidence} \xB7 ${res.mode} \xB7 ${res.duration_ms} ms`, cls: "sb-muted" });
    const ans = out.createDiv({ cls: "sb-answer" });
    await import_obsidian2.MarkdownRenderer.render(this.app, (_a = res.answer) != null ? _a : "", ans, "", new import_obsidian2.Component());
    if (res.llm_error) out.createDiv({ text: "LLM no usado: " + res.llm_error, cls: "sb-muted" });
    const fb = out.createDiv({ cls: "sb-fb" });
    fb.createSpan({ text: "\xBF\xDAtil? " });
    for (const v of ["USEFUL", "NOT_USEFUL", "WRONG"]) {
      const b = fb.createEl("button", { text: v });
      b.onclick = async () => {
        await this.plugin.client.feedback("answer", res.question, v);
        new import_obsidian2.Notice("Gracias, feedback guardado");
      };
    }
    const sec = (title) => {
      out.createEl("h4", { text: title });
      return out.createDiv({ cls: "sb-sources" });
    };
    const s = sec("Sources");
    for (const src of (_b = res.sources) != null ? _b : []) {
      const d = s.createDiv({ cls: "sb-item" });
      this.link(d, src.title, src.path);
      d.createSpan({ text: String(src.score), cls: "sb-score" });
      d.createDiv({ text: src.snippet, cls: "sb-muted" });
    }
    if ((_c = res.related) == null ? void 0 : _c.length) {
      const r = sec("Related notes");
      for (const x of res.related) {
        const d = r.createDiv({ cls: "sb-item" });
        this.link(d, x.title, x.path);
        d.createDiv({ text: ((_d = x.reasons) != null ? _d : []).join(" \xB7 "), cls: "sb-muted" });
      }
    }
    if ((_e = res.entities) == null ? void 0 : _e.length) sec("Entities").createEl("p", { text: res.entities.map((e) => `${e.name} (${e.type})`).join(", ") });
    if ((_f = res.projects) == null ? void 0 : _f.length) sec("Projects").createEl("p", { text: res.projects.map((p) => p.name).join(", ") });
    if ((_g = res.timeline) == null ? void 0 : _g.length) {
      const t = sec("Timeline");
      for (const it of res.timeline) t.createDiv({ text: `${it.date} \xB7 ${it.kind} \xB7 ${it.title}`, cls: "sb-item" });
    }
    if (res.why) {
      const w = sec("Provenance");
      w.createEl("pre", { text: res.why.summary });
    }
  }
  renderSearch(out, res) {
    var _a, _b, _c;
    out.empty();
    for (const r of (_a = res.results) != null ? _a : []) {
      const d = out.createDiv({ cls: "sb-item" });
      this.link(d, r.title, r.path);
      d.createSpan({ text: String(r.score), cls: "sb-score" });
      d.createDiv({ text: (_b = r.snippet) == null ? void 0 : _b.slice(0, 200), cls: "sb-muted" });
    }
    if (!((_c = res.results) == null ? void 0 : _c.length)) out.createEl("p", { text: "Not enough evidence in Boveda Sergio.", cls: "sb-muted" });
  }
  renderWhy(out, res) {
    var _a;
    out.empty();
    out.createEl("pre", { text: res.summary });
    for (const n of (_a = res.chain) != null ? _a : []) {
      const d = out.createDiv({ cls: "sb-item" });
      this.link(d, n.title, n.path);
      d.createDiv({ text: n.evidence, cls: "sb-muted" });
    }
  }
  renderChanged(out, res) {
    var _a, _b, _c;
    out.empty();
    for (const d of (_a = res.documents) != null ? _a : []) {
      const el = out.createDiv({ cls: "sb-item" });
      if (d.document) this.link(el, d.document.title, d.document.path);
      el.createDiv({ text: d.message, cls: "sb-muted" });
      if (d.diff) el.createEl("pre", { text: d.diff.slice(0, 4e3) });
    }
    for (const s of (_b = res.superseded) != null ? _b : []) out.createDiv({ text: `SUPERSEDED \xB7 ${s.subject}: \xAB${s.statement_a}\xBB \u2192 \xAB${s.statement_b}\xBB`, cls: "sb-item" });
    if (!((_c = res.documents) == null ? void 0 : _c.length)) out.createEl("p", { text: "Sin cambios registrados para esa consulta.", cls: "sb-muted" });
  }
  onClose() {
    this.contentEl.empty();
  }
};
var CaptureModal = class extends import_obsidian2.Modal {
  constructor(app, plugin, text) {
    super(app);
    this.plugin = plugin;
    this.text = text;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Capture to Inbox" });
    const title = contentEl.createEl("input", { type: "text", placeholder: "T\xEDtulo (opcional)" });
    title.style.width = "100%";
    const url = contentEl.createEl("input", { type: "text", placeholder: "URL de origen (opcional)" });
    url.style.width = "100%";
    const ta = contentEl.createEl("textarea");
    ta.value = this.text;
    ta.style.minHeight = "160px";
    const force = contentEl.createEl("label");
    const cb = force.createEl("input", { type: "checkbox" });
    force.createSpan({ text: " Guardar aunque se clasifique como trivial" });
    const b = contentEl.createEl("button", { text: "Capturar", cls: "mod-cta" });
    b.onclick = async () => {
      var _a, _b, _c;
      try {
        const res = await this.plugin.client.capture(ta.value, { title: title.value || void 0, url: url.value || void 0, capture_type: "hotkey", force: cb.checked, source: { source_type: "obsidian", capture_method: "plugin", source_note: (_a = this.app.workspace.getActiveFile()) == null ? void 0 : _a.path } });
        new import_obsidian2.Notice((_b = res.message) != null ? _b : res.saved ? "Guardado" : "No guardado");
        if ((_c = res.existing_candidates) == null ? void 0 : _c.length) new import_obsidian2.Notice("Posiblemente ya existe: " + res.existing_candidates.map((x) => x.title).join(", "), 8e3);
        this.close();
      } catch (e) {
        new import_obsidian2.Notice("Error: " + e.message);
      }
    };
  }
  onClose() {
    this.contentEl.empty();
  }
};
var RecallModal = class extends import_obsidian2.Modal {
  constructor(app, plugin, items) {
    super(app);
    this.plugin = plugin;
    this.items = items;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Remember" });
    if (!this.items.length) contentEl.createEl("p", { text: "Nada que recordar hoy.", cls: "sb-muted" });
    for (const it of this.items) {
      const d = contentEl.createDiv({ cls: "sb-item" });
      d.createSpan({ text: it.kind, cls: "sb-badge" });
      d.createSpan({ text: it.message });
      if (it.path) {
        const a = d.createEl("a", { text: " abrir" });
        a.onclick = () => {
          openNote(this.app, it.path);
          this.close();
        };
      }
      const fb = d.createSpan({ cls: "sb-fb" });
      for (const v of ["USEFUL", "IGNORE"]) {
        const b = fb.createEl("button", { text: v });
        b.onclick = async () => {
          const [type, id] = String(it.key).split(":");
          await this.plugin.client.feedback(type === "suggestion" ? "suggestion" : type === "task" || type === "decision" ? "memory" : type, id != null ? id : it.key, v);
          b.setText("\u2713");
        };
      }
    }
  }
  onClose() {
    this.contentEl.empty();
  }
};

// src/main.ts
var SergioBrainPlugin = class extends import_obsidian3.Plugin {
  constructor() {
    super(...arguments);
    this.settings = DEFAULT_SETTINGS;
    this.pending = /* @__PURE__ */ new Map();
  }
  async onload() {
    await this.loadSettings();
    this.client = new BrainClient(() => this.settings);
    this.addSettingTab(new BrainSettingTab(this.app, this));
    this.registerView(VIEW_TYPE, (leaf) => new BrainPanelView(leaf, this));
    this.statusEl = this.addStatusBarItem();
    this.addRibbonIcon("brain", "Sergio Brain", () => this.openOmnibar());
    this.addCommand({ id: "ask", name: "Ask Sergio Brain (Omnibar)", hotkeys: [{ modifiers: ["Ctrl", "Shift"], key: "b" }], callback: () => this.openOmnibar() });
    this.addCommand({ id: "ask-selection", name: "Ask about selection", editorCallback: (editor) => this.openOmnibar(editor.getSelection()) });
    this.addCommand({ id: "capture", name: "Capture selection / clipboard to Inbox", hotkeys: [{ modifiers: ["Ctrl", "Alt"], key: "s" }], callback: () => void this.capture() });
    this.addCommand({ id: "search", name: "Search (hybrid)", callback: () => {
      const m = new OmnibarModal(this.app, this);
      m.mode = "search";
      m.open();
    } });
    this.addCommand({ id: "related", name: "Related notes panel", callback: () => void this.openPanel() });
    this.addCommand({ id: "remember", name: "Remember (active recall)", callback: () => void this.remember() });
    this.addCommand({ id: "why", name: "Why do I know this?", editorCallback: (editor) => {
      const m = new OmnibarModal(this.app, this, editor.getSelection());
      m.mode = "why";
      m.open();
    } });
    this.addCommand({ id: "changed", name: "What changed in this note?", callback: () => void this.whatChangedCurrent() });
    this.addCommand({ id: "briefing", name: "Morning briefing (GOOD MORNING SERGIO)", callback: () => this.generated(() => this.client.briefing(), "Morning briefing generado") });
    this.addCommand({ id: "dashboard", name: "Open SERGIO BRAIN command center", callback: () => this.generated(() => this.client.dashboard(), "Dashboard actualizado", "SERGIO BRAIN/SERGIO BRAIN.md") });
    this.addCommand({ id: "health", name: "Brain Health", callback: () => this.generated(() => this.client.health_note(), "Brain Health actualizado", "SERGIO BRAIN/Brain Health.md") });
    this.addCommand({ id: "weekly", name: "Weekly Brain Review", callback: () => this.generated(() => this.client.review("weekly"), "Weekly review generado") });
    this.addCommand({ id: "monthly", name: "Monthly Brain Review", callback: () => this.generated(() => this.client.review("monthly"), "Monthly review generado") });
    this.addCommand({ id: "daily", name: "Update today's Daily Memory", callback: () => this.generated(() => this.client.review("daily"), "Daily memory actualizada") });
    this.addCommand({ id: "reindex", name: "Reindex vault (incremental)", callback: async () => {
      try {
        const r = await this.client.reindex();
        new import_obsidian3.Notice(`Indexadas ${r.indexed}, sin cambios ${r.skipped}`);
      } catch (e) {
        new import_obsidian3.Notice("Error: " + e.message);
      }
    } });
    this.addCommand({ id: "backup", name: "Backup snapshot now", callback: async () => {
      try {
        const r = await this.client.backup();
        new import_obsidian3.Notice(`Backup: ${r.files} archivos`);
      } catch (e) {
        new import_obsidian3.Notice("Error: " + e.message);
      }
    } });
    this.registerEvent(this.app.vault.on("modify", (f) => this.notify(f)));
    this.registerEvent(this.app.vault.on("create", (f) => this.notify(f)));
    this.registerEvent(this.app.vault.on("delete", (f) => this.notify(f, true)));
    this.registerEvent(this.app.vault.on("rename", (f, old) => {
      void this.client.notify(old, true).catch(() => {
      });
      this.notify(f);
    }));
    this.registerEvent(this.app.workspace.on("file-open", () => this.refreshPanel()));
    this.app.workspace.onLayoutReady(async () => {
      await this.checkHealth();
      this.registerInterval(window.setInterval(() => void this.checkHealth(), 6e4));
      if (this.settings.briefingOnStartup) await this.generated(() => this.client.briefing(), "Morning briefing generado");
      if (this.settings.recallOnStartup) await this.remember(true);
    });
  }
  onunload() {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE);
  }
  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }
  async saveSettings() {
    await this.saveData(this.settings);
  }
  // ---------------------------------------------------------------- helpers
  openOmnibar(initial = "") {
    new OmnibarModal(this.app, this, initial).open();
  }
  notify(f, deleted = false) {
    if (!this.settings.notifyOnChange || !(f instanceof import_obsidian3.TFile) || f.extension !== "md") return;
    const key = f.path;
    const prev = this.pending.get(key);
    if (prev) window.clearTimeout(prev);
    this.pending.set(key, window.setTimeout(() => {
      this.pending.delete(key);
      void this.client.notify(key, deleted).catch(() => {
      });
    }, 1500));
  }
  async checkHealth() {
    try {
      const h = await this.client.health();
      this.statusEl.setText(`\u{1F9E0} ${h.stats.documents_active} notas \xB7 ${h.pending_jobs} jobs \xB7 ${h.llm}`);
      this.statusEl.removeClass("sb-status-bad");
    } catch (e) {
      this.statusEl.setText("\u{1F9E0} motor apagado (sergio-brain serve)");
      this.statusEl.addClass("sb-status-bad");
    }
  }
  async capture() {
    var _a;
    const view = this.app.workspace.getActiveViewOfType(import_obsidian3.MarkdownView);
    let text = (_a = view == null ? void 0 : view.editor.getSelection()) != null ? _a : "";
    if (!text) {
      try {
        text = await navigator.clipboard.readText();
      } catch (e) {
        text = "";
      }
    }
    new CaptureModal(this.app, this, text).open();
  }
  async openPanel() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false);
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
    await leaf.view.refresh();
  }
  refreshPanel() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) void leaf.view.refresh();
  }
  async remember(quiet = false) {
    var _a;
    try {
      const r = await this.client.recall();
      if (!((_a = r.recall) == null ? void 0 : _a.length)) {
        if (!quiet) new import_obsidian3.Notice("Nada que recordar hoy.");
        return;
      }
      new RecallModal(this.app, this, r.recall).open();
    } catch (e) {
      if (!quiet) new import_obsidian3.Notice("Error: " + e.message);
    }
  }
  async whatChangedCurrent() {
    const f = this.app.workspace.getActiveFile();
    if (!f) return;
    try {
      const r = await this.client.changed(f.path);
      const m = new OmnibarModal(this.app, this);
      m.mode = "changed";
      m.open();
      m.renderChanged(m.contentEl.createDiv(), { documents: [r], superseded: [] });
    } catch (e) {
      new import_obsidian3.Notice("Error: " + e.message);
    }
  }
  async generated(fn, msg, openPath) {
    try {
      await fn();
      new import_obsidian3.Notice(msg);
      if (openPath) {
        const file = this.app.vault.getAbstractFileByPath(openPath);
        if (file instanceof import_obsidian3.TFile) await this.app.workspace.getLeaf(false).openFile(file);
      }
    } catch (e) {
      new import_obsidian3.Notice("Error: " + e.message);
    }
  }
};
var BrainSettingTab = class extends import_obsidian3.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Sergio Brain" });
    containerEl.createEl("p", { text: "El motor Python debe estar corriendo: sergio-brain serve", cls: "sb-muted" });
    new import_obsidian3.Setting(containerEl).setName("Engine URL").setDesc("Direcci\xF3n del motor local").addText((t) => t.setValue(this.plugin.settings.engineUrl).onChange(async (v) => {
      this.plugin.settings.engineUrl = v.trim();
      await this.plugin.saveSettings();
    }));
    new import_obsidian3.Setting(containerEl).setName("Token").setDesc("Debe coincidir con server.token en config.toml (opcional)").addText((t) => t.setValue(this.plugin.settings.token).onChange(async (v) => {
      this.plugin.settings.token = v.trim();
      await this.plugin.saveSettings();
    }));
    new import_obsidian3.Setting(containerEl).setName("Notificar cambios al motor").setDesc("Indexaci\xF3n inmediata al guardar (el watcher del motor es el respaldo)").addToggle((t) => t.setValue(this.plugin.settings.notifyOnChange).onChange(async (v) => {
      this.plugin.settings.notifyOnChange = v;
      await this.plugin.saveSettings();
    }));
    new import_obsidian3.Setting(containerEl).setName("Usar LLM en respuestas").setDesc("Si est\xE1 apagado, el asistente responde solo con pasajes citados").addToggle((t) => t.setValue(this.plugin.settings.useLlm).onChange(async (v) => {
      this.plugin.settings.useLlm = v;
      await this.plugin.saveSettings();
    }));
    new import_obsidian3.Setting(containerEl).setName("Morning briefing al abrir Obsidian").addToggle((t) => t.setValue(this.plugin.settings.briefingOnStartup).onChange(async (v) => {
      this.plugin.settings.briefingOnStartup = v;
      await this.plugin.saveSettings();
    }));
    new import_obsidian3.Setting(containerEl).setName("Recordatorios (active recall) al abrir Obsidian").addToggle((t) => t.setValue(this.plugin.settings.recallOnStartup).onChange(async (v) => {
      this.plugin.settings.recallOnStartup = v;
      await this.plugin.saveSettings();
    }));
  }
};
