(() => {
  const SENSITIVE = /(password|passwd|pwd|otp|mfa|token|secret|captcha|verification.?code|验证码|令牌|密码)/i;
  const MAX_TEXT = 160;

  function cssPath(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
      let part = cur.tagName.toLowerCase();
      const name = cur.getAttribute("name");
      const role = cur.getAttribute("role");
      if (name) part += `[name="${CSS.escape(name)}"]`;
      else if (role) part += `[role="${CSS.escape(role)}"]`;
      else if (cur.parentElement) {
        const siblings = [...cur.parentElement.children].filter(x => x.tagName === cur.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  function semantic(el) {
    return (
      el.getAttribute?.("aria-label") ||
      el.getAttribute?.("title") ||
      el.getAttribute?.("placeholder") ||
      el.getAttribute?.("name") ||
      el.innerText ||
      el.textContent ||
      el.tagName ||
      "element"
    ).trim().slice(0, MAX_TEXT);
  }

  function isSensitive(el) {
    const attrs = [el.type, el.name, el.id, el.placeholder, el.getAttribute?.("aria-label")].filter(Boolean).join(" ");
    return el.type === "password" || SENSITIVE.test(attrs);
  }

  function send(eventType, el, extra = {}) {
    const sensitive = isSensitive(el);
    const payload = {
      event_type: eventType,
      url: location.href,
      selector: cssPath(el),
      semantic_name: semantic(el),
      sensitive,
      value_repr: sensitive ? "<SECRET_INPUT>" : (extra.value_repr || ""),
      timestamp: new Date().toISOString(),
      ...extra,
    };
    delete payload.value;
    chrome.runtime.sendMessage({type: "AITEST_BROWSER_EVENT", payload}).catch(() => {});
  }

  document.addEventListener("click", e => send("CLICK", e.target), true);
  document.addEventListener("change", e => {
    const el = e.target;
    let value = "";
    if (!isSensitive(el)) {
      if (el.type === "checkbox" || el.type === "radio") value = String(el.checked);
      else value = String(el.value || "").slice(0, MAX_TEXT);
    }
    send("CHANGE", el, {value_repr: value});
  }, true);
  window.addEventListener("load", () => send("PAGE_LOADED", document.documentElement, {title: document.title}), {once: true});
})();
