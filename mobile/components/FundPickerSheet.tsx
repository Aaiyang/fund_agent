import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button, Chip } from '@/components/ui';
import { theme } from '@/constants/theme';
import { usePositions } from '@/hooks/usePortfolio';
import { useWatchlist } from '@/hooks/useWatchlist';
import { formatDate, formatNumber, formatReturnPoints, formatSignedMoney, trendColor } from '@/utils/format';
import { MAX_PICKER_FUNDS, dedupePickerFunds, pickerActionLabel, pickerHint, pickerRowDisabled, summarizeHoldings, togglePickerFund, type PickerFund, type ResearchTier } from '@/utils/fundPicker';

type TabKey = 'holdings' | 'watchlist';

/**
 * 选基金面板：从我的持仓 / 我的自选里多选 1~3 只，直接发起分析或对比。
 *
 * 两只以上后端会自动切到 `fund_comparison` 意图。成本档位由这里显式选：
 * 「多智能体」会拉起三角色合议，token 是普通研究的数倍，所以不给模型自决。
 */
export function FundPickerSheet({ visible, busy = false, onClose, onConfirm }: {
  visible: boolean;
  busy?: boolean;
  onClose: () => void;
  onConfirm: (funds: PickerFund[], tier: ResearchTier) => void;
}) {
  const insets = useSafeAreaInsets();
  const [tab, setTab] = useState<TabKey>('holdings');
  const [selected, setSelected] = useState<PickerFund[]>([]);
  const holdings = usePositions(null);
  const watchlist = useWatchlist(null);

  const rows: PickerFund[] = tab === 'holdings'
    ? dedupePickerFunds((holdings.data?.items ?? []).map((item) => ({ code: item.fund_code, name: item.fund_name ?? '' })))
    : dedupePickerFunds((watchlist.data?.items ?? []).map((item) => ({ code: item.fund_code, name: item.fund_name ?? '' })));
  const loading = tab === 'holdings' ? holdings.isPending : watchlist.isPending;
  const metrics = tab === 'holdings'
    ? (code: string) => {
      // 持仓接口每 (账户, 基金) 出一行：这里合成一行，收益金额按账户相加，涨幅取同源净值。
      const group = (holdings.data?.items ?? []).filter((each) => each.fund_code === code);
      if (!group.length) return null;
      const summary = summarizeHoldings(group);
      const navDate = group.find((each) => each.nav_date)?.nav_date;
      const parts = [
        summary.profit == null ? null : `${summary.accounts > 1 ? '涨幅对应收益合计' : '涨幅对应收益'} ${formatSignedMoney(summary.profit)}`,
        navDate ? `截至 ${formatDate(navDate)}` : null,
        summary.accounts > 1 ? `${summary.accounts} 个账户` : null,
      ];
      return { rate: summary.rate, extra: parts.filter(Boolean).join('　') || null };
    }
    : (code: string) => {
      const item = watchlist.data?.items.find((each) => each.fund_code === code);
      if (!item) return null;
      return { rate: item.daily_return, extra: item.latest_nav == null ? null : `最新净值 ${formatNumber(item.latest_nav)}（${formatDate(item.nav_date)}）` };
    };
  const close = () => {
    if (busy) return;
    setSelected([]);
    onClose();
  };
  const confirm = (tier: ResearchTier) => {
    if (!selected.length || busy) return;
    onConfirm(selected, tier);
    setSelected([]);
  };

  return <Modal transparent visible={visible} animationType="slide" onRequestClose={close}>
    <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityRole="button" accessibilityLabel="关闭选基金面板" disabled={busy}/>
      <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 12) }]} accessibilityViewIsModal>
        <View style={styles.handle}/>
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>选择基金</Text>
            <Text style={styles.hint}>可多选，最多 {MAX_PICKER_FUNDS} 只；两只以上按对比分析处理</Text>
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel="关闭选基金面板" disabled={busy} onPress={close} style={styles.close}><Text style={styles.closeText}>×</Text></Pressable>
        </View>
        <View style={styles.tabs}>
          <Chip label="我的持仓" active={tab === 'holdings'} onPress={() => setTab('holdings')}/>
          <Chip label="我的自选" active={tab === 'watchlist'} onPress={() => setTab('watchlist')}/>
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          {loading ? <ActivityIndicator size="small" color={theme.primary}/> : null}
          {!loading && !rows.length ? <Text style={styles.hint}>{tab === 'holdings' ? '还没有持仓记录，先去导入或添加一笔交易。' : '自选还是空的，可以从搜索页加几只基金。'}</Text> : null}
          {!loading ? rows.map((fund) => {
            const checked = selected.some((item) => item.code === fund.code);
            const disabled = busy || pickerRowDisabled(selected, fund.code);
            const value = metrics(fund.code);
            return <Pressable key={fund.code} accessibilityRole="checkbox" accessibilityState={{ checked, disabled }} disabled={disabled} onPress={() => setSelected((prev) => togglePickerFund(prev, fund))} style={[styles.row, checked && styles.rowSelected]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{fund.name || fund.code}</Text>
                <Text style={styles.rowMeta}>
                  {fund.name ? `${fund.code}　` : ''}
                  {value?.rate == null ? '最新涨幅 未更新' : <>最新涨幅 <Text style={{ color: trendColor(value.rate) }}>{formatReturnPoints(value.rate)}</Text></>}
                  {value?.extra ? `　${value.extra}` : ''}
                </Text>
              </View>
              <View style={[styles.radio, checked && styles.radioSelected]}>{checked ? <View style={styles.dot}/>: null}</View>
            </Pressable>;
          }) : null}
        </ScrollView>
        <View style={styles.footer}>
          <Text style={styles.hint}>{pickerHint(selected.length)}</Text>
          <View style={styles.actions}>
            <View style={{ flex: 1 }}>
              <Button label={pickerActionLabel(selected.length)} disabled={!selected.length || busy} onPress={() => confirm('single')}/>
            </View>
            <View style={{ flex: 1 }}>
              <Button label={selected.length > 1 ? '多智能体对比' : '多智能体分析'} variant="secondary" disabled={!selected.length || busy} onPress={() => confirm('multi_role')}/>
            </View>
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  </Modal>;
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: theme.overlay, justifyContent: 'flex-end' },
  sheet: {
    maxHeight: '82%',
    width: '100%',
    maxWidth: 640,
    alignSelf: 'center',
    backgroundColor: theme.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: theme.border,
  },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: theme.borderStrong, alignSelf: 'center', marginTop: 10 },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingTop: 12, paddingBottom: 16 },
  title: { fontSize: 19, fontWeight: '700', color: theme.text, marginBottom: 4 },
  hint: { fontSize: 12, color: theme.textMuted, lineHeight: 19 },
  close: { minWidth: 44, minHeight: 44, justifyContent: 'center', alignItems: 'center' },
  closeText: { fontSize: 26, color: theme.textMuted },
  tabs: { flexDirection: 'row', gap: 8, paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: theme.border },
  content: { padding: 20, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', padding: 14, borderRadius: 12, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surfaceSoft, gap: 10 },
  rowSelected: { backgroundColor: theme.primarySoft, borderColor: theme.primary },
  rowTitle: { fontSize: 15, fontWeight: '600', color: theme.text, marginBottom: 4 },
  rowMeta: { fontSize: 12, color: theme.textMuted },
  radio: { width: 20, height: 20, borderWidth: 1.5, borderColor: theme.borderStrong, borderRadius: 10, justifyContent: 'center', alignItems: 'center' },
  radioSelected: { borderColor: theme.primary },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.primary },
  footer: { paddingHorizontal: 20, paddingTop: 12, borderTopWidth: 1, borderTopColor: theme.border },
  actions: { flexDirection: 'row', gap: 10, marginTop: 10 },
});
