/**
 * 研究报告的证据与核对面板。
 *
 * 正文只保留结论和编号角标；来源摘录、覆盖与引用审计放在这里，默认折叠。
 * 角标与「证据 N 条」入口共用同一个底部面板，点角标会滚到对应来源。
 */

import { SymbolView } from 'expo-symbols';
import { useEffect, useRef } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { components } from '@/api/schema';
import { Divider } from '@/components/ui';
import { theme } from '@/constants/theme';

type ResearchCitations = components['schemas']['ResearchCitations'];
type ResearchCitationItem = components['schemas']['ResearchCitationItem'];

function CitationRow({
  item,
  active,
  onLayout,
}: {
  item: ResearchCitationItem;
  active: boolean;
  onLayout: (event: { nativeEvent: { layout: { y: number } } }) => void;
}) {
  const codes = item.fund_codes ?? [];
  return (
    <View
      onLayout={onLayout}
      style={{
        padding: 12,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: active ? theme.primary : theme.border,
        backgroundColor: active ? theme.primarySoft : theme.surfaceSoft,
        marginBottom: 8,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <View
          style={{
            width: 24,
            height: 24,
            borderRadius: 12,
            backgroundColor: active ? theme.primary : theme.surfaceMuted,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ fontSize: 11, fontWeight: '700', color: active ? theme.primaryInk : theme.textMuted }}>
            {item.number}
          </Text>
        </View>
        <Text numberOfLines={1} style={{ flexShrink: 1, marginLeft: 8, fontSize: 14, fontWeight: '600', color: theme.text }}>
          {item.label}
        </Text>
        {codes.length ? (
          <Text numberOfLines={1} style={{ marginLeft: 8, fontSize: 11, color: theme.textMuted }}>
            {codes.join('、')}
          </Text>
        ) : null}
      </View>
      {item.as_of ? (
        <Text style={{ marginTop: 5, marginLeft: 32, fontSize: 11, color: theme.textFaint }}>数据日期 {item.as_of}</Text>
      ) : null}
      {item.excerpt ? (
        <Text selectable style={{ marginTop: 7, marginLeft: 32, fontSize: 12, lineHeight: 19, color: theme.textMuted }}>
          {item.excerpt}
        </Text>
      ) : null}
    </View>
  );
}

function NoteLines({ title, lines }: { title: string; lines: string[] }) {
  if (!lines.length) return null;
  return (
    <View style={{ marginTop: 6 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {lines.map((line, index) => (
        <View key={`${index}-${line}`} style={{ flexDirection: 'row', marginTop: 5 }}>
          <Text style={{ width: 12, fontSize: 12, lineHeight: 19, color: theme.textFaint }}>·</Text>
          <Text style={{ flex: 1, fontSize: 12, lineHeight: 19, color: theme.textMuted }}>{line}</Text>
        </View>
      ))}
    </View>
  );
}

export function ResearchEvidenceSheet({
  visible,
  citations,
  activeNumber,
  onClose,
}: {
  visible: boolean;
  citations: ResearchCitations;
  activeNumber: number | null;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const scroller = useRef<ScrollView>(null);
  const rowY = useRef<Record<number, number>>({});
  const items = citations.citations ?? [];
  const coverage = citations.coverage ?? [];
  const sources = citations.sources ?? [];
  const audit = citations.audit ?? {};
  const matched = audit.matched ?? 0;
  const unknown = audit.unknown ?? 0;
  const uncited = audit.uncited_lines ?? 0;

  useEffect(() => {
    if (!visible || activeNumber === null) return;
    // 面板刚打开时行还没量完；等一帧后再滚到被点的那条来源。
    const timer = setTimeout(() => {
      scroller.current?.scrollTo({ y: Math.max(0, (rowY.current[activeNumber] ?? 0) - 12), animated: true });
    }, 160);
    return () => clearTimeout(timer);
  }, [visible, activeNumber]);

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="关闭证据面板" onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 14) }]} accessibilityViewIsModal>
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.eyebrow}>EVIDENCE</Text>
              <Text style={styles.title}>证据与核对</Text>
              <Text style={styles.subtitle}>
                {items.length ? `${items.length} 条引用` : '本轮没有编号引用'} · {matched} 处可核对
                {unknown ? ` · ${unknown} 处无法核对` : ''}
              </Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="关闭证据面板"
              hitSlop={8}
              onPress={onClose}
              style={styles.close}
            >
              <SymbolView name={{ ios: 'xmark', android: 'close', web: 'close' }} tintColor={theme.textMuted} size={17} />
            </Pressable>
          </View>

          <ScrollView ref={scroller} style={{ flex: 1 }} contentContainerStyle={styles.content}>
            {items.map((item) => (
              <CitationRow
                key={`${item.number}-${item.evidence_id}`}
                item={item}
                active={item.number === activeNumber}
                onLayout={(event) => { rowY.current[item.number] = event.nativeEvent.layout.y; }}
              />
            ))}
            {!items.length ? (
              <Text style={styles.empty}>本轮报告的结论没有指向可核对的证据标识。</Text>
            ) : null}

            {coverage.length ? (
              <>
                <Divider style={{ marginVertical: 12 }} />
                <NoteLines title="研究范围" lines={coverage} />
              </>
            ) : null}
            {sources.length ? (
              <>
                <Divider style={{ marginVertical: 12 }} />
                <NoteLines title="来源核对" lines={sources} />
              </>
            ) : null}

            <Divider style={{ marginVertical: 12 }} />
            <Text style={styles.sectionTitle}>引用核对</Text>
            <Text style={styles.auditText}>
              {matched} 处可核对，{unknown} 处引用了无法核对的标识；另有 {uncited} 行含数字但未带引用
              （启发式统计，不代表编造）。
            </Text>
            {unknown ? <Text style={styles.warnText}>正文里的「?」角标表示该处引用无法核对。</Text> : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: theme.overlay, justifyContent: 'flex-end' },
  sheet: {
    width: '100%',
    maxHeight: '88%',
    maxWidth: 640,
    alignSelf: 'center',
    backgroundColor: theme.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: theme.border,
  },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: theme.borderStrong, alignSelf: 'center', marginTop: 10 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  eyebrow: { fontSize: 10, fontWeight: '700', letterSpacing: 1.4, color: theme.gold },
  title: { fontSize: 21, fontWeight: '600', color: theme.text, marginTop: 4 },
  subtitle: { fontSize: 11, color: theme.textMuted, marginTop: 4 },
  close: {
    width: 36,
    height: 36,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: { padding: 16, paddingBottom: 24 },
  empty: { fontSize: 13, lineHeight: 20, color: theme.textMuted, paddingVertical: 8 },
  sectionTitle: { fontSize: 12, fontWeight: '600', color: theme.text, marginBottom: 2 },
  auditText: { fontSize: 12, lineHeight: 19, color: theme.textMuted, marginTop: 4 },
  warnText: { fontSize: 12, lineHeight: 19, color: theme.warning, marginTop: 5 },
});
