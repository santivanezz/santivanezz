import { App, Notice, Plugin, PluginSettingTab, Setting, TFile, MarkdownView, TAbstractFile } from "obsidian";
import { BrainClient, BrainSettings, DEFAULT_SETTINGS } from "./api";
import { BrainPanelView, CaptureModal, OmnibarModal, RecallModal, VIEW_TYPE } from "./views";

export default class SergioBrainPlugin extends Plugin {
  settings: BrainSettings = DEFAULT_SETTINGS;
  client!: BrainClient;
  private statusEl!: HTMLElement;
  private pending = new Map<string, number>();

  async onload() {
    await this.loadSettings();
    this.client = new BrainClient(() => this.settings);
    this.addSettingTab(new BrainSettingTab(this.app, this));
    this.registerView(VIEW_TYPE, (leaf) => new BrainPanelView(leaf, this));
    this.statusEl = this.addStatusBarItem();
    this.addRibbonIcon("brain", "Sergio Brain", () => this.openOmnibar());

    // ---- commands (quick access: Capture, Ask, Search, Related, Remember, Review, Brain Health)
    this.addCommand({ id: "ask", name: "Ask Sergio Brain (Omnibar)", hotkeys: [{ modifiers: ["Ctrl", "Shift"], key: "b" }], callback: () => this.openOmnibar() });
    this.addCommand({ id: "ask-selection", name: "Ask about selection", editorCallback: (editor) => this.openOmnibar(editor.getSelection()) });
    this.addCommand({ id: "capture", name: "Capture selection / clipboard to Inbox", hotkeys: [{ modifiers: ["Ctrl", "Alt"], key: "s" }], callback: () => void this.capture() });
    this.addCommand({ id: "search", name: "Search (hybrid)", callback: () => { const m = new OmnibarModal(this.app, this); m.mode = "search"; m.open(); } });
    this.addCommand({ id: "related", name: "Related notes panel", callback: () => void this.openPanel() });
    this.addCommand({ id: "remember", name: "Remember (active recall)", callback: () => void this.remember() });
    this.addCommand({ id: "why", name: "Why do I know this?", editorCallback: (editor) => { const m = new OmnibarModal(this.app, this, editor.getSelection()); m.mode = "why"; m.open(); } });
    this.addCommand({ id: "changed", name: "What changed in this note?", callback: () => void this.whatChangedCurrent() });
    this.addCommand({ id: "briefing", name: "Morning briefing (GOOD MORNING SERGIO)", callback: () => this.generated(() => this.client.briefing(), "Morning briefing generado") });
    this.addCommand({ id: "dashboard", name: "Open SERGIO BRAIN command center", callback: () => this.generated(() => this.client.dashboard(), "Dashboard actualizado", "SERGIO BRAIN/SERGIO BRAIN.md") });
    this.addCommand({ id: "health", name: "Brain Health", callback: () => this.generated(() => this.client.health_note(), "Brain Health actualizado", "SERGIO BRAIN/Brain Health.md") });
    this.addCommand({ id: "weekly", name: "Weekly Brain Review", callback: () => this.generated(() => this.client.review("weekly"), "Weekly review generado") });
    this.addCommand({ id: "monthly", name: "Monthly Brain Review", callback: () => this.generated(() => this.client.review("monthly"), "Monthly review generado") });
    this.addCommand({ id: "daily", name: "Update today's Daily Memory", callback: () => this.generated(() => this.client.review("daily"), "Daily memory actualizada") });
    this.addCommand({ id: "reindex", name: "Reindex vault (incremental)", callback: async () => { try { const r = await this.client.reindex(); new Notice(`Indexadas ${r.indexed}, sin cambios ${r.skipped}`); } catch (e) { new Notice("Error: " + (e as Error).message); } } });
    this.addCommand({ id: "backup", name: "Backup snapshot now", callback: async () => { try { const r = await this.client.backup(); new Notice(`Backup: ${r.files} archivos`); } catch (e) { new Notice("Error: " + (e as Error).message); } } });

    // ---- vault events -> engine (debounced); the engine's own watcher is the safety net
    this.registerEvent(this.app.vault.on("modify", (f) => this.notify(f)));
    this.registerEvent(this.app.vault.on("create", (f) => this.notify(f)));
    this.registerEvent(this.app.vault.on("delete", (f) => this.notify(f, true)));
    this.registerEvent(this.app.vault.on("rename", (f, old) => { void this.client.notify(old, true).catch(() => {}); this.notify(f); }));
    this.registerEvent(this.app.workspace.on("file-open", () => this.refreshPanel()));

    this.app.workspace.onLayoutReady(async () => {
      await this.checkHealth();
      this.registerInterval(window.setInterval(() => void this.checkHealth(), 60000));
      if (this.settings.briefingOnStartup) await this.generated(() => this.client.briefing(), "Morning briefing generado");
      if (this.settings.recallOnStartup) await this.remember(true);
    });
  }

