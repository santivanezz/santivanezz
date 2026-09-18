import { requestUrl } from "obsidian";

export interface BrainSettings {
  engineUrl: string;
  token: string;
  notifyOnChange: boolean;
  briefingOnStartup: boolean;
  useLlm: boolean;
  recallOnStartup: boolean;
}

export const DEFAULT_SETTINGS: BrainSettings = {
  engineUrl: "http://127.0.0.1:8765",
  token: "",
  notifyOnChange: true,
  briefingOnStartup: false,
  useLlm: true,
  recallOnStartup: true,
};

export class BrainClient {
  constructor(private settings: () => BrainSettings) {}

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    const t = this.settings().token;
    if (t) h["X-Brain-Token"] = t;
    return h;
  }

  private url(path: string, params?: Record<string, string | number | undefined>): string {
    const base = this.settings().engineUrl.replace(/\/$/, "");
    const qs = params
      ? Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== "")
          .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
          .join("&")
      : "";
    return base + path + (qs ? "?" + qs : "");
  }

  async get<T = any>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
    const r = await requestUrl({ url: this.url(path, params), method: "GET", headers: this.headers(), throw: false });
    if (r.status >= 400) throw new Error(`Engine ${r.status}: ${r.text?.slice(0, 200)}`);
    return r.json as T;
  }

  async post<T = any>(path: string, body: unknown): Promise<T> {
    const r = await requestUrl({ url: this.url(path), method: "POST", headers: this.headers(), body: JSON.stringify(body), throw: false });
    if (r.status >= 400) throw new Error(`Engine ${r.status}: ${r.text?.slice(0, 200)}`);
    return r.json as T;
  }

  health() { return this.get("/health"); }
  ask(q: string, useLlm: boolean) { return this.post("/ask", { q, use_llm: useLlm }); }
  search(q: string, k = 12) { return this.get("/search", { q, k }); }
  related(path: string) { return this.get("/related", { path }); }
  capture(text: string, extra: Record<string, unknown> = {}) { return this.post("/capture", { text, ...extra }); }
  notify(path: string, deleted = false) { return this.post("/notify", { path, deleted }); }
  recall() { return this.get("/recall"); }
  briefing() { return this.get("/briefing"); }
  dashboard() { return this.get("/dashboard"); }
  health_note() { return this.get("/brain-health", { write: 1 }); }
  review(period: string) { return this.get("/review", { period }); }
  why(q: string) { return this.get("/why", { q }); }
  changed(path?: string, q?: string) { return this.get("/changed", { path, q }); }
  feedback(target_type: string, target_id: string | number, verdict: string) { return this.post("/feedback", { target_type, target_id, verdict }); }
  reindex() { return this.post("/reindex", {}); }
  backup() { return this.post("/backup", { kind: "snapshot" }); }
  timeline(days = 14) { return this.get("/timeline", { days }); }
  tasks() { return this.get("/tasks"); }
  suggestions() { return this.get("/suggestions"); }
  contradictions() { return this.get("/contradictions"); }
}
