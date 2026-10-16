import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function compile(file) {
  return ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
}

function importHarness() {
  const calls = [];
  const invalidations = [];
  const exports = {};
  const client = { invalidateQueries: async (input) => invalidations.push(input.queryKey) };
  const keys = {
    chatImports: ['imports'], chatPendingAction: ['pending'],
    agentMessages: (id) => ['messages', id], chatImport: (id) => ['import', id],
    agentSessions: ['sessions'], portfolio: ['portfolio'], transactionsAll: ['transactions'],
  };
  class Form {
    entries = [];
    append(...entry) { this.entries.push(entry); }
  }
  vm.runInNewContext(compile('../hooks/useChatImport.ts'), {
    exports, FormData: Form,
    require(name) {
      if (name === '@tanstack/react-query') return {
        useQueryClient: () => client, useQuery: (config) => config, useMutation: (config) => config,
      };
      if (name === 'react-native') return { Platform: { OS: 'android' } };
      if (name === '@/api/queries') return { queryKeys: keys };
      if (name === '@/hooks/useAgent') return { ensureSessionToken: async (_client, id) => `token:${id}` };
      if (name === '@/api/client') return {
        request: async (path, options) => { calls.push({ path, options }); return { import_id: 'batch', status: 'UPLOADED' }; },
      };
      throw new Error(`Unexpected import ${name}`);
    },
  });
  return { exports, calls, invalidations };
}

test('chat upload stages attachments without requiring an account and sets native MIME type', async () => {
  const h = importHarness();
  const result = await h.exports.useUploadChatScreenshots().mutationFn({
    sessionId: 'A', images: [{ uri: 'file:///image.png', name: 'holding.png', mimeType: 'image/png' }],
  });
  assert.equal(result.status, 'UPLOADED');
  const { path, options } = h.calls[0];
  assert.equal(path, '/chatbot/holding-imports/screenshots');
  assert.equal(options.bearer, 'token:A');
  assert.equal(options.query.account_id, undefined);
  const [field, image] = options.formData.entries[0];
  assert.equal(field, 'files');
  assert.equal(image.type, 'image/png');
  assert.equal(image.uri, 'file:///image.png');
  assert.equal(image.name, 'holding.png');
});

test('pending actions and OCR progress are scoped to their authenticated session', async () => {
  const h = importHarness();
  const a = h.exports.usePendingChatAction('A');
  const b = h.exports.usePendingChatAction('B');
  assert.notDeepEqual(a.queryKey, b.queryKey);
  await a.queryFn();
  await b.queryFn();
  assert.equal(h.calls[0].options.bearer, 'token:A');
  assert.equal(h.calls[1].options.bearer, 'token:B');
  const progress = h.exports.useChatImportProgress('A', 'batch');
  assert.equal(progress.refetchInterval({ state: { data: { import_batch: { status: 'PARSING' } } } }), 3000);
  assert.equal(progress.refetchInterval({ state: { data: { import_batch: { status: 'REVIEW_REQUIRED' } } } }), false);
  assert.equal(h.exports.useChatImportProgress(null, 'batch').enabled, false);
});

test('account choice and recognition continuation cannot submit a confirmation decision', async () => {
  const h = importHarness();
  const mutation = h.exports.useAdvanceChatImport('A');
  await mutation.mutationFn({ importId: 'batch', interruptId: 'processing' });
  await mutation.mutationFn({ importId: 'batch', interruptId: 'selection', accountId: 7 });
  assert.equal(h.calls[0].path, '/chatbot/holding-imports/batch/continue');
  assert.equal(h.calls[1].path, '/chatbot/holding-imports/batch/account');
  assert.equal(h.calls[1].options.body.account_id, 7);
  assert.equal(h.calls[1].options.body.interrupt_id, 'selection');
  assert.equal(h.calls[1].options.body.decision, undefined);
});

test('continuing an accepted task sends only its original turn and authenticated session', async () => {
  const h = importHarness();
  const mutation = h.exports.useContinueAgentRun('A');
  const context = mutation.onMutate();
  await mutation.mutationFn({ turnId: 'original-turn' });
  const call = h.calls[0];
  assert.equal(call.path, '/chatbot/continue');
  assert.equal(call.options.bearer, 'token:A');
  assert.deepEqual(JSON.parse(JSON.stringify(call.options.body)), { turn_id: 'original-turn' });
  mutation.onSuccess({}, {}, context);
  assert.ok(h.invalidations.some((key) => JSON.stringify(key) === JSON.stringify(['messages', 'A'])));
  assert.ok(h.invalidations.some((key) => JSON.stringify(key) === JSON.stringify(['pending', 'A'])));
  assert.ok(!h.invalidations.some((key) => key?.[1] === 'B'));
});

