import { ItemView, Modal, App, WorkspaceLeaf, Notice, MarkdownRenderer, Component } from "obsidian";
import type SergioBrainPlugin from "./main";

export const VIEW_TYPE = "sergio-brain-panel";

function openNote(app: App, path: string) {
  const file = app.vault.getAbstractFileByPath(path);
  if (file) app.workspace.openLinkText(path, "", false);
  else new Notice("Nota no encontrada: " + path);
}

/** Side panel: related notes, entities and memories for the active note. */
export class BrainPanelView extends ItemView {
  plugin: SergioBrainPlugin;
  constructor(leaf: WorkspaceLeaf, plugin: SergioBrainPlugin) {
    super(leaf);
    this.plugin = plugin;
  }
  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "Sergio Brain"; }
  getIcon() { return "brain"; }

  async onOpen() { await this.refresh(); }

  async refresh() {
    const root = this.contentEl;
    root.empty();
    root.addClass("sb-panel");
    const file = this.app.workspace.getActiveFile();
    root.createEl("h3", { text: "SERGIO BRAIN" });
    if (!file) { root.createEl("p", { text: "Abre una nota para ver su memoria.", cls: "sb-muted" }); return; }
    root.createEl("p", { text: file.basename, cls: "sb-muted" });
    let data: any;
    try { data = await this.plugin.client.related(file.path); } catch (e) { root.createEl("p", { text: "Motor no disponible: " + (e as Error).message, cls: "sb-status-bad" }); return; }
    if (data.message) root.createEl("p", { text: data.message, cls: "sb-muted" });
    root.createEl("h4", { text: "Related notes" });
    if (!data.related?.length) root.createEl("p", { text: "(ninguna todavía)", cls: "sb-muted" });
    for (const r of data.related ?? []) {
      const d = root.createDiv({ cls: "sb-item" });
      const a = d.createEl("a", { text: r.title });
      a.onclick = () => openNote(this.app, r.path);
      d.createSpan({ text: String(r.score), cls: "sb-score" });
      d.createDiv({ text: (r.reasons ?? []).join(" · "), cls: "sb-muted" });
    }
    root.createEl("h4", { text: "Memories" });
    for (const m of data.memories ?? []) {
      const d = root.createDiv({ cls: "sb-item" });
      d.createSpan({ text: m.memory_type, cls: "sb-badge" });
      d.createSpan({ text: m.content.slice(0, 140) });
      const fb = d.createSpan({ cls: "sb-fb" });
      for (const v of ["IMPORTANT", "NOT_USEFUL", "WRONG"]) {
        const b = fb.createEl("button", { text: v === "IMPORTANT" ? "★" : v === "NOT_USEFUL" ? "✕" : "!" , title: v });
        b.onclick = async () => { await this.plugin.client.feedback("memory", m.id, v); new Notice("Feedback: " + v); };
      }
      if (m.importance_reason) d.createDiv({ text: m.importance_reason, cls: "sb-muted" });
    }
    root.createEl("h4", { text: "Entities" });
    root.createEl("p", { text: (data.entities ?? []).slice(0, 20).map((e: any) => `${e.name} (${e.entity_type})`).join(", ") || "(ninguna)", cls: "sb-muted" });
  }
}

