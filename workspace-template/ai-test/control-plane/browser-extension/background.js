const DEFAULT_URL = "http://127.0.0.1:8765";

async function settings() {
  const stored = await chrome.storage.local.get(["controlPlaneUrl", "browserSessionId"]);
  const controlPlaneUrl = stored.controlPlaneUrl || DEFAULT_URL;
  let browserSessionId = stored.browserSessionId || null;
  if (!browserSessionId) {
    try {
      const response = await fetch(`${controlPlaneUrl}/api/browser/active`);
      const data = await response.json();
      browserSessionId = data?.browser_session?.browser_session_id || null;
      if (browserSessionId) await chrome.storage.local.set({browserSessionId, controlPlaneUrl});
    } catch (_) {}
  }
  return {controlPlaneUrl, browserSessionId};
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "AITEST_BROWSER_EVENT") return false;
  (async () => {
    const cfg = await settings();
    if (!cfg.browserSessionId) {
      sendResponse({ok: false, error: "No active controlled browser session"});
      return;
    }
    const body = {...message.payload, browser_session_id: cfg.browserSessionId};
    try {
      const response = await fetch(`${cfg.controlPlaneUrl}/api/browser/events`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      sendResponse({ok: response.ok});
    } catch (error) {
      sendResponse({ok: false, error: String(error)});
    }
  })();
  return true;
});

chrome.tabs.onRemoved.addListener(async () => {
  // Do not retain a stale lease forever. The next event will discover the newest open session.
  await chrome.storage.local.remove("browserSessionId");
});
