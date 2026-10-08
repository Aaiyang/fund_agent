/**
 * 轻量的 markdown 渲染：够把模型输出的结构显示出来，不引第三方库。
 *
 * 支持的都是模型真会用的那几样：#~### 标题、``` 代码块、- 与 1. 两种列表、
 * > 引用、--- 分隔线、| 表格 |、**加粗** 与 `行内代码`。段落沿用换行，所以列表
 * 没被识别出来时也不至于糊成一坨。
 *
 * 流式输出时文本是半截的：代码栅栏没闭合就当成代码块继续显示（不吞字），
 * 加粗没闭合就原样留着星号 —— 等后面的分块到达再补全，不做任何猜测性修复。
 * 表格要第二行的 |---| 才认，所以光有一行竖线的正文不会被错认成表。
 */

import { ScrollView, Text, View } from 'react-native';

import { theme } from '@/constants/theme';

const BASE = { fontSize: 15, lineHeight: 23 } as const;
/** 表格里的字比正文小一档：列宽是按字数算的，字号越大越容易撑出屏幕。 */
const CELL = { fontSize: 13, lineHeight: 19 } as const;

type Inline = { text: string; bold?: boolean; code?: boolean };

type Block =
  | { kind: 'code'; lines: string[] }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'rule' }
  | { kind: 'para'; text: string };

const HEADING = /^(#{1,3})\s+(.*)$/;
const UNORDERED = /^[-*•]\s+(.*)$/;
const ORDERED = /^(\d+)[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])\s*(\1\s*){2,}$/;
const QUOTE = /^>\s?(.*)$/;
const TABLE_ROW = /^\s*\|(.+)\|\s*$/;

/** 一列里 CJK 占两个半宽字符，按码点粗估就够，不必上字体度量。 */
function displayWidth(text: string): number {
  let width = 0;
  for (const char of text) width += char.codePointAt(0)! > 255 ? 2 : 1;
  return width;
}

function columnWidth(rows: string[][], index: number): number {
  const widest = rows.reduce((max, row) => Math.max(max, displayWidth(row[index] ?? '')), 0);
  return Math.min(220, Math.max(56, widest * 6.6 + 18));
}

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
  let table: string[][] | null = null;

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
  /** 第二行不是 |---| 就不是表，原样退回正文。 */
  const flushTable = () => {
    if (!table) return;
    const rows = table;
    table = null;
    const separator = rows[1];
    if (rows.length >= 2 && separator?.length && separator.every((cell) => /^:?-{2,}:?$/.test(cell))) {
      blocks.push({ kind: 'table', header: rows[0], rows: rows.slice(2) });
      return;
    }
    for (const row of rows) blocks.push({ kind: 'para', text: `|${row.join('|')}|` });
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
      flushTable();
      code = [];
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      flushTable();
      continue;
    }

    const row = TABLE_ROW.exec(line);
    if (row) {
      if (!table) {
        flushParagraph();
        flushList();
      }
      table = table ?? [];
      table.push(row[1].split('|').map((cell) => cell.trim()));
      continue;
    }
    flushTable();

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
      // 两个正则的捕获组数量不同：ORDERED 的序号是组 1、正文是组 2，
      // UNORDERED 只有正文一个组。取错下标会把 undefined 当文本传下去。
      const item = ordered ? ordered[2] : (unordered as RegExpExecArray)[1];
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

  // 流式输出停在半截的地方：没闭合的代码栅栏、最后一行段落、最后一列表、最后一张表。
  if (code !== null) blocks.push({ kind: 'code', lines: code });
  flushTable();
  flushParagraph();
  flushList();
  return blocks;
}

function InlineText({ parts, color, cell = false }: { parts: Inline[]; color: string; cell?: boolean }) {
  return (
    <Text style={{ ...(cell ? CELL : BASE), color }}>
      {parts.map((part, index) => (
        <Text
          key={index}
          style={{
            fontWeight: part.bold ? '700' : undefined,
            fontFamily: part.code ? 'monospace' : undefined,
            fontSize: part.code ? (cell ? 12 : 14) : undefined,
            backgroundColor: part.code ? '#F3F4F6' : undefined,
          }}
        >
          {part.text}
        </Text>
      ))}
    </Text>
  );
}

/**
 * 表格按列宽排：宽度取该列最宽那条，夹在 56~220 之间，超出的部分整张表横向滚。
 * 不做自动换行适配是因为量宽度要等布局完成，那样每帧都在抖。
 */
function TableBlock({ header, rows }: { header: string[]; rows: string[][] }) {
  const all = [header, ...rows];
  const widths = header.map((_, index) => columnWidth(all, index));
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View style={{ borderWidth: 1, borderColor: theme.border, borderRadius: 8, overflow: 'hidden' }}>
        {all.map((row, rowIndex) => (
          <View
            key={rowIndex}
            style={{
              flexDirection: 'row',
              backgroundColor: rowIndex === 0 ? theme.background : theme.surface,
            }}
          >
            {header.map((_, columnIndex) => (
              <View
                key={columnIndex}
                style={{
                  width: widths[columnIndex],
                  paddingHorizontal: 8,
                  paddingVertical: 6,
                  borderTopWidth: rowIndex === 0 ? 0 : 1,
                  borderTopColor: theme.border,
                  borderLeftWidth: columnIndex === 0 ? 0 : 1,
                  borderLeftColor: theme.border,
                }}
              >
                <InlineText parts={inlineParts(row[columnIndex] ?? '')} color={rowIndex === 0 ? theme.textMuted : theme.text} cell />
              </View>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
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
        if (block.kind === 'table') {
          return <TableBlock key={index} header={block.header} rows={block.rows} />;
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
