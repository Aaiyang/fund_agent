/**
 * 轻量的 markdown 渲染：够把模型输出的结构显示出来，不引第三方库。
 *
 * 支持的都是模型真会用的那几样：#~### 标题、``` 代码块、- 与 1. 两种列表、
 * > 引用、--- 分隔线、| 表格 |、**加粗**、`行内代码` 与 http(s) 链接。段落沿用换行，
 * 所以列表没被识别出来时也不至于糊成一坨。
 *
 * 流式输出时文本是半截的：代码栅栏没闭合就当成代码块继续显示（不吞字），
 * 加粗没闭合就原样留着星号 —— 等后面的分块到达再补全，不做任何猜测性修复。
 * 表格要第二行的 |---| 才认，所以光有一行竖线的正文不会被错认成表。
 */

import { useState } from 'react';
import { SymbolView } from 'expo-symbols';
import { Linking, Pressable, ScrollView, Text, View } from 'react-native';

import { splitFundAnalysisBlocks } from '../../shared/fund-chart';
import type { components } from '@/api/schema';
import { FundAnalysisChart } from '@/components/FundAnalysisChart';
import { FundHoldingsCard } from '@/components/FundHoldingsCard';
import { ResearchDataCard } from '@/components/ResearchDataCard';
import { ResearchEvidenceSheet } from '@/components/ResearchEvidenceSheet';
import { theme } from '@/constants/theme';

type ResearchCitations = components['schemas']['ResearchCitations'];
const SUPERSCRIPT_DIGITS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

function superscript(value: number): string {
  return String(value).split('').map((digit) => SUPERSCRIPT_DIGITS[Number(digit)] ?? digit).join('');
}

const BASE = { fontSize: 15, lineHeight: 24 } as const;
/** 表格里的字压到次要信息档（12）：列宽是按字数算的，字号越大越容易撑出屏幕。 */
const CELL = { fontSize: 12, lineHeight: 18 } as const;

type Inline = { text: string; bold?: boolean; code?: boolean; href?: string; cite?: number | null; evidence?: string };

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
  // 上限压到 180：再宽一张四列表就放不下，末列只能露半截，不如让它换行。
  return Math.min(180, Math.max(56, widest * 6.6 + 18));
}

