const addonPath = process.argv[2];
const loginPath = process.argv[3];
(async () => {
  try {
    if (typeof fetch !== 'function') throw new Error('global fetch unavailable');
    const a = require(addonPath);
    if (typeof a.createPowChallenge !== 'function') throw new Error('createPowChallenge missing');
    if (typeof a.generateApiKey !== 'function') throw new Error('generateApiKey missing');
    const { pathToFileURL } = require('node:url');
    const m = await import(pathToFileURL(loginPath).href);
    if (typeof m.startCasLogin !== 'function') throw new Error('startCasLogin missing');
    process.stdout.write('WKEY_NODE_COMPATIBLE\n');
  } catch (e) {
    process.stderr.write(String(e && e.stack || e) + '\n');
    process.exit(8);
  }
})();
