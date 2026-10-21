import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const HOST = '127.0.0.1';
const PORT = Number(process.env.BANK_MODEL_GATEWAY_PORT || 17891);
const HERMES_HOME = process.env.HERMES_HOME || 'R:\\hermes';
const PLUGIN_DIR = process.env.WIZARD_PLUGIN_DIR || '';
const WIZARD_UPSTREAM = (process.env.WIZARD_UPSTREAM_BASE_URL || 'https://wizard-ai.paic.com.cn/code_pilot/api/v1').replace(/\/$/, '');
const WIZARD_MODEL = process.env.WIZARD_MODEL || 'aicoder-plus';
const BANKGPT_UPSTREAM = (process.env.BANKGPT_BASE_URL || '').replace(/\/$/, '');
const BANKGPT_API_KEY = process.env.BANKGPT_API_KEY || '';
const BANKGPT_MODEL = process.env.BANKGPT_MODEL || 'wizard-bankgpt';
const TZ_OFFSET_MINUTES = Number(process.env.BANK_TZ_OFFSET_MINUTES || 480);
const REQUEST_LIMIT_10_MIN = Number(process.env.BANK_MODEL_REQUEST_LIMIT_10MIN || 100);
const REQUEST_SAFETY_LIMIT_10_MIN = Number(process.env.BANK_MODEL_REQUEST_SAFETY_LIMIT_10MIN || 90);
const QUOTA_09_18 = Number(process.env.BANK_MODEL_QUOTA_09_18 || 40000000);
const QUOTA_18_21 = Number(process.env.BANK_MODEL_QUOTA_18_21 || 40000000);
const R1 = path.join(HERMES_HOME, 'runtime-state', 'r1', 'event-stream.jsonl');
const BUDGET_FILE = path.join(HERMES_HOME, 'runtime-state', 'model-budget.json');
const require = createRequire(import.meta.url);

let currentTicket = null;
let loginPromise = null;
let cachedKey = null;
let cachedKeyExpires = 0;
let pluginState = null;
const sessionId = crypto.randomUUID();
const userId = process.env.WIZARD_HARNESS_USER_ID || crypto.randomUUID();

function ensureDir(p) { fs.mkdirSync(path.dirname(p), { recursive: true }); }
function appendR1(type, payload = {}) {
  try {
    ensureDir(R1);
    fs.appendFileSync(R1, JSON.stringify({ ts: new Date().toISOString(), event_type: type, session_id: sessionId, ...payload }) + '\n');
  } catch {}
}
function json(res, code, body, extra = {}) {
  const data = Buffer.from(JSON.stringify(body));
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', 'content-length': String(data.length), 'cache-control': 'no-store', ...extra });
  res.end(data);
}

