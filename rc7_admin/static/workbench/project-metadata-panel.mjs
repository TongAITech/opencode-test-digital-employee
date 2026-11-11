const labels = {
  'zh-CN': {
    title: '项目名称', load: '读取当前名称', name: '新名称', reason: '改名原因',
    save: '保存名称', retry: '核对原改名请求', choose: '请选择项目。',
    loading: '正在读取项目名称。', saving: '正在提交改名请求。',
    readOnly: '当前项目只读。', host: '当前宿主未提供写入证明。',
    unknown: '提交结果未知。请用原身份核对原请求。',
    changed: '原改名操作已确认。', unchanged: '名称相同，已确认无需改名。',
    failure: '无法完成请求。', conflict: '项目版本已变化，请读取当前名称后重新填写。',
    unavailable: '名称不可用。', exhausted: '名称版本已达上限，无法改名。', denied: '当前权限或身份无法执行此操作。',
    invalid: '请检查名称和改名原因的长度及字符。',
    policy: '名称最多128个Unicode标量、512个UTF-8字节。只去除首尾普通空格（U+0020）。大小写、组合字符及其他Unicode空白原样保留。',
  },
  'en-US': {
    title: 'Project name', load: 'Read current name', name: 'New name', reason: 'Reason for renaming',
    save: 'Save name', retry: 'Check original rename request', choose: 'Choose a project.',
    loading: 'Reading the project name.', saving: 'Submitting the rename request.',
    readOnly: 'This project is read-only.', host: 'The current host has not supplied write proof.',
    unknown: 'The outcome is unknown. Check the original request with the original identity.',
    changed: 'The original rename was confirmed.', unchanged: 'The name was unchanged.',
    failure: 'The request could not be completed.', conflict: 'The project revision changed. Read the current name and enter a new request.',
    unavailable: 'Name unavailable.', exhausted: 'The name revision has reached its limit. The rename was rejected.', denied: 'The current permissions or identity do not allow this operation.',
    invalid: 'Check the length and characters of the name and reason.',
    policy: 'Up to 128 Unicode scalar values and 512 UTF-8 bytes. Only leading and trailing ordinary spaces (U+0020) are removed. Case, combining characters and other Unicode whitespace are preserved.',
  },
};
const encoder = new TextEncoder();
const maxRevision = '9223372036854775807';

function revision(value) {
  return typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value)
    && (value.length < maxRevision.length || value <= maxRevision);
}

function canonicalName(value) {
  return value.replace(/^ +| +$/g, '');
}

function validName(value) {
  if (/[\u0000-\u001f\u007f\ud800-\udfff]/u.test(value)) return false;
  const name = canonicalName(value);
  return name.length > 0 && [...name].length <= 128 && encoder.encode(name).length <= 512;
}

function validMetadata(value, project) {
  return value?.schema === 'project-metadata/v1' && value.project_id === project
    && typeof value.name === 'string' && revision(value.metadata_revision)
    && revision(value.access_scope_revision)
    && (value.can_rename === undefined || typeof value.can_rename === 'boolean')
    && ['GOVERNED_ROOT_ACTIVE', 'METADATA_NOT_GOVERNED', 'GOVERNANCE_HOLD'].includes(value.governance_state);
}

function validReceipt(value, intent) {
  return value?.schema === 'project-metadata-receipt/v1'
    && value.project_id === intent.project && value.request_id === intent.requestId
    && value.action === 'project.metadata.update/v1'
    && value.name === intent.name && revision(value.applied_metadata_revision)
    && value.access_scope_revision === intent.accessRevision && revision(value.audit_id)
    && ((value.outcome === 'APPLIED' && value.history_revision === value.applied_metadata_revision
        && BigInt(value.applied_metadata_revision) === BigInt(intent.metadataRevision) + 1n)
      || (value.outcome === 'NO_CHANGE' && value.history_revision === null
        && value.applied_metadata_revision === intent.metadataRevision));
}

