import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import ts from 'typescript';

const page = ts.createSourceFile(
  'page.tsx',
  readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8'),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

function find(node, predicate) {
  if (predicate(node)) return node;
  return ts.forEachChild(node, (child) => find(child, predicate));
}

// Execute the actual handlers, with React state and network replaced by controlled fixtures.
function handler(name, dependencies) {
  const node = find(
    page,
    (item) => ts.isFunctionDeclaration(item) && item.name?.text === name,
  );
  assert.ok(node, `Missing handler ${name}`);
  const compiled = ts.transpileModule(node.getText(page), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return compileFunction(
    `${compiled}; return ${name};`,
    Object.keys(dependencies),
  )(...Object.values(dependencies));
}

const session = (id) => ({
  session_id: id,
  token: { access_token: `token-${id}` },
});

test('stopping an old stream preserves the generation used by the new sessions history', async () => {
  const refs = {
    activeSessionIdRef: { current: 'A' },
    streamRequestRef: { current: null },
    streamGenerationRef: { current: 0 },
  };
  const send = handler('submitMessage', {
    ...refs,
    activeSession: session('A'),
    setSending() {},
    setDraft() {},
    setError() {},
    setMessages() {},
    streamMessage: async (_, __, ___, signal) =>
      new Promise((resolve, reject) => {
        signal.addEventListener('abort', () =>
          reject(new DOMException('stopped', 'AbortError')),
        );
      }),
  });
  const response = send('question');
  const generation = refs.streamGenerationRef.current;
  refs.activeSessionIdRef.current = 'B';
  refs.streamRequestRef.current.controller.abort();
  assert.equal((await response).status, 'stopped');
  assert.equal(refs.streamGenerationRef.current, generation);
  assert.equal(refs.streamRequestRef.current, null);
});

test('selecting another session aborts the old request; selecting the same one preserves messages', () => {
  const controller = new AbortController();
  let clears = 0;
  const refs = {
    activeSessionIdRef: { current: 'A' },
    streamRequestRef: { current: { sessionId: 'A', controller } },
  };
  const activate = handler('activateSession', {
    ...refs,
    setActiveSession() {},
    setMessages() {
      clears++;
    },
  });
  activate(session('A'));
  assert.equal(clears, 0);
  assert.equal(controller.signal.aborted, false);
  activate(session('B'));
  assert.equal(refs.activeSessionIdRef.current, 'B');
  assert.equal(controller.signal.aborted, true);
  assert.equal(clears, 1);
});

test('chunks queued before a session switch cannot update the new sessions messages', () => {
  const call = find(
    page,
    (node) =>
      ts.isCallExpression(node) &&
      node.expression.getText(page) === 'streamMessage',
  );
  const callback = call.arguments[2];
  const source = ts.transpileModule(
    `const callback = ${callback.getText(page)};`,
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  const request = { sessionId: 'A', controller: new AbortController() };
  const streamRequestRef = { current: request };
  const activeSessionIdRef = { current: 'A' };
  let pending;
  const onChunk = compileFunction(`${source}; return callback;`, [
    'request',
    'streamRequestRef',
    'activeSessionIdRef',
    'setMessages',
  ])(request, streamRequestRef, activeSessionIdRef, (updater) => {
    pending = updater;
  });
  onChunk('old answer');
  activeSessionIdRef.current = 'B';
  const newMessages = [{ role: 'assistant', content: 'B answer' }];
  assert.equal(pending(newMessages), newMessages);
  pending = undefined;
  onChunk('late old answer');
  assert.equal(pending, undefined);
  activeSessionIdRef.current = 'A';
  onChunk('own answer');
  assert.equal(
    pending([{ role: 'assistant', content: '' }])[0].content,
    'own answer',
  );
  request.controller.abort();
  pending = undefined;
  onChunk('aborted');
  assert.equal(pending, undefined);
});

test('stream transport sends the selected sessions token and forwards cancellation', async () => {
  const api = ts.createSourceFile(
    'api.ts',
    readFileSync(new URL('../lib/api.ts', import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
  );
  const node = find(
    api,
    (item) =>
      ts.isFunctionDeclaration(item) && item.name?.text === 'streamMessage',
  );
  const source = ts.transpileModule(node.getText(api).replace('export ', ''), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const controller = new AbortController();
  const chunks = [];
  const fetchFixture = async (_, init) => {
    assert.equal(init.headers.Authorization, 'Bearer token-A');
    assert.equal(init.signal, controller.signal);
    assert.deepEqual(JSON.parse(init.body), {
      messages: [{ role: 'user', content: 'hello' }],
    });
    return new Response(
      'data: {"content":"answer","done":false}\n\ndata: {"content":"","done":true}\n\n',
    );
  };
  const send = compileFunction(`${source}; return streamMessage;`, [
    'fetch',
    'API_BASE_URL',
    'readError',
  ])(fetchFixture, 'http://fixture', () => 'error');
  await send(
    session('A'),
    'hello',
    (chunk) => chunks.push(chunk),
    controller.signal,
  );
  assert.deepEqual(chunks, ['answer']);
});
