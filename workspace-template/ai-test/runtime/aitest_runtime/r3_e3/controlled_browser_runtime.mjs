const BROWSER_CLIENT_MODULE_ENV = "AITEST_BROWSER_CLIENT_MODULE";

function configuredBrowserClientModule() {
  return globalThis?.process?.env?.[BROWSER_CLIENT_MODULE_ENV] || null;
}

/**
 * Controlled Browser client entrypoint.
 *
 * The setup call is deliberately before every browser selection access. This
 * wrapper is the JavaScript seam used by the in-app Browser runtime; the
 * Python runtime uses the same ordering through setupBrowserRuntime().
 */
export async function setupControlledBrowserRuntime({
  browserClientModule = null,
  setup = null,
  select = null,
} = {}) {
  const moduleSpecifier = browserClientModule || configuredBrowserClientModule();
  if (!setup && !moduleSpecifier) {
    const error = new Error(`R3_E3_BROWSER_CLIENT_MODULE_NOT_CONFIGURED: set ${BROWSER_CLIENT_MODULE_ENV} or pass browserClientModule`);
    error.code = "R3_E3_BROWSER_CLIENT_MODULE_NOT_CONFIGURED";
    throw error;
  }
  const setupBrowserRuntime = setup || (await import(moduleSpecifier)).setupBrowserRuntime;
  if (typeof setupBrowserRuntime !== "function") {
    const error = new Error("R3_E3_BROWSER_CLIENT_INIT_FAILED: setupBrowserRuntime is unavailable");
    error.code = "R3_E3_BROWSER_CLIENT_INIT_FAILED";
    throw error;
  }

  globalThis.agent = await setupBrowserRuntime();
  if (!globalThis.agent?.browsers) {
    const error = new Error("R3_E3_BROWSER_CLIENT_INIT_FAILED: initialized agent has no browsers capability");
    error.code = "R3_E3_BROWSER_CLIENT_INIT_FAILED";
    throw error;
  }

  globalThis.browser = select
    ? await select(globalThis.agent)
    : await globalThis.agent.browsers.getDefault();
  if (!globalThis.browser) {
    const error = new Error("R3_E3_BROWSER_CLIENT_INIT_FAILED: Browser selection returned no Browser");
    error.code = "R3_E3_BROWSER_CLIENT_INIT_FAILED";
    throw error;
  }
  return { agent: globalThis.agent, browser: globalThis.browser };
}