/** 链接只认 http(s)，避免模型把任意 scheme 塞进可点区域。 */
function inlineParts(raw: string): Inline[] {
  const parts: Inline[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[\^(\d{1,2}|\?)\]|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|\[(ev_[0-9a-f]{8,})\]/g;
  let cursor = 0;
  let match: RegExpExecArray | null = pattern.exec(raw);
  while (match) {
    if (match.index > cursor) parts.push({ text: raw.slice(cursor, match.index) });
    if (match[1] !== undefined) parts.push({ text: match[1], bold: true });
    else if (match[2] !== undefined) parts.push({ text: match[2], code: true });
    else if (match[3] !== undefined) parts.push({ text: match[3], cite: match[3] === '?' ? null : Number(match[3]) });
    else if (match[4] !== undefined) parts.push({ text: match[4], href: match[5] });
    else parts.push({ text: '', evidence: match[6] });
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

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
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
      flushTable();
      // 空行后仍是同类列表项时合并成一列表：模型常把 1. 2. 3. 之间空一行，
      // 每段各起一列表会把编号全画成 1.。
      let nextIndex = lineIndex + 1;
      while (nextIndex < lines.length && !lines[nextIndex].trim()) nextIndex += 1;
      const next = lines[nextIndex] ?? '';
      const keepsList = Boolean(list) && (
        (list!.ordered && ORDERED.test(next)) || (!list!.ordered && UNORDERED.test(next))
      );
      if (!keepsList) flushList();
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

function openLink(href: string) {
  Linking.openURL(href).catch(() => undefined);
}

function InlineText({
  parts,
  color,
  cell = false,
  selectable = false,
  onCite,
  citationByEvidence,
}: {
  parts: Inline[];
  color: string;
  cell?: boolean;
  selectable?: boolean;
  onCite?: (number: number | null) => void;
  citationByEvidence?: Record<string, number>;
}) {
  return (
    <Text selectable={selectable} style={{ ...(cell ? CELL : BASE), color }}>
      {parts.map((part, index) => {
        if (part.cite !== undefined) {
          return (
            <Text
              key={index}
              onPress={onCite ? () => onCite(part.cite ?? null) : undefined}
              style={{
                fontSize: cell ? 10 : 11,
                fontWeight: '700',
                color: part.cite === null ? theme.warning : theme.primary,
              }}
            >
              {part.cite === null ? '?' : superscript(part.cite)}
            </Text>
          );
        }
        if (part.evidence) {
          const number = citationByEvidence?.[part.evidence];
          if (number === undefined) return null;
          return (
            <Text
              key={index}
              onPress={onCite ? () => onCite(number) : undefined}
              style={{ fontSize: cell ? 10 : 11, fontWeight: '700', color: theme.primary }}
            >
              {superscript(number)}
            </Text>
          );
        }
        return (
          <Text
            key={index}
            onPress={part.href ? () => openLink(part.href!) : undefined}
            style={{
              fontWeight: part.bold ? '700' : undefined,
              fontFamily: part.code ? theme.monoFont : undefined,
              fontSize: part.code ? (cell ? 12 : 13.5) : undefined,
              color: part.href ? theme.primary : part.bold ? theme.text : undefined,
              textDecorationLine: part.href ? 'underline' : undefined,
              backgroundColor: part.code ? theme.inlineCodeBackground : undefined,
            }}
          >
            {part.text}
          </Text>
        );
      })}
    </Text>
  );
}

/**
 * 表格按列宽排：宽度取该列最宽那条，夹在 56~180 之间，超出的部分整张表横向滚。
 * 不做自动换行适配是因为量宽度要等布局完成，那样每帧都在抖。
 */
function TableBlock({
  header,
  rows,
  onCite,
  citationByEvidence,
}: {
  header: string[];
  rows: string[][];
  onCite?: (number: number | null) => void;
  citationByEvidence?: Record<string, number>;
}) {
  const all = [header, ...rows];
  const widths = header.map((_, index) => columnWidth(all, index));
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View style={{ borderWidth: 1, borderColor: theme.border, borderRadius: 10, overflow: 'hidden' }}>
        {all.map((row, rowIndex) => (
          <View
            key={rowIndex}
            style={{
              flexDirection: 'row',
              backgroundColor: rowIndex === 0 ? theme.tableHeader : rowIndex % 2 === 0 ? theme.tableStripe : theme.surface,
            }}
          >
            {header.map((_, columnIndex) => (
              <View
                key={columnIndex}
                style={{
                  width: widths[columnIndex],
                  paddingHorizontal: 8,
                  paddingVertical: 7,
                  borderTopWidth: rowIndex === 0 ? 0 : 1,
                  borderTopColor: theme.border,
                  borderLeftWidth: columnIndex === 0 ? 0 : 1,
                  borderLeftColor: theme.border,
                }}
              >
                <InlineText
                  parts={inlineParts(row[columnIndex] ?? '')}
                  color={rowIndex === 0 ? theme.textMuted : theme.textSoft}
                  cell
                  onCite={onCite}
                  citationByEvidence={citationByEvidence}
                />
              </View>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function MarkdownBody({
  content,
  color = theme.textSoft,
  onCite,
  citationByEvidence,
}: {
  content: string;
  color?: string;
  onCite?: (number: number | null) => void;
  citationByEvidence?: Record<string, number>;
}) {
  return (
    <View style={{ gap: 10 }}>
      {parseBlocks(content).map((block, index) => {
        if (block.kind === 'code') {
          return (
            <Text
              key={index}
              selectable
              style={{
                fontFamily: theme.monoFont,
                fontSize: 12,
                lineHeight: 19,
                color: theme.codeText,
                backgroundColor: theme.codeBackground,
                borderRadius: 12,
                paddingHorizontal: 12,
                paddingVertical: 11,
                overflow: 'hidden',
              }}
            >
              {block.lines.join('\n')}
            </Text>
          );
        }
        if (block.kind === 'heading') {
          // 一级标题落在页面大标题档（18~20），二三级按卡片/区块标题档 15。
          return (
            <Text
              key={index}
              selectable
              style={{
                ...BASE,
                color: theme.text,
                fontWeight: '700',
                letterSpacing: -0.2,
                fontSize: block.level === 1 ? 20 : block.level === 2 ? 17 : 15,
                lineHeight: block.level === 1 ? 29 : block.level === 2 ? 25 : 23,
                marginTop: index === 0 ? 0 : 4,
              }}
            >
              {block.text}
            </Text>
          );
        }
        if (block.kind === 'rule') {
          return <View key={index} style={{ height: 1, backgroundColor: theme.border, marginVertical: 6 }} />;
        }
        if (block.kind === 'quote') {
          return (
            <View
              key={index}
              style={{
                borderLeftWidth: 3,
                borderLeftColor: theme.primary,
                backgroundColor: theme.primarySoft,
                borderRadius: 10,
                paddingHorizontal: 12,
                paddingVertical: 10,
              }}
            >
              <InlineText
                parts={inlineParts(block.text)}
                color={theme.textMuted}
                onCite={onCite}
                citationByEvidence={citationByEvidence}
              />
            </View>
          );
        }
        if (block.kind === 'list') {
          return (
            <View key={index} style={{ gap: 5 }}>
              {block.items.map((item, itemIndex) => (
                <View key={itemIndex} style={{ flexDirection: 'row' }}>
                  {/* 记号占固定宽度，换行的正文才能对齐第一行的文字起点。 */}
                  <Text style={{ ...BASE, color: theme.textFaint, width: block.ordered ? 24 : 14 }}>
                    {block.ordered ? `${itemIndex + 1}. ` : '· '}
                  </Text>
                  <View style={{ flex: 1 }}>
                    <InlineText
                      parts={inlineParts(item)}
                      color={color}
                      onCite={onCite}
                      citationByEvidence={citationByEvidence}
                    />
                  </View>
                </View>
              ))}
            </View>
          );
        }
        if (block.kind === 'table') {
          return (
            <TableBlock
              key={index}
              header={block.header}
              rows={block.rows}
              onCite={onCite}
              citationByEvidence={citationByEvidence}
            />
          );
        }
        // 段落走行内解析：这里以前直接吐原文，所以 **加粗** 的星号会露在界面上。
        return (
          <View key={index} style={{ gap: 3 }}>
            {block.text.split('\n').map((line, lineIndex) => (
              <InlineText
                key={lineIndex}
                parts={inlineParts(line)}
                color={color}
                selectable
                onCite={onCite}
                citationByEvidence={citationByEvidence}
              />
            ))}
          </View>
        );
      })}
    </View>
  );
}

export function MarkdownText({
  content,
  color = theme.textSoft,
  citations,
}: {
  content: string;
  color?: string;
  citations?: ResearchCitations | null;
}) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [activeNumber, setActiveNumber] = useState<number | null>(null);
  const items = citations?.citations ?? [];
  const hasEvidence = Boolean(
    citations && (
      items.length
      || (citations.coverage?.length ?? 0)
      || (citations.sources?.length ?? 0)
      || (citations.audit?.unknown ?? 0) > 0
    ),
  );
  const citationByEvidence = Object.fromEntries(items.map((item) => [item.evidence_id, item.number]));

  function openCitation(number: number | null) {
    if (!citations) return;
    setActiveNumber(number);
    setEvidenceOpen(true);
  }

  return (
    <View style={{ gap: 12 }}>
      {splitFundAnalysisBlocks(content).map((block) => block.kind === 'chart' ? (
        <FundAnalysisChart key={block.offset} chart={block.chart} />
      ) : block.kind === 'holdings' ? (
        <FundHoldingsCard key={block.offset} holdings={block.holdings} />
      ) : block.kind === 'research' ? (
        <ResearchDataCard key={block.offset} card={block.card} />
      ) : (
        <MarkdownBody
          key={block.offset}
          content={block.content}
          color={color}
          onCite={hasEvidence ? openCitation : undefined}
          citationByEvidence={citationByEvidence}
        />
      ))}
      {hasEvidence && citations ? (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="查看证据与来源核对"
            onPress={() => openCitation(null)}
            style={({ pressed }) => ({
              alignSelf: 'flex-start',
              flexDirection: 'row',
              alignItems: 'center',
              paddingHorizontal: 10,
              paddingVertical: 6,
              borderRadius: 999,
              borderWidth: 1,
              borderColor: theme.border,
              backgroundColor: theme.surfaceSoft,
              opacity: pressed ? 0.72 : 1,
            })}
          >
            <SymbolView
              name={{ ios: 'doc.text.magnifyingglass', android: 'description', web: 'description' }}
              tintColor={theme.textMuted}
              size={14}
            />
            <Text style={{ marginLeft: 6, fontSize: 12, color: theme.textMuted }}>
              {items.length ? `证据 ${items.length} 条` : '研究核对'}
            </Text>
            <Text style={{ marginLeft: 8, fontSize: 11, color: theme.primary }}>查看 ›</Text>
          </Pressable>
          <ResearchEvidenceSheet
            visible={evidenceOpen}
            citations={citations}
            activeNumber={activeNumber}
            onClose={() => setEvidenceOpen(false)}
          />
        </>
      ) : null}
    </View>
  );
}
