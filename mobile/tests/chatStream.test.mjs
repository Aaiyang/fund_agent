import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the actual transport with a controllable XHR, without starting Expo.
const source = readFileSync(new URL('../api/chatStream.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function harness() {
  const requests = [];
  class FakeXHR {
    status = 200;
    statusText = 'OK';
    responseText = '';
    aborts = 0;
    constructor() { requests.push(this); }
    open() {}
    setRequestHeader() {}
    send(body) { this.body = JSON.parse(body); }
    abort() { this.aborts += 1; this.onabort?.(); }
    append(body) { this.responseText += body; this.onprogress?.(); }
  }
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    XMLHttpRequest: FakeXHR,
    require(name) {
      assert.equal(name, '@/api/client');
      return {
        API_BASE_URL: 'http://test',
        apiError: (status) => new Error(`HTTP ${status}`),
      };
    },
  });
  const controller = new globalThis.AbortController();
  const deltas = [];
  const reviews = [];
  const start = (overrides = {}) => exports.streamChatMessage({
    token: 'token', text: '分析基金', signal: controller.signal,
    onDelta: (delta) => deltas.push(delta), onPendingAction: (review) => reviews.push(review),
    ...overrides,
  });
  return { requests, controller, deltas, reviews, start, exports };
}

const frame = (chunk) => `data: ${JSON.stringify(chunk)}\n\n`;

for (const kind of ['holding_import_processing', 'holding_import_account', 'holding_import_review', 'fund_selection']) {
  test(`terminal stream frame preserves the ${kind} action`, async () => {
    const h = harness();
    const pending = h.start({ holdingImportIds: ['batch'] });
    h.requests[0].append(frame({ done: true, content: '', pending_action: { kind, import_id: 'batch', interrupt_id: 'actual' } }));
    h.requests[0].onload();
    await pending;
    assert.equal(h.reviews.length, 1);
    assert.equal(h.reviews[0].kind, kind);
    assert.equal(h.reviews[0].interrupt_id, 'actual');
  });
}

test('progress server error rejects once without escaping the event callback', async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, (error) => {
    assert.ok(error instanceof h.exports.ChatStreamError);
    assert.equal(error.message, '存在没有对应 AI ToolCall 的孤立 ToolMessage');
    return true;
  });
  const xhr = h.requests[0];
  assert.doesNotThrow(() => xhr.append(frame({ done: true, content: '存在没有对应 AI ToolCall 的孤立 ToolMessage' })));
  await rejected;
  assert.equal(xhr.aborts, 1);
  xhr.append(frame({ content: 'late delta' }));
  xhr.onload();
  h.controller.abort();
  assert.equal(xhr.aborts, 1, 'abort listener must be removed');
  assert.deepEqual(h.deltas, []);
});

test('a completed human reply clears the old question even when pending_action is null', async () => {
  const h = harness();
  const pending = h.start();
  h.requests[0].append(frame({ done: false, pending_action: { kind: 'human_question', question: '期限？', interrupt_id: 'actual' } }));
  h.requests[0].append(frame({ done: true, pending_action: null }));
  h.requests[0].onload();
  await pending;
  assert.equal(h.reviews[0].kind, 'human_question');
  assert.equal(h.reviews[1], null);
});

test('arbitrary frame boundaries stream deltas and confirmation exactly once', async () => {
  const h = harness();
  const pending = h.start({ holdingImportIds: ['import-1'] });
  const xhr = h.requests[0];
  const body = frame({ content: '第一段' }) + frame({ pending_action: { id: 'review-1' } })
    + frame({ content: '第二段' }) + frame({ done: true });
  for (let offset = 0; offset < body.length; offset += 7) xhr.append(body.slice(offset, offset + 7));
  xhr.onload();
  await pending;
  assert.deepEqual(h.deltas, ['第一段', '第二段']);
  assert.equal(h.reviews.length, 1);
  assert.deepEqual(xhr.body.holding_import_ids, ['import-1']);
  h.controller.abort();
  assert.equal(xhr.aborts, 0);
});

test('malformed progress frame rejects without an uncaught exception', async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, { name: 'SyntaxError' });
  assert.doesNotThrow(() => h.requests[0].append('data: {broken}\n\n'));
  await rejected;
  assert.equal(h.requests[0].aborts, 1);
});

test('final frame without separator reports the original server error', async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, { name: 'ChatStreamError', message: '工具失败' });
  h.requests[0].append(frame({ done: true, content: '工具失败' }).trimEnd());
  h.requests[0].onload();
  await rejected;
});

test('pre-aborted request opens no connection', async () => {
  const h = harness();
  h.controller.abort();
  await assert.rejects(h.start(), { name: 'AbortError' });
  assert.equal(h.requests.length, 0);
});

test('user stop rejects with AbortError and ignores late data', async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  h.controller.abort();
  h.requests[0].append(frame({ content: 'late' }));
  await rejected;
  assert.deepEqual(h.deltas, []);
});

for (const status of [401, 429, 500]) {
  test(`HTTP ${status} preserves the HTTP error`, async () => {
    const h = harness();
    const pending = h.start();
    const rejected = assert.rejects(pending, { message: `HTTP ${status}` });
    h.requests[0].status = status;
    h.requests[0].append('not SSE or JSON');
    h.requests[0].onload();
    await rejected;
  });
}

for (const event of ['onerror', 'ontimeout']) {
  test(`${event} rejects and cleans up the abort listener`, async () => {
    const h = harness();
    const pending = h.start();
    const rejected = assert.rejects(pending, { message: '连接中断，这条回答没有生成完' });
    h.requests[0][event]();
    await rejected;
    h.controller.abort();
    assert.equal(h.requests[0].aborts, 0);
  });
}
