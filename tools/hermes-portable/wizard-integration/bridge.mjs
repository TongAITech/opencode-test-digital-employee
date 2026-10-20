import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const HOST = '127.0.0.1';
const PORT = Number(process.env.WIZARD_BRIDGE_PORT || 17891);
const UPSTREAM = (process.env.WIZARD_UPSTREAM_BASE_URL || 'https://wizard-ai.paic.com.cn/code_pilot/api/v1').replace(/\/$/, '');
const MODEL = process.env.WIZARD_MODEL || 'aicoder-plus';
const CONTEXT_LENGTH = Number(process.env.WIZARD_CONTEXT_LENGTH || 148000);
const PLUGIN_DIR = process.env.WIZARD_PLUGIN_DIR || '';
const SESSION_ID = crypto.randomUUID();
const USER_ID = process.env.WIZARD_HARNESS_USER_ID || crypto.randomUUID();
const require = createRequire(import.meta.url);

let currentTicket = null;
let loginPromise = null;
let cachedKey = null;
let cachedKeyExpires = 0;
let pluginState = null;

function json(res, code, value) {
  const body = Buffer.from(JSON.stringify(value));
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(body.length),
    'cache-control': 'no-store'
  });
  res.end(body);
}

function safeState() {
  return {
    cas: currentTicket ? 'READY' : (loginPromise ? 'PENDING' : 'NOT_AUTHENTICATED'),
    ticket: currentTicket ? 'PRESENT' : 'ABSENT',
    apiKey: cachedKey && Date.now() < cachedKeyExpires - 5000 ? 'READY' : 'NOT_READY',
    expiresInMs: cachedKeyExpires > Date.now() ? cachedKeyExpires - Date.now() : 0,
    pluginDir: PLUGIN_DIR || null,
    pluginLoaded: !!pluginState,
    model: MODEL,
    contextLength: CONTEXT_LENGTH
  };
}

function assertPluginDir() {
  if (!PLUGIN_DIR) throw new Error('WIZARD_PLUGIN_DIR is not set');
  const loginJs = path.join(PLUGIN_DIR, 'lib', 'login.js');
  const addon = path.join(PLUGIN_DIR, 'wkey.x86_64-pc-windows-msvc.node');
  if (!fs.existsSync(loginJs)) throw new Error(`Missing ${loginJs}`);
  if (!fs.existsSync(addon)) throw new Error(`Missing ${addon}`);
  return { loginJs, addon };
}

async function loadPlugin() {
  if (pluginState) return pluginState;
  const { loginJs, addon } = assertPluginDir();
  const loginModule = await import(pathToFileURL(loginJs).href);
  if (typeof loginModule.startCasLogin !== 'function') throw new Error('login.js does not export startCasLogin');
  const native = require(addon);
  if (typeof native.createPowChallenge !== 'function') throw new Error('wkey addon missing createPowChallenge');
  if (typeof native.generateApiKey !== 'function') throw new Error('wkey addon missing generateApiKey');
  pluginState = { startCasLogin: loginModule.startCasLogin, native };
  return pluginState;
}

function solvePow(ticket, nonce, difficulty) {
  const target = '0'.repeat(Number(difficulty || 0));
  let answer = 0;
  while (true) {
    const digest = crypto.createHash('sha256').update(`${ticket}:${nonce}:${answer}`).digest('hex');
    if (digest.startsWith(target)) return String(answer);
    answer += 1;
    if (answer > 10_000_000) throw new Error('PoW solver exceeded 10M iterations');
  }
}

async function ensureTicket() {
  if (currentTicket) return currentTicket;
  if (loginPromise) return loginPromise;
  const { startCasLogin } = await loadPlugin();
  loginPromise = startCasLogin({ log: (line) => console.log(`[cas] ${line}`) })
    .then((ticket) => {
      currentTicket = ticket;
      cachedKey = null;
      cachedKeyExpires = 0;
      return ticket;
    })
    .finally(() => { loginPromise = null; });
  return loginPromise;
}

async function resolveApiKey() {
  const now = Date.now();
  if (cachedKey && now < cachedKeyExpires - 5000) return cachedKey;
  const ticket = await ensureTicket();
  const { native } = await loadPlugin();
  const challenge = native.createPowChallenge();
  const answer = solvePow(ticket, challenge.nonce, challenge.difficulty);
  const result = native.generateApiKey({
    ticket,
    nonce: challenge.nonce,
    difficulty: challenge.difficulty,
    issuedAt: challenge.issuedAt,
    expiresAt: challenge.expiresAt,
    signature: challenge.signature,
    answer
  });
  if (!result || !result.apiKey) throw new Error('wkey generateApiKey returned no apiKey');
  cachedKey = result.apiKey;
  cachedKeyExpires = parseInt(challenge.expiresAt, 10) || (Date.now() + 60_000);
  return cachedKey;
}