/** Omnibar: ask / search / why / changed with answer, sources, related, timeline. */
export class OmnibarModal extends Modal {
  plugin: SergioBrainPlugin;
  mode: "ask" | "search" | "why" | "changed" = "ask";
  initial: string;
  constructor(app: App, plugin: SergioBrainPlugin, initial = "") { super(app); this.plugin = plugin; this.initial = initial; }

  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Ask Sergio Brain" });
    const tabs = contentEl.createDiv({ cls: "sb-tabs" });
    const modes: Array<[typeof this.mode, string]> = [["ask", "Ask"], ["search", "Search"], ["why", "Why do I know this?"], ["changed", "What changed?"]];
    const buttons: HTMLButtonElement[] = [];
    for (const [m, label] of modes) {
      const b = tabs.createEl("button", { text: label });
      b.onclick = () => { this.mode = m; buttons.forEach(x => x.removeClass("mod-cta")); b.addClass("mod-cta"); };
      if (m === this.mode) b.addClass("mod-cta");
      buttons.push(b);
    }
    const input = contentEl.createEl("textarea", { placeholder: "¿Qué tengo pendiente? ¿Qué sé sobre Erlang C? ¿Por qué decidí X?" });
    input.value = this.initial;
    const out = contentEl.createDiv();
    const run = async () => {
      const q = input.value.trim();
      if (!q) return;
      out.empty();
      out.createEl("p", { text: "Pensando…", cls: "sb-muted" });
      try {
        if (this.mode === "ask") await this.renderAsk(out, await this.plugin.client.ask(q, this.plugin.settings.useLlm));
        else if (this.mode === "search") this.renderSearch(out, await this.plugin.client.search(q));
        else if (this.mode === "why") this.renderWhy(out, await this.plugin.client.why(q));
        else this.renderChanged(out, await this.plugin.client.changed(undefined, q));
      } catch (e) { out.empty(); out.createEl("p", { text: "Error: " + (e as Error).message, cls: "sb-status-bad" }); }
    };
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); void run(); } });
    const go = contentEl.createEl("button", { text: "Preguntar (Enter)", cls: "mod-cta" });
    go.onclick = () => void run();
    setTimeout(() => input.focus(), 30);
    if (this.initial) void run();
  }

  private link(el: HTMLElement, title: string, path: string) {
    const a = el.createEl("a", { text: title });
    a.onclick = () => { openNote(this.app, path); this.close(); };
  }

  async renderAsk(out: HTMLElement, res: any) {
    out.empty();
    out.createDiv({ text: `${res.evidence} · ${res.mode} · ${res.duration_ms} ms`, cls: "sb-muted" });
    const ans = out.createDiv({ cls: "sb-answer" });
    await MarkdownRenderer.render(this.app, res.answer ?? "", ans, "", new Component());
    if (res.llm_error) out.createDiv({ text: "LLM no usado: " + res.llm_error, cls: "sb-muted" });
    const fb = out.createDiv({ cls: "sb-fb" });
    fb.createSpan({ text: "¿Útil? " });
    for (const v of ["USEFUL", "NOT_USEFUL", "WRONG"]) {
      const b = fb.createEl("button", { text: v });
      b.onclick = async () => { await this.plugin.client.feedback("answer", res.question, v); new Notice("Gracias, feedback guardado"); };
    }
    const sec = (title: string) => { out.createEl("h4", { text: title }); return out.createDiv({ cls: "sb-sources" }); };
    const s = sec("Sources");
    for (const src of res.sources ?? []) { const d = s.createDiv({ cls: "sb-item" }); this.link(d, src.title, src.path); d.createSpan({ text: String(src.score), cls: "sb-score" }); d.createDiv({ text: src.snippet, cls: "sb-muted" }); }
    if (res.related?.length) { const r = sec("Related notes"); for (const x of res.related) { const d = r.createDiv({ cls: "sb-item" }); this.link(d, x.title, x.path); d.createDiv({ text: (x.reasons ?? []).join(" · "), cls: "sb-muted" }); } }
    if (res.entities?.length) sec("Entities").createEl("p", { text: res.entities.map((e: any) => `${e.name} (${e.type})`).join(", ") });
    if (res.projects?.length) sec("Projects").createEl("p", { text: res.projects.map((p: any) => p.name).join(", ") });
    if (res.timeline?.length) { const t = sec("Timeline"); for (const it of res.timeline) t.createDiv({ text: `${it.date} · ${it.kind} · ${it.title}`, cls: "sb-item" }); }
    if (res.why) { const w = sec("Provenance"); w.createEl("pre", { text: res.why.summary }); }
  }

  renderSearch(out: HTMLElement, res: any) {
    out.empty();
    for (const r of res.results ?? []) { const d = out.createDiv({ cls: "sb-item" }); this.link(d, r.title, r.path); d.createSpan({ text: String(r.score), cls: "sb-score" }); d.createDiv({ text: r.snippet?.slice(0, 200), cls: "sb-muted" }); }
    if (!res.results?.length) out.createEl("p", { text: "Not enough evidence in Boveda Sergio.", cls: "sb-muted" });
  }

  renderWhy(out: HTMLElement, res: any) {
    out.empty();
    out.createEl("pre", { text: res.summary });
    for (const n of res.chain ?? []) { const d = out.createDiv({ cls: "sb-item" }); this.link(d, n.title, n.path); d.createDiv({ text: n.evidence, cls: "sb-muted" }); }
  }

  renderChanged(out: HTMLElement, res: any) {
    out.empty();
    for (const d of res.documents ?? []) {
      const el = out.createDiv({ cls: "sb-item" });
      if (d.document) this.link(el, d.document.title, d.document.path);
      el.createDiv({ text: d.message, cls: "sb-muted" });
      if (d.diff) el.createEl("pre", { text: d.diff.slice(0, 4000) });
    }
    for (const s of res.superseded ?? []) out.createDiv({ text: `SUPERSEDED · ${s.subject}: «${s.statement_a}» → «${s.statement_b}»`, cls: "sb-item" });
    if (!res.documents?.length) out.createEl("p", { text: "Sin cambios registrados para esa consulta.", cls: "sb-muted" });
  }

  onClose() { this.contentEl.empty(); }
}