function defaultBudgetState() { return { request_ts: [], token_windows: {} }; }
function loadBudget() {
  try {
    const x = JSON.parse(fs.readFileSync(BUDGET_FILE, 'utf8'));
    return x && typeof x === 'object' ? x : defaultBudgetState();
  } catch { return defaultBudgetState(); }
}
function saveBudget(s) {
  try {
    ensureDir(BUDGET_FILE);
    const tmp = BUDGET_FILE + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(s, null, 2));
    fs.renameSync(tmp, BUDGET_FILE);
  } catch {}
}
function bankClock(now = Date.now()) {
  const d = new Date(now + TZ_OFFSET_MINUTES * 60000);
  return { date: d.toISOString().slice(0, 10), hour: d.getUTCHours(), minute: d.getUTCMinutes() };
}
function quotaWindow(now = Date.now()) {
  const t = bankClock(now);
  if (t.hour >= 9 && t.hour < 18) return { key: `${t.date}:09-18`, limit: QUOTA_09_18, name: '09:00-18:00' };
  if (t.hour >= 18 && t.hour < 21) return { key: `${t.date}:18-21`, limit: QUOTA_18_21, name: '18:00-21:00' };
  return { key: `${t.date}:OFFPEAK`, limit: null, name: '21:00-09:00' };
}
function budgetStatus() {
  const now = Date.now();
  const s = loadBudget();
  s.request_ts = (s.request_ts || []).filter(x => now - x < 600000);
  const w = quotaWindow(now);
  const used = Number((s.token_windows || {})[w.key] || 0);
  return {
    request_limit_10min: REQUEST_LIMIT_10_MIN,
    safety_limit_10min: REQUEST_SAFETY_LIMIT_10_MIN,
    requests_last_10min: s.request_ts.length,
    quota_window: w.name,
    quota_limit_tokens: w.limit,
    quota_used_tokens: used,
    quota_remaining_tokens: w.limit == null ? null : Math.max(0, w.limit - used),
    offpeak_unlimited: w.limit == null,
  };
}
async function acquireBudget(provider) {
  while (true) {
    const now = Date.now();
    const s = loadBudget();
    s.request_ts = (s.request_ts || []).filter(x => now - x < 600000);
    const w = quotaWindow(now);
    const used = Number((s.token_windows || {})[w.key] || 0);
    if (w.limit != null && used >= w.limit) {
      const err = new Error(`model quota exhausted for ${w.name}`); err.status = 429; err.retryAfter = 600; throw err;
    }
    if (s.request_ts.length < REQUEST_SAFETY_LIMIT_10_MIN) {
      s.request_ts.push(now); saveBudget(s);
      appendR1('MODEL_REQUEST_ADMITTED', { provider, budget: budgetStatus() });
      return;
    }
    const oldest = Math.min(...s.request_ts);
    const wait = Math.max(1000, Math.min(600000, oldest + 600000 - now + 250));
    appendR1('MODEL_REQUEST_THROTTLED', { provider, wait_ms: wait, requests_last_10min: s.request_ts.length });
    await new Promise(r => setTimeout(r, wait));
  }
}
function addUsage(tokens, provider) {
  if (!Number.isFinite(tokens) || tokens <= 0) return;
  const s = loadBudget();
  const w = quotaWindow();
  s.token_windows ||= {};
  s.token_windows[w.key] = Number(s.token_windows[w.key] || 0) + Math.ceil(tokens);
  saveBudget(s);
  appendR1('MODEL_USAGE_ACCOUNTED', { provider, total_tokens: Math.ceil(tokens), window: w.name, used: s.token_windows[w.key] });
}

function pluginFiles() {
  if (!PLUGIN_DIR) throw new Error('WIZARD_PLUGIN_DIR is not set');
  const loginJs = path.join(PLUGIN_DIR, 'lib', 'login.js');
  const addon = path.join(PLUGIN_DIR, 'wkey.x86_64-pc-windows-msvc.node');
  if (!fs.existsSync(loginJs)) throw new Error(`missing ${loginJs}`);
  if (!fs.existsSync(addon)) throw new Error(`missing ${addon}`);
  return { loginJs, addon };
}
async function loadPlugin() {
  if (pluginState) return pluginState;
  const { loginJs, addon } = pluginFiles();
  const mod = await import(pathToFileURL(loginJs).href);
  if (typeof mod.startCasLogin !== 'function') throw new Error('login.js does not export startCasLogin');
  const native = require(addon);
  if (typeof native.createPowChallenge !== 'function' || typeof native.generateApiKey !== 'function') throw new Error('wkey addon API mismatch');
  pluginState = { startCasLogin: mod.startCasLogin, native };
  return pluginState;
}
function solvePow(ticket, nonce, difficulty) {
  const target = '0'.repeat(Number(difficulty || 0));
  let answer = 0;
  while (true) {
    const digest = crypto.createHash('sha256').update(`${ticket}:${nonce}:${answer}`).digest('hex');
    if (digest.startsWith(target)) return String(answer);
    if (++answer > 10000000) throw new Error('PoW solver exceeded 10M iterations');
  }
}
async function ensureTicket() {
  if (currentTicket) return currentTicket;
  if (loginPromise) return loginPromise;
  const { startCasLogin } = await loadPlugin();
  appendR1('WIZARD_CAS_LOGIN_STARTED');
  loginPromise = startCasLogin({ log: line => console.log(`[cas] ${line}`) })
    .then(ticket => { currentTicket = ticket; cachedKey = null; cachedKeyExpires = 0; appendR1('WIZARD_CAS_LOGIN_SUCCEEDED'); return ticket; })
    .finally(() => { loginPromise = null; });
  return loginPromise;
}
async function wizardApiKey() {
  const now = Date.now();
  if (cachedKey && now < cachedKeyExpires - 5000) return cachedKey;
  const ticket = await ensureTicket();
  const { native } = await loadPlugin();
  const c = native.createPowChallenge();
  const answer = solvePow(ticket, c.nonce, c.difficulty);
  const result = native.generateApiKey(ticket, c.nonce, c.difficulty, c.issuedAt, c.expiresAt, c.signature, answer);
  if (!result?.apiKey) throw new Error('wkey generateApiKey returned no apiKey');
  cachedKey = result.apiKey;
  cachedKeyExpires = parseInt(c.expiresAt, 10) || (Date.now() + 60000);
  appendR1('WIZARD_API_KEY_REFRESHED', { expires_at: cachedKeyExpires });
  return cachedKey;
}
function invalidateWizard() { currentTicket = null; loginPromise = null; cachedKey = null; cachedKeyExpires = 0; appendR1('WIZARD_AUTH_INVALIDATED'); }

