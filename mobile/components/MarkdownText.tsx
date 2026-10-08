/**
 * 轻量的 markdown 渲染：够把模型输出的结构显示出来，不引第三方库。
 *
 * 支持的都是模型真会用的那几样：#~### 标题、``` 代码块、- 与 1. 两种列表、
 * > 引用、--- 分隔线、**加粗** 与 `行内代码`。段落沿用换行，所以列表没被识别
 * 出来时也不至于糊成一坨。
 *
 * 流式输出时文本是半截的：代码栅栏没闭合就当成代码块继续显示（不吞字），
 * 加粗没闭合就原样留着星号 —— 等后面的分块到达再补全，不做任何猜测性修复。
 */

import { Text, View } from 'react-native';

import { theme } from '@/constants/theme';

const BASE = { fontSize: 15, lineHeight: 23 } as const;

type Inline = { text: string; bold?: boolean; code?: boolean };

type Block =
  | { kind: 'code'; lines: string[] }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'rule' }
  | { kind: 'para'; text: string };

const HEADING = /^(#{1,3})\s+(.*)$/;
const UNORDERED = /^[-*•]\s+(.*)$/;
const ORDERED = /^(\d+)[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])\s*(\1\s*){2,}$/;
const QUOTE = /^>\s?(.*)$/;

function inlineParts(raw: string): Inline[] {
  const parts: Inline[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let cursor = 0;
  let match: RegExpExecArray | null = pattern.exec(raw);
  while (match) {
    if (match.index > cursor) parts.push({ text: raw.slice(cursor, match.index) });
    parts.push(match[1] !== undefined ? { text: match[1], bold: true } : { text: match[2], code: true });
    cursor = match.index + match[0].length;
    match = pattern.exec(raw);
  }
  if (cursor < raw.length) parts.push({ text: raw.slice(cursor) });
  return parts;
}

function parseBlocks(content: string): Block[] {
  const blocks: Block[] = [];
  const lines = content.split('\n');
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let code: string[] | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ kind: 'para', text: paragraph.join('\n') });
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    blocks.push({ kind: 'list', ordered: list.ordered, items: list.items });
    list = null;
  };

  for (const line of lines) {
    const fence = line.trimStart().startsWith('```');
    if (code !== null) {
      if (fence) {
        blocks.push({ kind: 'code', lines: code });
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }
    if (fence) {
      flushParagraph();
      flushList();
      code = [];
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] });
      continue;
    }
    if (RULE.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'rule' });
      continue;
    }
    const quote = QUOTE.exec(line);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'quote', text: quote[1] });
      continue;
    }
    const ordered = ORDERED.exec(line);
    const unordered = ordered ? null : UNORDERED.exec(line);
    if (ordered || unordered) {
      flushParagraph();
      const item = (ordered ?? unordered)![2];
      const wantsOrdered = Boolean(ordered);
      // 序号不同才另起一组：模型连着列 1..5 时那是一列表。
      if (list && list.ordered !== wantsOrdered) flushList();
      list = list ?? { ordered: wantsOrdered, items: [] };
      list.items.push(item);
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  // 流式输出停在半截的地方：没闭合的代码栅栏、最后一行段落、最后一列表。
  if (code !== null) blocks.push({ kind: 'code', lines: code });
  flushParagraph();
  flushList();
  return blocks;
}

function InlineText({ parts, color }: { parts: Inline[]; color: string }) {
  return (
    <Text style={{ ...BASE, color }}>
      {parts.map((part, index) => (
        <Text
          key={index}
          style={{
            fontWeight: part.bold ? '700' : undefined,
            fontFamily: part.code ? 'monospace' : undefined,
            fontSize: part.code ? 14 : undefined,
            backgroundColor: part.code ? '#F3F4F6' : undefined,
          }}
        >
          {part.text}
        </Text>
      ))}
    </Text>
  );
}

export function MarkdownText({ content, color = theme.text }: { content: string; color?: string }) {
  return (
    <View style={{ gap: 6 }}>
      {parseBlocks(content).map((block, index) => {
        if (block.kind === 'code') {
          return (
            <Text
              key={index}
              selectable
              style={{
                fontFamily: 'monospace',
                fontSize: 13,
                lineHeight: 20,
                color: theme.text,
                backgroundColor: '#F3F4F6',
                borderRadius: 8,
                padding: 10,
              }}
            >
              {block.lines.join('\n')}
            </Text>
          );
        }
        if (block.kind === 'heading') {
          return (
            <Text key={index} style={{ ...BASE, color, fontWeight: '700', fontSize: block.level === 1 ? 18 : 16 }}>
              {block.text}
            </Text>
          );
        }
        if (block.kind === 'rule') {
          return <View key={index} style={{ height: 1, backgroundColor: theme.border, marginVertical: 4 }} />;
        }
        if (block.kind === 'quote') {
          return (
            <View key={index} style={{ borderLeftWidth: 3, borderLeftColor: theme.border, paddingLeft: 10 }}>
              <InlineText parts={inlineParts(block.text)} color={theme.textMuted} />
            </View>
          );
        }
        if (block.kind === 'list') {
          return (
            <View key={index} style={{ gap: 2 }}>
              {block.items.map((item, itemIndex) => (
                <View key={itemIndex} style={{ flexDirection: 'row' }}>
                  <Text style={{ ...BASE, color }}>
                    {block.ordered ? `${itemIndex + 1}. ` : '· '}
                  </Text>
                  <View style={{ flex: 1 }}>
                    <InlineText parts={inlineParts(item)} color={color} />
                  </View>
                </View>
              ))}
            </View>
          );
        }
        return (
          <Text key={index} style={{ ...BASE, color }} selectable>
            {block.text}
          </Text>
        );
      })}
    </View>
  );
}