/** Capture modal: free text (prefilled with selection or clipboard) → Inbox. */
export class CaptureModal extends Modal {
  plugin: SergioBrainPlugin;
  text: string;
  constructor(app: App, plugin: SergioBrainPlugin, text: string) { super(app); this.plugin = plugin; this.text = text; }
  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Capture to Inbox" });
    const title = contentEl.createEl("input", { type: "text", placeholder: "Título (opcional)" });
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
      try {
        const res = await this.plugin.client.capture(ta.value, { title: title.value || undefined, url: url.value || undefined, capture_type: "hotkey", force: cb.checked, source: { source_type: "obsidian", capture_method: "plugin", source_note: this.app.workspace.getActiveFile()?.path } });
        new Notice(res.message ?? (res.saved ? "Guardado" : "No guardado"));
        if (res.existing_candidates?.length) new Notice("Posiblemente ya existe: " + res.existing_candidates.map((x: any) => x.title).join(", "), 8000);
        this.close();
      } catch (e) { new Notice("Error: " + (e as Error).message); }
    };
  }
  onClose() { this.contentEl.empty(); }
}

/** Shows a list of reminders (active recall) with feedback. */
export class RecallModal extends Modal {
  plugin: SergioBrainPlugin;
  items: any[];
  constructor(app: App, plugin: SergioBrainPlugin, items: any[]) { super(app); this.plugin = plugin; this.items = items; }
  onOpen() {
    const { contentEl } = this;
    contentEl.addClass("sb-omnibar");
    contentEl.createEl("h2", { text: "Remember" });
    if (!this.items.length) contentEl.createEl("p", { text: "Nada que recordar hoy.", cls: "sb-muted" });
    for (const it of this.items) {
      const d = contentEl.createDiv({ cls: "sb-item" });
      d.createSpan({ text: it.kind, cls: "sb-badge" });
      d.createSpan({ text: it.message });
      if (it.path) { const a = d.createEl("a", { text: " abrir" }); a.onclick = () => { openNote(this.app, it.path); this.close(); }; }
      const fb = d.createSpan({ cls: "sb-fb" });
      for (const v of ["USEFUL", "IGNORE"]) {
        const b = fb.createEl("button", { text: v });
        b.onclick = async () => { const [type, id] = String(it.key).split(":"); await this.plugin.client.feedback(type === "suggestion" ? "suggestion" : type === "task" || type === "decision" ? "memory" : type, id ?? it.key, v); b.setText("✓"); };
      }
    }
  }
  onClose() { this.contentEl.empty(); }
}
