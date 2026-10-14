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
    open(method, url) { this.method = method; this.url = url; }
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

test('research follow-up uses a report reference and progress never becomes answer text', async () => {
  const h = harness();
  const progress = [];
  const pending = h.start({ researchFollowupId: 'a'.repeat(32), onResearchProgress: (event) => progress.push(event) });
  assert.equal(h.requests[0].body.research_followup_id, 'a'.repeat(32));
  h.requests[0].append(frame({ content: '', research_progress: { kind: 'research_progress', run_id: 'run', stage: 'review', role: null, status: 'started' } }));
  h.requests[0].append(frame({ content: '综合报告', done: false }));
  h.requests[0].append(frame({ content: '', done: true }));
  h.requests[0].onload();
  await pending;
  assert.deepEqual(h.deltas, ['综合报告']);
  assert.equal(progress[0].stage, 'review');
});

test('fund-page multi-role research sends the structured authorization, not only prose', async () => {
  const h = harness();
  const pending = h.start({ multiRoleFundCodes: ['022287'] });
  assert.deepEqual(h.requests[0].body.multi_role_fund_codes, ['022287']);
  h.requests[0].append(frame({ content: '三个角色已合议', done: false }));
  h.requests[0].append(frame({ content: '', done: true }));
  h.requests[0].onload();
  await pending;
  assert.deepEqual(h.deltas, ['三个角色已合议']);
});

test('ordinary chat leaves the multi-role field out of the body entirely', async () => {
  const h = harness();
  const pending = h.start();
  h.requests[0].append(frame({ content: '', done: true }));
  h.requests[0].onload();
  await pending;
  assert.equal('multi_role_fund_codes' in h.requests[0].body, false);
});

for (const action of [
  { kind: 'fund_selection', interruptId: 'actual', fundCode: '002207' },
  { kind: 'continue', turnId: 'original-turn' },
]) {
  test(`${action.kind} uses SSE without adding a new user message and displays deltas before completion`, async () => {
    const h = harness();
    const continuation = [];
    const pending = h.exports.streamAgentResume({
      token: 'token', action, signal: h.controller.signal,
      onDelta: (delta) => h.deltas.push(delta),
      onContinuation: (value) => continuation.push(value),
    });
    const xhr = h.requests[0];
    assert.ok(xhr.url.endsWith(action.kind === 'fund_selection' ? '/fund-selection/decision/stream' : '/continue/stream'));
    assert.equal(xhr.body.messages, undefined);
    assert.equal(xhr.body.fund_code ?? xhr.body.turn_id, action.fundCode ?? action.turnId);
    xhr.append(': ping\n\n');
    xhr.append(frame({ content: '第一段' }));
    assert.deepEqual(h.deltas, ['第一段']);
    xhr.append(frame({ content: '第二段' }));
    xhr.append(frame({ done: true, content: '', pending_action: null, continuation: null }));
    xhr.onload();
    await pending;
    assert.deepEqual(h.deltas, ['第一段', '第二段']);
    assert.deepEqual(continuation, [null]);
  });
}

test('an interrupted resume preserves partial text and returns the original task continuation', async () => {
  const h = harness();
  const continuation = [];
  const pending = h.exports.streamAgentResume({
    token: 'token', action: { kind: 'fund_selection', interruptId: 'actual', fundCode: '002207' },
    signal: h.controller.signal, onDelta: (delta) => h.deltas.push(delta),
    onContinuation: (value) => continuation.push(value),
  });
  const rejected = assert.rejects(pending, { name: 'ChatStreamError', message: '继续原任务' });
  h.requests[0].append(frame({ content: '部分报告' }));
  h.requests[0].append(frame({ done: true, content: '继续原任务', continuation: { turn_id: 'original' } }));
  await rejected;
  assert.deepEqual(h.deltas, ['部分报告']);
  assert.equal(continuation[0].turn_id, 'original');
});

test('a transport ending without a terminal frame does not silently claim completion', async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, /研究尚未完成/);
  h.requests[0].append(frame({ content: '部分报告' }));
  h.requests[0].onload();
  await rejected;
  assert.deepEqual(h.deltas, ['部分报告']);
});

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