  onunload() { this.app.workspace.detachLeavesOfType(VIEW_TYPE); }

  async loadSettings() { this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData()); }
  async saveSettings() { await this.saveData(this.settings); }

  // ---------------------------------------------------------------- helpers
  openOmnibar(initial = "") { new OmnibarModal(this.app, this, initial).open(); }

  private notify(f: TAbstractFile, deleted = false) {
    if (!this.settings.notifyOnChange || !(f instanceof TFile) || f.extension !== "md") return;
    const key = f.path;
    const prev = this.pending.get(key);
    if (prev) window.clearTimeout(prev);
    this.pending.set(key, window.setTimeout(() => { this.pending.delete(key); void this.client.notify(key, deleted).catch(() => {}); }, 1500));
  }

  async checkHealth() {
    try {
      const h = await this.client.health();
      this.statusEl.setText(`🧠 ${h.stats.documents_active} notas · ${h.pending_jobs} jobs · ${h.llm}`);
      this.statusEl.removeClass("sb-status-bad");
    } catch {
      this.statusEl.setText("🧠 motor apagado (sergio-brain serve)");
      this.statusEl.addClass("sb-status-bad");
    }
  }

  async capture() {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    let text = view?.editor.getSelection() ?? "";
    if (!text) { try { text = await navigator.clipboard.readText(); } catch { text = ""; } }
    new CaptureModal(this.app, this, text).open();
  }

  async openPanel() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) { leaf = this.app.workspace.getRightLeaf(false)!; await leaf.setViewState({ type: VIEW_TYPE, active: true }); }
    this.app.workspace.revealLeaf(leaf);
    await (leaf.view as BrainPanelView).refresh();
  }

  refreshPanel() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) void (leaf.view as BrainPanelView).refresh();
  }

  async remember(quiet = false) {
    try {
      const r = await this.client.recall();
      if (!r.recall?.length) { if (!quiet) new Notice("Nada que recordar hoy."); return; }
      new RecallModal(this.app, this, r.recall).open();
    } catch (e) { if (!quiet) new Notice("Error: " + (e as Error).message); }
  }

  async whatChangedCurrent() {
    const f = this.app.workspace.getActiveFile();
    if (!f) return;
    try {
      const r = await this.client.changed(f.path);
      const m = new OmnibarModal(this.app, this); m.mode = "changed"; m.open();
      m.renderChanged(m.contentEl.createDiv(), { documents: [r], superseded: [] });
    } catch (e) { new Notice("Error: " + (e as Error).message); }
  }

  async generated(fn: () => Promise<any>, msg: string, openPath?: string) {
    try {
      await fn();
      new Notice(msg);
      if (openPath) { const file = this.app.vault.getAbstractFileByPath(openPath); if (file instanceof TFile) await this.app.workspace.getLeaf(false).openFile(file); }
    } catch (e) { new Notice("Error: " + (e as Error).message); }
  }
}

class BrainSettingTab extends PluginSettingTab {
  plugin: SergioBrainPlugin;
  constructor(app: App, plugin: SergioBrainPlugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Sergio Brain" });
    containerEl.createEl("p", { text: "El motor Python debe estar corriendo: sergio-brain serve", cls: "sb-muted" });
    new Setting(containerEl).setName("Engine URL").setDesc("Dirección del motor local").addText(t => t.setValue(this.plugin.settings.engineUrl).onChange(async v => { this.plugin.settings.engineUrl = v.trim(); await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("Token").setDesc("Debe coincidir con server.token en config.toml (opcional)").addText(t => t.setValue(this.plugin.settings.token).onChange(async v => { this.plugin.settings.token = v.trim(); await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("Notificar cambios al motor").setDesc("Indexación inmediata al guardar (el watcher del motor es el respaldo)").addToggle(t => t.setValue(this.plugin.settings.notifyOnChange).onChange(async v => { this.plugin.settings.notifyOnChange = v; await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("Usar LLM en respuestas").setDesc("Si está apagado, el asistente responde solo con pasajes citados").addToggle(t => t.setValue(this.plugin.settings.useLlm).onChange(async v => { this.plugin.settings.useLlm = v; await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("Morning briefing al abrir Obsidian").addToggle(t => t.setValue(this.plugin.settings.briefingOnStartup).onChange(async v => { this.plugin.settings.briefingOnStartup = v; await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("Recordatorios (active recall) al abrir Obsidian").addToggle(t => t.setValue(this.plugin.settings.recallOnStartup).onChange(async v => { this.plugin.settings.recallOnStartup = v; await this.plugin.saveSettings(); }));
  }
}