const invalidRequestCodes = [
  'INVALID_METADATA_TARGET', 'INVALID_METADATA_QUERY', 'INVALID_METADATA_BODY',
  'INCOMPLETE_METADATA_BODY', 'INVALID_METADATA_REQUEST', 'INVALID_METADATA_CANONICAL',
  'PROJECT_TARGET_INVALID', 'BODY_BYTES_REQUIRED', 'BODY_BYTE_LIMIT',
  'JSON_INVALID_UTF8', 'JSON_INVALID', 'JSON_INVALID_UNICODE', 'JSON_DUPLICATE_KEY',
  'JSON_NUMBER_FORBIDDEN', 'REQUEST_FIELDS_INVALID', 'CHANGES_FIELDS_INVALID',
  'REQUEST_ID_INVALID', 'REVISION_INVALID', 'NAME_INVALID_UTF8_OR_TYPE',
  'NAME_CONTROL_FORBIDDEN', 'NAME_SCALAR_LIMIT', 'NAME_BYTE_LIMIT', 'NAME_NOT_CANONICAL',
  'REASON_INVALID_UTF8_OR_TYPE', 'REASON_BYTE_LIMIT',
];
const knownRejections = new Map([
  ...invalidRequestCodes.map(code => ['400:' + code, 'invalid']),
  ['409:NAME_UNAVAILABLE', 'unavailable'],
  ['409:REVISION_EXHAUSTED', 'exhausted'],
  ['409:REVISION_CONFLICT', 'conflict'],
  ['409:WRITE_CONTEXT_CHANGED', 'denied'],
  ['409:METADATA_NOT_GOVERNED', 'readOnly'],
  ['409:GOVERNANCE_HOLD', 'readOnly'],
  ['409:IDEMPOTENCY_CONFLICT', 'conflict'],
  ['403:FORBIDDEN', 'denied'],
  ['403:WRITE_CONTEXT_REQUIRED', 'denied'],
  ['403:MUTATION_AUTH_REQUIRED', 'denied'],
]);

