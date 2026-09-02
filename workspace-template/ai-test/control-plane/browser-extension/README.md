# Controlled Browser Extension

The extension records page navigation, clicks and non-secret field semantics. Password, OTP, token, captcha and similar fields are always stored as `<SECRET_INPUT>`; raw values are never sent to the runtime.

The control plane writes the current `browserSessionId` and URL into extension local storage when it opens a controlled browser session. If enterprise Chrome policy blocks unpacked extensions, bind an approved browser automation adapter instead; HumanTask and BrowserSession state remain unchanged.
