import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const element = require('react').createElement;
const compiled = ts.transpileModule(readFileSync(new URL('../components/FundSelectionCard.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

function render(busy = false) {
  const presses = [];
  const selected = [];
  const exported = {};
  const native = {
    View: ({ children }) => element('div', {}, children), Text: ({ children }) => element('span', {}, children),
    ActivityIndicator: () => element('span', {}, 'loading'),
    Pressable: ({ children, onPress, disabled }) => {
      presses.push({ onPress, disabled });
      return element('button', { disabled }, children);
    },
  };
  compileFunction(compiled, ['exports', 'require'])(exported, (name) => {
    if (name === 'react-native') return native;
    if (name === '@/components/ui') return {
      Card: native.View, Button: ({ label, ...props }) => element(native.Pressable, props, label),
    };
    if (name === '@/constants/theme') return { theme: { text: '#111827', textMuted: '#6B7280', primary: '#2563EB', background: '#F5F6F8' } };
    return require(name);
  });
  const markup = renderToStaticMarkup(element(exported.FundSelectionCard, {
    action: { kind: 'fund_selection', interrupt_id: 'actual', notice: '请选择份额', candidates: [
      { fund_code: '000001', fund_name: '示例成长A', fund_type: '混合型' },
      { fund_code: '000002', fund_name: '示例成长C' },
      { fund_code: '000003', fund_name: '示例精选A' },
    ] }, busy, onSelect: (code) => selected.push(code), onCancel: () => selected.push('cancel'),
  }));
  return { markup, presses, selected };
}

test('fund choices preserve names, share classes and codes; nothing is auto-selected', () => {
  const h = render();
  assert.deepEqual(h.selected, []);
  assert.ok(h.markup.includes('示例成长A') && h.markup.includes('示例成长C') && h.markup.includes('000002'));
  assert.equal(h.presses.length, 4);
  h.presses[1].onPress();
  h.presses[3].onPress();
  assert.deepEqual(h.selected, ['000002', 'cancel']);
});

test('resuming analysis disables every choice and cancel button', () => {
  const h = render(true);
  assert.ok(h.presses.every((button) => button.disabled));
  assert.ok(h.markup.includes('正在继续分析'));
});