export function mountProjectMetadata(root, {
  getProject, getView, refreshDirectory, clearUnauthorized,
  fetcher = fetch, csrf = () => document.querySelector('meta[name="dsh-csrf-token"]')?.content,
}) {
  root.innerHTML = `<h3 data-title></h3><p data-current></p>
    <button type="button" data-load></button>
    <form hidden><label><span data-name></span><input name="project-name" aria-describedby="project-name-policy" required></label>
      <p id="project-name-policy"></p>
      <label><span data-reason></span><textarea name="rename-reason"></textarea></label>
      <button type="submit" data-save></button></form>
    <button type="button" data-check hidden></button><p data-status role="status"></p>`;
  const find = selector => root.querySelector(selector);
  const name = find('[name=project-name]');
  const reason = find('[name=rename-reason]');
  const form = find('form');
  const load = find('[data-load]');
  const check = find('[data-check]');
  const pending = new Map();
  const submitting = new Set();
  let project = '', generation = 0, metadata = null, subject = null, busy = false, notice = '', confirmed = '';

  function render() {
    const t = labels[document.documentElement.lang] || labels['zh-CN'];
    const unknown = pending.has(project);
    const canRename = metadata?.governance_state === 'GOVERNED_ROOT_ACTIVE' && metadata.can_rename === true;
    const writable = canRename && subject && csrf();
    root.hidden = !project && !(getView().page === 'detail' && getView().section === 'overview');
    find('[data-title]').textContent = t.title;
    find('[data-current]').textContent = metadata?.name ?? '';
    find('[data-name]').textContent = t.name;
    find('[data-reason]').textContent = t.reason;
    find('#project-name-policy').textContent = t.policy;
    find('[data-save]').textContent = t.save;
    load.textContent = t.load;
    load.disabled = !project || busy;
    form.hidden = !writable || unknown;
    find('[data-save]').disabled = busy;
    name.disabled = reason.disabled = busy;
    check.textContent = t.retry;
    check.hidden = !unknown;
    check.disabled = busy || submitting.has(project) || !csrf();
    const status = [confirmed, notice || (!project ? 'choose' : metadata && !writable
      ? (canRename ? 'host' : 'readOnly') : ''),
    unknown && !busy ? 'unknown' : ''].filter(Boolean);
    find('[data-status]').textContent = status.map(key => t[key]).join(' ');
    root.dataset.metadataStatus = unknown ? 'UNKNOWN' : busy ? 'LOADING' : metadata ? 'READY' : 'NOT_READY';
  }

  function sync() {
    const view = getView();
    const next = view.page === 'detail' && view.section === 'overview' ? getProject() : '';
    if (next !== project) {
      generation++;
      project = next;
      metadata = null;
      subject = null;
      notice = confirmed = '';
      busy = false;
      form.reset();
    }
    render();
  }

  async function request(path, options = {}) {
    const response = await fetcher(path, {
      credentials: 'same-origin', redirect: 'error', cache: 'no-store', ...options,
      headers: {Accept: 'application/json', ...options.headers},
    });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error('METADATA_HTTP_ERROR');
      error.status = response.status;
      error.code = value?.error?.code;
      throw error;
    }
    return value;
  }

  async function readSubject() {
    const value = await request('/api/workbench/v1/write-context');
    if (value?.schema !== 'dsh-workbench/write-context/v1'
        || typeof value.write_context !== 'string' || !value.write_context) throw new Error('INVALID_CONTEXT');
    return value.write_context;
  }

  function path(target) {
    return '/api/workbench/v1/projects/' + encodeURIComponent(target) + '/metadata';
  }

  async function readCurrent({refresh = false} = {}) {
    if (!project || busy) return;
    const target = project;
    const epoch = ++generation;
    metadata = null;
    subject = null;
    form.reset();
    notice = 'loading';
    busy = true;
    render();
    try {
      const before = csrf() ? await readSubject().catch(() => null) : null;
      const current = await request(path(target));
      const after = before ? await readSubject().catch(() => null) : null;
      if (epoch !== generation) return;
      if (!validMetadata(current, target) || before !== after) throw new Error('INVALID_METADATA');
      metadata = current;
      subject = after;
      name.value = current.name;
      notice = '';
      if (refresh) await refreshDirectory();
    } catch (error) {
      if (epoch !== generation) return;
      notice = error.status === 403 ? 'denied' : 'failure';
      if (error.status === 403) clearUnauthorized(target);
    } finally {
      if (epoch === generation) {
        busy = false;
        render();
      }
    }
  }

  async function submit(intent, recovering) {
    if (!csrf() || submitting.has(intent.project)) return;
    const epoch = generation;
    submitting.add(intent.project);
    busy = true;
    notice = 'saving';
    confirmed = '';
    render();
    try {
      const currentSubject = await readSubject();
      if (epoch !== generation) return;
      if (currentSubject !== intent.subject) {
        metadata = null;
        subject = null;
        form.reset();
        notice = 'denied';
        return;
      }
      const proof = csrf();
      if (!proof) {
        notice = 'host';
        return;
      }
      pending.set(intent.project, intent);
      const receipt = await request(path(intent.project), {method: 'PATCH', body: intent.body,
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': proof,
          'X-DSH-Write-Context': intent.subject}});
      if (epoch !== generation) return;
      if (!validReceipt(receipt, intent)) throw new Error('INVALID_RECEIPT');
      const receivingSubject = await readSubject().catch(() => null);
      if (epoch !== generation) return;
      if (receivingSubject !== intent.subject) {
        metadata = null;
        subject = null;
        form.reset();
        notice = 'denied';
        return;
      }
      pending.delete(intent.project);
      confirmed = receipt.outcome === 'NO_CHANGE' ? 'unchanged' : 'changed';
      busy = false;
      await readCurrent({refresh: true});
    } catch (error) {
      if (epoch !== generation) return;
      const rejection = knownRejections.get(error.status + ':' + error.code);
      if (!recovering && rejection) pending.delete(intent.project);
      notice = rejection || (pending.has(intent.project) ? '' : 'failure');
      if (pending.has(intent.project) || rejection === 'denied' || rejection === 'conflict' || rejection === 'readOnly') {
        metadata = null;
        subject = null;
        form.reset();
      }
    } finally {
      submitting.delete(intent.project);
      if (epoch === generation) busy = false;
      render();
    }
  }

  form.onsubmit = event => {
    event.preventDefault();
    if (!metadata || metadata.governance_state !== 'GOVERNED_ROOT_ACTIVE'
        || metadata.can_rename !== true || !subject || busy || pending.has(project)) return;
    if (!validName(name.value) || /[\ud800-\udfff]/u.test(reason.value)
        || encoder.encode(reason.value).length > 2048) {
      notice = 'invalid';
      render();
      return;
    }
    const requestId = crypto.randomUUID();
    const body = JSON.stringify({request_id: requestId,
      expected_metadata_revision: metadata.metadata_revision,
      expected_access_scope_revision: metadata.access_scope_revision,
      changes: {name: name.value}, reason: reason.value});
    if (encoder.encode(body).length > 16384) {
      notice = 'invalid';
      render();
      return;
    }
    void submit(Object.freeze({project, requestId, body, subject,
      name: canonicalName(name.value), metadataRevision: metadata.metadata_revision,
      accessRevision: metadata.access_scope_revision}), false);
  };
  check.onclick = () => {
    const intent = pending.get(project);
    if (intent && !busy) void submit(intent, true);
  };
  load.onclick = () => {
    confirmed = '';
    void readCurrent();
  };
  document.addEventListener('workbench-scope-changed', sync);
  document.addEventListener('workbench-view-changed', sync);
  sync();
}
