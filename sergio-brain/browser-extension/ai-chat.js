// Content script: extracts the current AI conversation (ChatGPT / Claude / Gemini) as messages.
// Runs only on those hosts. Sends nothing unless you click "Save AI conversation" or enable auto-save.
(() => {
  const host = location.hostname;
  const provider = host.includes("openai") || host.includes("chatgpt") ? "chatgpt" : host.includes("claude") ? "claude" : host.includes("gemini") ? "gemini" : "other";
  const clean = (t) => (t || "").replace(/ /g, " ").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();

  function extract() {
    let messages = [];
    if (provider === "chatgpt") {
      document.querySelectorAll("[data-message-author-role]").forEach((el) => {
        const role = el.getAttribute("data-message-author-role") === "user" ? "user" : "assistant";
        messages.push({ role, text: clean(el.innerText) });
      });
    } else if (provider === "claude") {
      // Claude renders user turns and assistant turns as sibling blocks; fall back to heuristics.
      const nodes = document.querySelectorAll('[data-testid="user-message"], .font-user-message, .font-claude-message, [data-is-streaming]');
      nodes.forEach((el) => {
        const isUser = el.matches('[data-testid="user-message"], .font-user-message');
        messages.push({ role: isUser ? "user" : "assistant", text: clean(el.innerText) });
      });
    } else if (provider === "gemini") {
      document.querySelectorAll("user-query, model-response").forEach((el) => {
        messages.push({ role: el.tagName.toLowerCase() === "user-query" ? "user" : "assistant", text: clean(el.innerText) });
      });
    }
    messages = messages.filter((m) => m.text);
    if (!messages.length) {
      const main = document.querySelector("main") || document.body;
      const text = clean(main.innerText).slice(0, 60000);
      if (text) messages = [{ role: "assistant", text }];
    }
    const id = location.pathname.split("/").filter(Boolean).pop() || location.href;
    const title = clean(document.title).replace(/\s*[-|]\s*(ChatGPT|Claude|Gemini).*$/i, "") || "Sin título";
    return { provider, id: `${provider}-${id}`, url: location.href, title, messages };
  }

  let lastSig = "";
  async function save(engine, token, force) {
    const conv = extract();
    const sig = JSON.stringify(conv.messages).length + ":" + conv.id;
    if (!force && sig === lastSig) return { action: "unchanged" };
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Brain-Token"] = token;
    const r = await fetch(engine.replace(/\/$/, "") + "/ai-chat", { method: "POST", headers, body: JSON.stringify(conv) });
    const j = await r.json();
    if (j.action && j.action !== "ignored") lastSig = sig;
    return j;
  }

  chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
    if (msg.type === "SB_SAVE_AI_CHAT") {
      save(msg.engine, msg.token, true).then(respond).catch((e) => respond({ error: e.message }));
      return true;
    }
    if (msg.type === "SB_PROBE") { respond({ provider, messages: extract().messages.length }); return true; }
  });

  // Auto-save (opt-in): after the page is quiet for 20 s and the conversation changed, upsert it.
  let timer = null;
  function schedule() {
    chrome.storage.sync.get({ engine: "http://127.0.0.1:8765", token: "", autosave: false }, (s) => {
      if (!s.autosave) return;
      clearTimeout(timer);
      timer = setTimeout(() => save(s.engine, s.token, false).catch(() => {}), 20000);
    });
  }
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true, characterData: true });
  window.addEventListener("beforeunload", () => {
    chrome.storage.sync.get({ engine: "http://127.0.0.1:8765", token: "", autosave: false }, (s) => { if (s.autosave) save(s.engine, s.token, false).catch(() => {}); });
  });
})();