test('late human-decision callbacks invalidate their origin session after a session switch', () => {
  for (const name of ['useDecideChatImport', 'useAdvanceChatImport', 'useSelectAnalysisFund']) {
    const h = importHarness();
    const old = h.exports[name]('A');
    const origin = old.onMutate();
    const current = h.exports[name]('B');
    current.onSuccess({}, {}, origin);
    assert.ok(h.invalidations.some((key) => JSON.stringify(key) === JSON.stringify(['pending', 'A'])));
    assert.ok(!h.invalidations.some((key) => key?.[1] === 'B'));
  }
});

test('fund selection submits only candidate code and real interrupt using the active session token', async () => {
  const h = importHarness();
  const mutation = h.exports.useSelectAnalysisFund('A');
  await mutation.mutationFn({ interruptId: 'fund-choice', fundCode: '000002' });
  await mutation.mutationFn({ interruptId: 'fund-choice' });
  assert.equal(h.calls[0].path, '/chatbot/fund-selection/decision');
  assert.equal(h.calls[0].options.bearer, 'token:A');
  assert.equal(h.calls[0].options.body.decision, 'select');
  assert.equal(h.calls[0].options.body.fund_code, '000002');
  assert.equal(h.calls[0].options.body.interrupt_id, 'fund-choice');
  assert.equal(h.calls[0].options.body.candidates, undefined);
  assert.equal(h.calls[1].options.body.decision, 'cancel');
  assert.equal(h.calls[1].options.body.fund_code, undefined);
  await assert.rejects(h.exports.useSelectAnalysisFund(null).mutationFn({ interruptId: 'fund-choice' }));
});

for (const entry of ['message', 'fund_selection', 'continue']) {
test(`a late ${entry} stream stays hidden in the current session`, async () => {
  const values = [];
  let cursor = 0;
  let stream;
  let finish;
  const exports = {};
  vm.runInNewContext(compile('../hooks/useAgentChat.ts'), {
    exports, AbortController,
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const index = cursor++;
          if (!(index in values)) values[index] = initial;
          return [values[index], (value) => { values[index] = typeof value === 'function' ? value(values[index]) : value; }];
        },
        useRef(initial) {
          const index = cursor++;
          return values[index] ??= { current: initial };
        },
        useCallback: (fn) => fn, useEffect: () => {},
      };
      if (name === '@tanstack/react-query') return { useQueryClient: () => ({ invalidateQueries: async () => {} }) };
      if (name === '@/api/queries') return { queryKeys: { chatPendingAction: ['pending'], agentSessions: ['sessions'] } };
      if (name === '@/hooks/useAgent') return {
        ensureSessionToken: async () => 'token',
        useAgentMessages: () => ({ data: { messages: [] }, refetch: async () => {} }),
      };
      if (name === '@/api/chatStream') return {
        ChatStreamError: Error,
        streamChatMessage: (input) => { stream = input; return new Promise((resolve) => { finish = resolve; }); },
        streamAgentResume: (input) => { stream = input; return new Promise((resolve) => { finish = resolve; }); },
      };
      if (name === '@/utils/researchProgress') {
        const progressExports = {};
        vm.runInNewContext(compile('../utils/researchProgress.ts'), { exports: progressExports });
        return progressExports;
      }
      throw new Error(`Unexpected import ${name}`);
    },
  });
  const render = (id) => {
    cursor = 0;
    return exports.useAgentChat({ sessionId: id, ensureSession: async () => id });
  };
  const sending = entry === 'message' ? render('A').send('同步截图', ['batch']) : render('A').resume(
    entry === 'fund_selection' ? { kind: entry, interruptId: 'actual', fundCode: '002207' } : { kind: entry, turnId: 'original' },
  );
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(render('A').resume({ kind: 'continue', turnId: 'original' }), /上一条还在生成中/);
  render('B');
  stream.onPendingAction({ kind: 'holding_import_processing', import_id: 'batch', interrupt_id: 'wait' });
  stream.onDelta('正在识别');
  stream.onResearchProgress({ kind: 'research_progress', run_id: 'run-A', stage: 'analysis', role: 'risk', status: 'started' });
  assert.equal(render('B').review, null);
  assert.equal(render('B').turns.length, 0);
  assert.equal(render('A').review.import_id, 'batch');
  assert.match(render('A').turns.at(-1).researchProgress, /风险与回撤进行中/);
  assert.equal(render('A').turns.filter((turn) => turn.role === 'user').length, entry === 'message' ? 1 : 0);
  finish();
  await sending;
});
}