function containsActualImage(messages) {
  if (!Array.isArray(messages)) return false;
  for (const message of messages) {
    const content = message?.content;
    if (typeof content === 'string' || content == null) continue;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      if (!part || typeof part !== 'object') continue;
      const type = String(part.type || '').toLowerCase();
      if (type === 'image' || type === 'image_url' || type === 'input_image' || part.image_url != null || part.image != null) return true;
    }
  }
  return false;
}
async function readBody(req, max = 64 * 1024 * 1024) {
  const chunks = []; let n = 0;
  for await (const c of req) { n += c.length; if (n > max) throw new Error('request body too large'); chunks.push(c); }
  return Buffer.concat(chunks);
}
function usageFromJson(obj) {
  const u = obj?.usage || {};
  const total = Number(u.total_tokens ?? ((u.prompt_tokens || 0) + (u.completion_tokens || 0)));
  return Number.isFinite(total) && total > 0 ? total : 0;
}
async function upstream(provider, body, incomingHeaders, retry = 0) {
  await acquireBudget(provider);
  let base, model, auth;
  const headers = { 'content-type': 'application/json', accept: incomingHeaders.accept || 'text/event-stream' };
  if (provider === 'wizard') {
    base = WIZARD_UPSTREAM; model = WIZARD_MODEL; auth = await wizardApiKey();
    headers['x-wizard-harness-user-id'] = userId;
    headers['x-wizard-harness-session-id'] = sessionId;
  } else {
    if (!BANKGPT_UPSTREAM || !BANKGPT_API_KEY) throw new Error('BankGPT is not configured on this PC');
    base = BANKGPT_UPSTREAM; model = BANKGPT_MODEL; auth = BANKGPT_API_KEY;
  }
  headers.authorization = `Bearer ${auth}`;
  let parsed = JSON.parse(body.toString('utf8'));
  if (!parsed.model) parsed.model = model;
  const payload = Buffer.from(JSON.stringify(parsed));
  const response = await fetch(`${base}/chat/completions`, { method: 'POST', headers, body: payload });
  if (provider === 'wizard' && (response.status === 401 || response.status === 403) && retry === 0) {
    invalidateWizard(); await ensureTicket(); return upstream(provider, body, incomingHeaders, 1);
  }
  return response;
}
async function pipeAndAccount(response, res, provider) {
  const out = {};
  for (const h of ['content-type', 'cache-control', 'x-request-id', 'retry-after']) { const v = response.headers.get(h); if (v) out[h] = v; }
  res.writeHead(response.status, out);
  if (!response.body) return res.end();
  const isSse = (response.headers.get('content-type') || '').includes('text/event-stream');
  const reader = response.body.getReader();
  let textBuf = ''; let bytes = 0; let maxUsage = 0; const jsonChunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      const b = Buffer.from(value); bytes += b.length;
      if (isSse) {
        textBuf += b.toString('utf8');
        const lines = textBuf.split(/\r?\n/); textBuf = lines.pop() || '';
        for (const line of lines) if (line.startsWith('data:')) {
          const raw = line.slice(5).trim(); if (!raw || raw === '[DONE]') continue;
          try { maxUsage = Math.max(maxUsage, usageFromJson(JSON.parse(raw))); } catch {}
        }
      } else if (jsonChunks.reduce((a, x) => a + x.length, 0) < 8 * 1024 * 1024) jsonChunks.push(b);
      if (!res.write(b)) await new Promise(r => res.once('drain', r));
    }
  } finally { try { reader.releaseLock(); } catch {} res.end(); }
  if (!isSse && jsonChunks.length) { try { maxUsage = Math.max(maxUsage, usageFromJson(JSON.parse(Buffer.concat(jsonChunks).toString('utf8')))); } catch {} }
  if (!maxUsage) maxUsage = Math.ceil(bytes / 4);
  addUsage(maxUsage, provider);
}
async function chat(provider, req, res) {
  const body = await readBody(req);
  let parsed; try { parsed = JSON.parse(body.toString('utf8')); } catch { return json(res, 400, { error: { code: 'INVALID_JSON', message: 'invalid JSON' } }); }
  if (provider === 'wizard' && containsActualImage(parsed.messages)) return json(res, 400, { error: { code: 'UNSUPPORTED_CONTENT', message: 'aicoder-plus is text-only; use accessibility/DOM paths instead of image input' } });
  const response = await upstream(provider, body, req.headers, 0);
  appendR1('MODEL_RESPONSE_HEADERS', { provider, status: response.status, request_id: response.headers.get('x-request-id') || null });
  return pipeAndAccount(response, res, provider);
}

