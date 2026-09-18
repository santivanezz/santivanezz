const $ = (id) => document.getElementById(id);
const status = (t) => ($("status").textContent = t);

chrome.storage.sync.get({ engine: "http://127.0.0.1:8765", token: "" }, (s) => { $("engine").value = s.engine; $("token").value = s.token; });
for (const id of ["engine", "token"]) $(id).addEventListener("change", () => chrome.storage.sync.set({ engine: $("engine").value.trim(), token: $("token").value.trim() }));

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