function completedChatHarness() {
  const values = [];
  const cache = new Map();
  const streams = [];
  const refreshes = [];
  let cursor = 0;
  const exports = {};
  const client = {
    invalidateQueries: async () => {},
    fetchQuery: ({ queryKey }) => new Promise((resolve, reject) => {
      refreshes.push({
        id: queryKey[1], reject,
        resolve(data) { cache.set(queryKey[1], data); resolve(data); },
      });
    }),
  };
  const progressExports = {};
  vm.runInNewContext(compile('../utils/researchProgress.ts'), { exports: progressExports });
  vm.runInNewContext(compile('../hooks/useAgentChat.ts'), {
    exports, AbortController,
    require(name) {
      if (name === 'react') return {
        useState(initial) {
          const index = cursor++;
          if (!(index in values)) values[index] = initial;
          return [values[index], (value) => { values[index] = typeof value === 'function' ? value(values[index]) : value; }];
        },
        useRef(initial) {
          const index = cursor++;
          return values[index] ??= { current: initial };
        },
        useCallback: (fn) => fn, useEffect: () => {},
      };
      if (name === '@tanstack/react-query') return { useQueryClient: () => client };
      if (name === '@/api/queries') return { queryKeys: {
        chatPendingAction: ['pending'], agentSessions: ['sessions'], agentMessages: (id) => ['messages', id],
      } };
      if (name === '@/hooks/useAgent') return {
        ensureSessionToken: async () => 'token',
        fetchAgentMessages: async () => {},
        useAgentMessages: (id) => ({ data: cache.get(id) ?? { messages: [] }, refetch: async () => {} }),
      };
      if (name === '@/api/chatStream') {
        const start = (input) => new Promise((resolve, reject) => streams.push({ ...input, finish: resolve, reject }));
        return { ChatStreamError: Error, streamChatMessage: start, streamAgentResume: start };
      }
      if (name === '@/utils/researchProgress') return progressExports;
      throw new Error(`Unexpected import ${name}`);
    },
  });
  return {
    cache, streams, refreshes,
    render(id) {
      cursor = 0;
      return exports.useAgentChat({ sessionId: id, ensureSession: async () => id ?? 'new-session' });
    },
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
for (const outcome of ['failed', 'stale', 'complete']) {
test(`completed research remains visible while history refresh is ${outcome}`, async () => {
  const h = completedChatHarness();
  const old = [{ role: 'user', content: '之前的问题' }, { role: 'assistant', content: '之前的报告' }];
  h.cache.set('A', { messages: old });
  const task = h.render('A').resume({ kind: 'fund_selection', interruptId: 'choice', fundCode: '002207' });
  await tick();
  h.streams[0].onDelta('完整的研究正文。\n');
  h.streams[0].onDelta('数据来源与风险说明。');
  h.streams[0].finish();
  await tick();
  const answer = '完整的研究正文。\n数据来源与风险说明。';
  assert.equal(h.render('A').turns.at(-1).content, answer);
  assert.equal(h.render('A').sending, false);
  assert.equal(h.refreshes[0].id, 'A');
  if (outcome === 'failed') h.refreshes[0].reject(new Error('offline'));
  else h.refreshes[0].resolve({ messages: outcome === 'complete' ? [...old, { role: 'assistant', content: answer }] : old });
  await task;
  const turns = h.render('A').turns;
  assert.equal(turns.at(-1).content, answer);
  assert.equal(turns.filter((turn) => turn.content === answer).length, 1);
  assert.equal(turns.length, 3);
});
}

test('an old refresh cannot remove a newer stream or use the newly selected session', async () => {
  const h = completedChatHarness();
  const first = h.render('A').send('分析基金');
  await tick();
  h.streams[0].onDelta('A 的完整回答');
  h.streams[0].finish();
  await tick();
  const second = h.render('B').send('研究另一个基金');
  await tick();
  h.streams[1].onDelta('B 的回答正在生成');
  h.refreshes[0].resolve({ messages: [{ role: 'user', content: '分析基金' }, { role: 'assistant', content: 'A 的完整回答' }] });
  await first;
  // 即使旧 transport 再发迟到的增量，也不能改写新一轮。
  h.streams[0].onDelta('迟到的 A 内容');
  assert.equal(h.render('B').turns.at(-1).content, 'B 的回答正在生成');
  assert.equal(h.render('B').sending, true);
  h.streams[1].finish();
  await tick();
  assert.equal(h.refreshes[1].id, 'B');
  h.refreshes[1].reject(new Error('offline'));
  await second;
});

test('a newly created session refreshes its own complete history', async () => {
  const h = completedChatHarness();
  const task = h.render(null).send('研究基金');
  await tick();
  h.streams[0].onDelta('完整报告');
  h.streams[0].finish();
  await tick();
  assert.equal(h.refreshes[0].id, 'new-session');
  h.refreshes[0].resolve({ messages: [{ role: 'user', content: '研究基金' }, { role: 'assistant', content: '完整报告' }] });
  await task;
  assert.equal(h.render('new-session').turns.length, 2);
});