const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, `http://${HOST}:${PORT}`);
    if (req.method === 'GET' && u.pathname === '/health') return json(res, 200, { status: 'UP', session_id: sessionId, budget: budgetStatus(), wizard: { ticket: !!currentTicket, api_key: !!cachedKey }, bankgpt_configured: !!(BANKGPT_UPSTREAM && BANKGPT_API_KEY) });
    if (req.method === 'GET' && u.pathname === '/budget/status') return json(res, 200, budgetStatus());
    if (req.method === 'GET' && u.pathname === '/auth/status') return json(res, 200, { cas: currentTicket ? 'READY' : (loginPromise ? 'PENDING' : 'NOT_AUTHENTICATED'), ticket: currentTicket ? 'PRESENT' : 'ABSENT', apiKey: cachedKey && Date.now() < cachedKeyExpires - 5000 ? 'READY' : 'NOT_READY' });
    if ((req.method === 'GET' || req.method === 'POST') && u.pathname === '/auth/login') { await ensureTicket(); await wizardApiKey(); return json(res, 200, { cas: 'READY', ticket: 'PRESENT', apiKey: 'READY' }); }
    if (req.method === 'POST' && u.pathname === '/auth/invalidate') { invalidateWizard(); return json(res, 200, { ok: true }); }
    if (req.method === 'GET' && u.pathname === '/wizard/v1/models') return json(res, 200, { object: 'list', data: [{ id: WIZARD_MODEL, object: 'model', owned_by: 'wizard-bank', context_length: 148000 }] });
    if (req.method === 'GET' && u.pathname === '/bankgpt/v1/models') return json(res, 200, { object: 'list', data: [{ id: BANKGPT_MODEL, object: 'model', owned_by: 'bankgpt', context_length: 256000 }] });
    if (req.method === 'POST' && u.pathname === '/wizard/v1/chat/completions') return chat('wizard', req, res);
    if (req.method === 'POST' && u.pathname === '/bankgpt/v1/chat/completions') return chat('bankgpt', req, res);
    return json(res, 404, { error: { code: 'NOT_FOUND', message: 'not found' } });
  } catch (e) {
    const code = Number(e?.status || 500);
    appendR1('MODEL_GATEWAY_ERROR', { code, message: String(e?.message || e) });
    if (!res.headersSent) return json(res, code, { error: { code: code === 429 ? 'RATE_OR_QUOTA_LIMIT' : 'GATEWAY_ERROR', message: String(e?.message || e) } }, e?.retryAfter ? { 'retry-after': String(e.retryAfter) } : {});
    try { res.end(); } catch {}
  }
});

server.listen(PORT, HOST, () => {
  appendR1('BANK_MODEL_GATEWAY_STARTED', { host: HOST, port: PORT, request_limit_10min: REQUEST_LIMIT_10_MIN, safety_limit_10min: REQUEST_SAFETY_LIMIT_10_MIN, quota_09_18: QUOTA_09_18, quota_18_21: QUOTA_18_21 });
  console.log(`BANK_MODEL_GATEWAY_READY http://${HOST}:${PORT}`);
});
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => server.close(() => process.exit(0)));
