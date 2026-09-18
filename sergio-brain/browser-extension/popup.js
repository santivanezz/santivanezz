const $ = (id) => document.getElementById(id);
const status = (t) => ($("status").textContent = t);

chrome.storage.sync.get({ engine: "http://127.0.0.1:8765", token: "", autosave: false }, (s) => { $("engine").value = s.engine; $("token").value = s.token; $("autosave").checked = s.autosave; });
for (const id of ["engine", "token"]) $(id).addEventListener("change", () => chrome.storage.sync.set({ engine: $("engine").value.trim(), token: $("token").value.trim() }));
$("autosave").addEventListener("change", () => chrome.storage.sync.set({ autosave: $("autosave").checked }));

async function activeTab() { const [tab] = await chrome.tabs.query({ active: true, currentWindow: true }); return tab; }

async function extract(kind) {
  const tab = await activeTab();
  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [kind],
    func: (kind) => {
      const clean = (t) => t.replace(/\s+\n/g, "\n").replace(/[ \t]{2,}/g, " ").trim();
      if (kind === "sel") return { text: clean(window.getSelection().toString()), title: document.title };
      if (kind === "url") return { text: "", title: document.title };
      if (kind === "article") {
        const el = document.querySelector("article") || document.querySelector("main") || document.querySelector('[role="main"]') || document.body;
        return { text: clean(el.innerText).slice(0, 60000), title: document.title };
      }
      return { text: clean(document.body.innerText).slice(0, 120000), title: document.title };
    },
  });
  return { ...res.result, url: tab.url };
}

async function send(kind) {
  try {
    status("Capturando…");
    const data = await extract(kind);
    if (kind === "sel" && !data.text) return status("No hay texto seleccionado.");
    const text = data.text || `${data.title}\n${data.url}`;
    const headers = { "Content-Type": "application/json" };
    if ($("token").value) headers["X-Brain-Token"] = $("token").value;
    const r = await fetch($("engine").value.replace(/\/$/, "") + "/capture", {
      method: "POST", headers,
      body: JSON.stringify({ text, title: data.title, url: data.url, capture_type: "web", force: kind === "url",
        source: { source_type: "web", capture_method: "browser-extension:" + kind, source_date: new Date().toISOString().slice(0, 10) } }),
    });
    const j = await r.json();
    status(j.message || (j.saved ? "Guardado" : "No guardado") + (j.existing_candidates?.length ? " · quizá ya existe: " + j.existing_candidates.map((x) => x.title).join(", ") : ""));
  } catch (e) { status("Error: motor apagado? " + e.message); }
}
for (const k of ["sel", "url", "article", "page"]) $(k).addEventListener("click", () => send(k));

async function saveAiChat() {
  try {
    status("Guardando conversación…");
    const tab = await activeTab();
    const j = await chrome.tabs.sendMessage(tab.id, { type: "SB_SAVE_AI_CHAT", engine: $("engine").value, token: $("token").value });
    if (j?.error) return status("Error: " + j.error);
    status(`${j.action}: ${j.path || ""} (${j.messages ?? 0} mensajes${j.secrets_redacted ? ", " + j.secrets_redacted + " secretos redactados" : ""})`);
  } catch (e) { status("Esta pestaña no es ChatGPT/Claude/Gemini, o recarga la página."); }
}
$("aichat").addEventListener("click", saveAiChat);
activeTab().then((tab) => chrome.tabs.sendMessage(tab.id, { type: "SB_PROBE" }).then((p) => { $("aiInfo").textContent = `${p.provider}: ${p.messages} mensajes detectados`; }).catch(() => { $("aiInfo").textContent = "Abre ChatGPT, Claude o Gemini para guardar la conversación."; }));