function invalidateAuth() {
  currentTicket = null;
  loginPromise = null;
  cachedKey = null;
  cachedKeyExpires = 0;
}

async function readBody(req, max = 32 * 1024 * 1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > max) throw new Error('request body too large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function containsImage(value) {
  if (!value || typeof value !== 'object') return false;
  if (Array.isArray(value)) return value.some(containsImage);
  if (value.type === 'image' || value.type === 'image_url' || value.image_url) return true;
  return Object.values(value).some(containsImage);
}

async function upstreamFetch(bodyBuffer, incomingHeaders, retry = 0) {
  const apiKey = await resolveApiKey();
  const headers = {
    'authorization': `Bearer ${apiKey}`,
    'content-type': 'application/json',
    'accept': incomingHeaders['accept'] || 'text/event-stream',
    'x-wizard-harness-user-id': USER_ID,
    'x-wizard-harness-session-id': SESSION_ID
  };
  if (process.env.WIZARD_EXTRA_HEADERS_JSON) {
    try { Object.assign(headers, JSON.parse(process.env.WIZARD_EXTRA_HEADERS_JSON)); } catch { }
  }
  const response = await fetch(`${UPSTREAM}/chat/completions`, {
    method: 'POST',
    headers,
    body: bodyBuffer
  });
  if ((response.status === 401 || response.status === 403) && retry === 0) {
    invalidateAuth();
    await ensureTicket();
    return upstreamFetch(bodyBuffer, incomingHeaders, 1);
  }
  return response;
}

async function proxyChat(req, res) {
  const body = await readBody(req);
  let parsed;
  try { parsed = JSON.parse(body.toString('utf8')); } catch { return json(res, 400, { error: { message: 'invalid JSON', code: 'INVALID_JSON' } }); }
  if (containsImage(parsed)) return json(res, 400, { error: { message: 'aicoder-plus is configured as text-only in this bank bridge', code: 'UNSUPPORTED_CONTENT' } });
  const response = await upstreamFetch(body, req.headers, 0);
  const outHeaders = {};
  for (const name of ['content-type', 'cache-control', 'x-request-id', 'retry-after']) {
    const v = response.headers.get(name);
    if (v) outHeaders[name] = v;
  }
  res.writeHead(response.status, outHeaders);
  if (!response.body) return res.end();
  const reader = response.body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!res.write(Buffer.from(value))) await new Promise((resolve) => res.once('drain', resolve));
    }
  } finally {
    try { reader.releaseLock(); } catch { }
    res.end();
  }
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${HOST}:${PORT}`);
    if (req.method === 'GET' && url.pathname === '/health') return json(res, 200, { status: 'UP', ...safeState() });
    if (req.method === 'GET' && url.pathname === '/auth/status') return json(res, 200, safeState());
    if ((req.method === 'GET' || req.method === 'POST') && url.pathname === '/auth/login') {
      await ensureTicket();
      await resolveApiKey();
      return json(res, 200, safeState());
    }
    if (req.method === 'POST' && url.pathname === '/auth/invalidate') {
      invalidateAuth();
      return json(res, 200, safeState());
    }
    if (req.method === 'GET' && url.pathname === '/v1/models') {
      return json(res, 200, { object: 'list', data: [{ id: MODEL, object: 'model', owned_by: 'wizard-bank', context_length: CONTEXT_LENGTH }] });
    }
    if (req.method === 'POST' && url.pathname === '/v1/chat/completions') return await proxyChat(req, res);
    return json(res, 404, { error: { message: 'not found', code: 'NOT_FOUND' } });
  } catch (error) {
    console.error('[bridge]', error?.stack || error);
    if (!res.headersSent) return json(res, 500, { error: { message: String(error?.message || error), code: 'BRIDGE_ERROR' } });
    try { res.end(); } catch { }
  }
});

server.listen(PORT, HOST, () => {
  console.log(`WIZARD_BRIDGE_READY http://${HOST}:${PORT}`);
  console.log(`PLUGIN_DIR=${PLUGIN_DIR || '<unset>'}`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => server.close(() => process.exit(0)));
}
