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

test('a late stream action from the previous session stays hidden in the current session', async () => {
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
      };
      throw new Error(`Unexpected import ${name}`);
    },
  });
  const render = (id) => {
    cursor = 0;
    return exports.useAgentChat({ sessionId: id, ensureSession: async () => id });
  };
  const sending = render('A').send('同步截图', ['batch']);
  await new Promise((resolve) => setImmediate(resolve));
  render('B');
  stream.onPendingAction({ kind: 'holding_import_processing', import_id: 'batch', interrupt_id: 'wait' });
  stream.onDelta('正在识别');
  assert.equal(render('B').review, null);
  assert.equal(render('B').turns.length, 0);
  assert.equal(render('A').review.import_id, 'batch');
  finish();
  await sending;
});
