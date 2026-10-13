import { Stack } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { PersonaEditor } from '@/components/persona/PersonaEditor';
import { Async, ErrorState, LoadingState } from '@/components/states';
import { Button, Card, Screen } from '@/components/ui';
import { theme } from '@/constants/theme';
import { FIELD_LABELS, describeChanges, formatFieldValue, personaErrorMessage, sourceLabel, usePersonaClear, usePersonaDecision, useUserPersona, useUserPersonaHistory, type Persona, type PersonaFieldKey, } from '@/hooks/useUserPersona';
import { confirmAction } from '@/utils/confirm';
import { formatDateTime } from '@/utils/format';
import { countPersonaFields, PERSONA_GROUPS, type PersonaGroup } from '@/utils/personaEditor';
type Tab = 'profile' | 'proposals' | 'history';
export default function PersonaScreen() {
    const query = useUserPersona();
    return <Screen refreshing={query.isFetching} onRefresh={() => void query.refetch()}>
    <Stack.Screen options={{ title: '用户画像' }}/>
    <Async query={query}>{(persona) => <PersonaManager persona={persona} onRefresh={() => void query.refetch()}/>}</Async>
  </Screen>;
}
function PersonaManager({ persona, onRefresh }: {
    persona: Persona;
    onRefresh: () => void;
}) {
    const [tab, setTab] = useState<Tab>('profile');
    const [editor, setEditor] = useState<{
        group: PersonaGroup;
        snapshot: Persona;
    } | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [problem, setProblem] = useState<string | null>(null);
    const [privacy, setPrivacy] = useState(false);
    const clear = usePersonaClear(persona.revision);
    const decide = usePersonaDecision(persona.revision);
    const busy = clear.isPending || decide.isPending;
    const filled = countPersonaFields(persona.fields);
    const latest = Object.values(persona.provenance).map((mark) => mark.confirmed_at).filter((date): date is string => Boolean(date)).sort().at(-1);
    const groups = Object.keys(PERSONA_GROUPS) as PersonaGroup[];
    const nextGroup = groups.find((group) => PERSONA_GROUPS[group].fields.some((key) => persona.fields[key] == null)) ?? 'investment';
    function edit(group: PersonaGroup) {
        setProblem(null);
        setNotice(null);
        setEditor({ group, snapshot: persona });
    }
    function review(proposalId: string, decision: 'accept' | 'reject') {
        if (busy)
            return;
        setProblem(null);
        setNotice(null);
        decide.mutate({ proposalId, decision }, {
            onSuccess: () => setNotice(decision === 'accept' ? '已采用建议，后续回答将使用更新后的画像。' : '已忽略这条建议，你的画像保持原样。'),
            onError: (error) => setProblem(personaErrorMessage(error)),
        });
    }
    return <View style={styles.container}>
    <View style={styles.hero}>
      <View style={styles.between}><Text style={styles.eyebrow}>AI 个性化</Text><View style={styles.heroBadge}><Text style={styles.heroBadgeText}>由你确认</Text></View></View>
      <Text style={styles.heroTitle}>你的偏好，由你决定</Text>
      <Text style={styles.heroDescription}>让基金研究与持仓分析，更贴合你的目标和阅读习惯。</Text>
      <View style={styles.summary}>
        <SummaryItem label="风险偏好" value={formatFieldValue('risk_preference', persona.fields.risk_preference)}/>
        <View style={styles.summaryDivider}/>
        <SummaryItem label="投资期限" value={formatFieldValue('investment_horizon_months', persona.fields.investment_horizon_months)}/>
        <View style={styles.summaryDivider}/>
        <SummaryItem label="投资目标" value={persona.fields.investment_goals?.length ? `${persona.fields.investment_goals.length} 个目标` : '未设置'}/>
      </View>
      <View style={styles.between}><Text style={styles.heroMeta}>已设置 {filled} / 7 项 · 所有信息均可选</Text>
        <Pressable accessibilityRole="button" disabled={busy} onPress={() => edit(nextGroup)} style={styles.heroAction}><Text style={styles.link}>{filled === 0 ? '开始设置' : filled < 7 ? '继续完善' : '编辑偏好'} ›</Text></Pressable>
      </View>
      <View style={styles.progressTrack} accessibilityLabel={`已设置 ${filled} 项，共 7 项可选信息`}><View style={[styles.progressFill, { width: `${filled / 7 * 100}%` }]}/></View>
    </View>

    <View style={styles.tabs}>
      {([['profile', '我的画像'], ['proposals', '待确认'], ['history', '变更记录']] as const).map(([value, title]) => <Pressable key={value} accessibilityRole="tab" accessibilityState={{ selected: tab === value }} accessibilityLabel={value === 'proposals' ? `待确认，${persona.pending_proposals.length} 条建议` : title} onPress={() => { setTab(value); setNotice(null); setProblem(null); }} style={[styles.tab, tab === value && styles.tabActive]}>
        <Text style={[styles.tabText, tab === value && styles.tabTextActive]}>{title}</Text>
        {value === 'proposals' && persona.pending_proposals.length > 0 ? <View style={styles.countBadge}><Text style={styles.countText}>{persona.pending_proposals.length}</Text></View> : null}
      </Pressable>)}
    </View>
    {notice ? <View style={styles.success}><Text accessibilityLiveRegion="polite" style={styles.successText}>✓ {notice}</Text></View> : null}
    {problem ? <View style={styles.problem}><Text accessibilityLiveRegion="polite" style={styles.problemText}>{problem}</Text><Pressable accessibilityRole="button" onPress={onRefresh} style={styles.inlineAction}><Text style={styles.link}>刷新最新画像</Text></Pressable></View> : null}

    {tab === 'profile' ? <>
      {persona.pending_proposals.length ? <Pressable accessibilityRole="button" accessibilityLabel={`查看 ${persona.pending_proposals.length} 条待确认建议`} onPress={() => setTab('proposals')} style={styles.pendingBanner}>
        <View style={{ flex: 1 }}><Text style={styles.pendingTitle}>{persona.pending_proposals.length} 条新建议，等你确认</Text><Text style={styles.small}>来自你的对话，确认前不会影响画像</Text></View><Text style={styles.link}>查看 ›</Text>
      </Pressable> : null}
      {groups.map((group, index) => <Card key={group} style={styles.groupCard}>
        <View style={styles.groupHeader}><View style={styles.groupIcon}><Text style={styles.groupNumber}>0{index + 1}</Text></View>
          <View style={{ flex: 1 }}><Text style={styles.groupTitle}>{PERSONA_GROUPS[group].title}</Text><Text style={styles.small}>{PERSONA_GROUPS[group].caption}</Text></View>
          <Pressable accessibilityRole="button" accessibilityLabel={`编辑${PERSONA_GROUPS[group].title}`} disabled={busy} onPress={() => edit(group)} style={styles.editButton}><Text style={styles.link}>编辑</Text></Pressable>
        </View>
        {PERSONA_GROUPS[group].fields.map((key, row) => {
                    const field = key as PersonaFieldKey;
                    const value = persona.fields[field];
                    const mark = persona.provenance[field];
                    return <View key={field} style={[styles.fieldRow, row > 0 && styles.fieldBorder]}>
            <View style={styles.between}><Text style={styles.fieldLabel}>{field === 'investment_horizon_months' ? '投资期限' : FIELD_LABELS[field]}</Text>
              <Text style={[styles.fieldValue, value == null && styles.unset]}>{Array.isArray(value) ? (value.length ? `${value.length} 项` : '未设置') : formatFieldValue(field, value)}</Text>
            </View>
            {Array.isArray(value) && value.length > 0 ? <View style={styles.values}>{value.map((item, i) => <View style={styles.valueTag} key={`${item}-${i}`}><Text style={styles.valueTagText}>{formatFieldValue(field, [item] as typeof value)}</Text></View>)}</View> : null}
            {mark ? <Text style={styles.source}>{sourceLabel(mark.source)}{mark.confirmed_at ? ` · ${formatDateTime(mark.confirmed_at)}` : ''}</Text> : null}
          </View>;
                })}
      </Card>)}
      <Text style={styles.updated}>{latest ? `最近更新 · ${formatDateTime(latest)}` : '还没有设置画像，可按需要逐项填写'}</Text>
      <Card style={styles.privacyCard}>
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: privacy }} onPress={() => setPrivacy(!privacy)} style={styles.privacyHeader}><View style={{ flex: 1 }}><Text style={styles.groupTitle}>数据与隐私</Text><Text style={styles.small}>了解画像用途，管理保存的信息</Text></View><Text style={styles.chevron}>{privacy ? '−' : '＋'}</Text></Pressable>
        {privacy ? <View style={styles.privacyBody}><Text style={styles.description}>画像用于个性化回答。持仓金额与收益来自你的账本，画像不会代替实际持仓，也不会授权交易。</Text>
          <Text style={styles.description}>清除会删除已确认画像、待确认建议和变更记录；聊天记录与长期记忆需分别管理。</Text>
          <Pressable accessibilityRole="button" disabled={busy || (persona.revision === 0 && !persona.pending_proposals.length && !filled)} onPress={() => confirmAction('清除用户画像', '已确认的偏好、待确认建议与变更记录将被删除。聊天记录、长期记忆和持仓不会删除。', () => {
                    setProblem(null);
                    clear.mutate(undefined, { onSuccess: () => setNotice('已清除用户画像。你可以重新设置偏好。'), onError: (error) => setProblem(personaErrorMessage(error)) });
                })} style={styles.clearButton}><Text style={{ color: theme.danger, fontSize: 13 }}>{clear.isPending ? '正在清除…' : '清除用户画像'}</Text></Pressable>
        </View> : null}
      </Card>
    </> : null}
    {tab === 'proposals' ? <>
      <Text style={styles.panelTitle}>确认助手理解得是否准确</Text><Text style={styles.panelDescription}>核对建议和原文依据，选择采用或忽略。你的决定才会改变画像。</Text>
      {persona.pending_proposals.length === 0 ? <EmptyPanel symbol="✓" title="没有待确认建议" hint="当你在对话中要求助手记住长期偏好时，新的建议会出现在这里。"/> : <>
        {persona.pending_proposals.length > 1 ? <View style={styles.reviewWarning}><Text style={styles.warningText}>确认一条后，其余待确认建议将失效。请先核对全部建议，再选择采用。</Text></View> : null}
        {persona.pending_proposals.map((proposal) => <Card key={proposal.id} style={styles.proposalCard}>
          <View style={styles.between}><Text style={styles.groupTitle}>画像更新建议</Text><View style={styles.pendingLabel}><Text style={styles.pendingLabelText}>待你确认</Text></View></View>
          <Text style={styles.source}>来自对话 · {formatDateTime(proposal.created_at)}</Text>
          {(Object.keys(proposal.changes) as PersonaFieldKey[]).map((key) => <View key={key} style={styles.comparison}>
            <Text style={styles.fieldLabel}>{FIELD_LABELS[key] ?? key}</Text><View style={styles.compareValues}>
              <Text style={styles.oldValue}>{formatFieldValue(key, persona.fields[key])}</Text><Text style={styles.arrow}>→</Text>
              <Text style={styles.newValue}>{proposal.changes[key] == null ? '清除设置' : formatFieldValue(key, proposal.changes[key])}</Text></View>
          </View>)}
          <View style={styles.evidence}><Text style={styles.evidenceLabel}>你的原话</Text><Text style={styles.evidenceText}>“{proposal.evidence}”</Text></View>
          <View style={styles.proposalActions}><View style={{ flex: 1 }}><Button label="忽略" variant="secondary" disabled={busy} onPress={() => review(proposal.id, 'reject')}/></View>
            <View style={{ flex: 2 }}><Button label="确认采用" disabled={busy} onPress={() => review(proposal.id, 'accept')}/></View></View>
        </Card>)}
      </>}
    </> : null}
    {tab === 'history' ? <PersonaHistory /> : null}
    {editor ? <PersonaEditor key={`${editor.group}-${editor.snapshot.revision}`} group={editor.group} snapshot={editor.snapshot} currentRevision={persona.revision} onClose={() => setEditor(null)} onReload={() => setEditor({ ...editor, snapshot: persona })} onSaved={() => { setEditor(null); setNotice('已保存，后续回答将使用更新后的偏好。'); }}/> : null}
  </View>;
}
function SummaryItem({ label, value }: {
    label: string;
    value: string;
}) {
    return <View style={{ flex: 1 }}><Text style={styles.summaryLabel}>{label}</Text><Text style={styles.summaryValue}>{value}</Text></View>;
}
function EmptyPanel({ symbol, title, hint }: {
    symbol: string;
    title: string;
    hint: string;
}) {
    return <Card style={styles.empty}><View style={styles.emptyIcon}><Text style={styles.emptySymbol}>{symbol}</Text></View><Text style={styles.emptyTitle}>{title}</Text><Text style={styles.emptyHint}>{hint}</Text></Card>;
}
function PersonaHistory() {
    const [limit, setLimit] = useState(10);
    const history = useUserPersonaHistory(limit);
    return <View>
    <Text style={styles.panelTitle}>每一次改变，都有记录</Text><Text style={styles.panelDescription}>查看你主动设置或确认过的偏好变更。</Text>
    {history.isPending ? <LoadingState /> : history.isError && !history.data ? <ErrorState message={personaErrorMessage(history.error)} onRetry={() => void history.refetch()}/> : <>
      {history.isError ? <View><Text style={styles.warningText}>刷新失败，当前显示上次加载的记录。</Text><Button label="重试加载记录" variant="secondary" onPress={() => void history.refetch()}/></View> : null}
      {history.data?.length ? <Card style={styles.historyCard}>{history.data.map((row, index) => <View key={row.revision} style={styles.historyRow}>
        <View style={styles.timeline}><View style={styles.timelineDot}/>{index < history.data.length - 1 ? <View style={styles.timelineLine}/> : null}</View>
        <View style={styles.historyContent}><Text style={styles.historyDate}>{formatDateTime(row.created_at)}</Text><Text style={styles.historyText}>{describeChanges(row.changes)}</Text>
          <Text style={styles.source}>{sourceLabel(row.source)}</Text></View>
      </View>)}</Card> : <EmptyPanel symbol="≡" title="还没有变更记录" hint="设置偏好或采用助手的建议后，可以在这里查看来源和更新时间。"/>}
      {history.data && history.data.length >= limit && limit < 100 ? <Button label="查看更多记录" variant="secondary" onPress={() => setLimit(Math.min(limit + 10, 100))}/> : null}
    </>}
  </View>;
}
const styles = StyleSheet.create({
    container: { width: '100%', maxWidth: 640, alignSelf: 'center' },
    between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
    hero: { backgroundColor: '#EDF3FF', borderRadius: 18, padding: 20, marginBottom: 18, borderWidth: 1, borderColor: '#DFE9FD' },
    eyebrow: { color: theme.primary, fontSize: 12, fontWeight: '600' }, heroBadge: { backgroundColor: '#FFFFFFB3', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }, heroBadgeText: { fontSize: 11, color: '#4B68A1' },
    heroTitle: { fontSize: 23, fontWeight: '700', color: '#18365E', marginTop: 14, marginBottom: 8 },
    heroDescription: { fontSize: 13, lineHeight: 21, color: '#607596' },
    summary: { flexDirection: 'row', alignItems: 'stretch', marginTop: 22, marginBottom: 16, gap: 12 },
    summaryLabel: { fontSize: 11, color: '#607596', marginBottom: 6 }, summaryValue: { fontSize: 15, color: '#18365E', fontWeight: '600' }, summaryDivider: { width: 1, backgroundColor: '#D8E4F8' },
    heroMeta: { fontSize: 10, color: '#607596', flex: 1 }, heroAction: { minHeight: 44, justifyContent: 'center' },
    link: { color: theme.primary, fontSize: 12, fontWeight: '600' },
    progressTrack: { height: 4, borderRadius: 2, overflow: 'hidden', backgroundColor: '#D9E4F7' }, progressFill: { height: 4, backgroundColor: theme.primary, borderRadius: 2 },
    tabs: { flexDirection: 'row', padding: 4, borderRadius: 12, backgroundColor: '#E9EDF3', marginBottom: 18, gap: 4 },
    tab: { flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 5, borderRadius: 9 }, tabActive: { backgroundColor: theme.surface },
    tabText: { fontSize: 13, color: theme.textMuted }, tabTextActive: { fontWeight: '600', color: theme.primary },
    countBadge: { backgroundColor: '#DBEAFE', borderRadius: 8, minWidth: 17, paddingHorizontal: 4, alignItems: 'center' }, countText: { fontSize: 10, color: theme.primary, lineHeight: 17 },
    groupCard: { borderRadius: 16, padding: 16, marginBottom: 12 }, groupHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 4 },
    groupIcon: { width: 36, height: 36, borderRadius: 10, backgroundColor: '#EFF6FF', alignItems: 'center', justifyContent: 'center' }, groupNumber: { fontSize: 12, fontWeight: '700', color: theme.primary },
    groupTitle: { fontSize: 15, fontWeight: '600', color: theme.text }, small: { fontSize: 11, color: theme.textMuted, lineHeight: 18, marginTop: 3 }, editButton: { minWidth: 44, minHeight: 44, alignItems: 'flex-end', justifyContent: 'center' },
    fieldRow: { paddingVertical: 13 }, fieldBorder: { borderTopWidth: 1, borderTopColor: '#F0F2F5' }, fieldLabel: { fontSize: 13, color: theme.textMuted }, fieldValue: { fontSize: 13, color: theme.text, fontWeight: '500', flexShrink: 1, textAlign: 'right' }, unset: { color: theme.textFaint, fontWeight: '400' },
    values: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 }, valueTag: { borderRadius: 7, backgroundColor: '#F3F6FB', paddingHorizontal: 9, paddingVertical: 6 }, valueTagText: { fontSize: 12, color: '#4B6080', lineHeight: 18 },
    source: { fontSize: 10, color: theme.textFaint, lineHeight: 17, marginTop: 6 }, updated: { fontSize: 11, color: theme.textFaint, textAlign: 'center', marginVertical: 8 },
    pendingBanner: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderColor: '#DCE7FC', backgroundColor: '#F5F9FF', padding: 14, borderRadius: 12, marginBottom: 14 }, pendingTitle: { fontSize: 13, color: '#244779', fontWeight: '600' },
    privacyCard: { borderRadius: 16, padding: 16, marginTop: 8 }, privacyHeader: { flexDirection: 'row', alignItems: 'center', minHeight: 44 }, chevron: { fontSize: 20, color: theme.textFaint }, privacyBody: { paddingTop: 12 }, description: { fontSize: 12, lineHeight: 21, color: theme.textMuted, marginBottom: 8 }, clearButton: { minHeight: 44, justifyContent: 'center', alignItems: 'flex-start' },
    success: { backgroundColor: '#ECFDF5', padding: 12, borderRadius: 10, marginBottom: 12 }, successText: { color: '#047857', fontSize: 12, lineHeight: 20 },
    problem: { backgroundColor: '#FEF2F2', padding: 12, borderRadius: 10, marginBottom: 12 }, problemText: { fontSize: 12, color: theme.danger, lineHeight: 20 }, inlineAction: { minHeight: 36, justifyContent: 'center' },
    panelTitle: { fontSize: 16, fontWeight: '600', color: theme.text, marginBottom: 6 }, panelDescription: { fontSize: 12, color: theme.textMuted, lineHeight: 20, marginBottom: 16 },
    reviewWarning: { backgroundColor: '#FFFBEB', padding: 12, borderRadius: 10, marginBottom: 14 }, warningText: { color: theme.warning, fontSize: 12, lineHeight: 20 },
    proposalCard: { padding: 16, borderRadius: 16 }, pendingLabel: { backgroundColor: '#EFF6FF', paddingVertical: 4, paddingHorizontal: 8, borderRadius: 6 }, pendingLabelText: { color: theme.primary, fontSize: 11 },
    comparison: { borderTopWidth: 1, borderTopColor: '#F0F2F5', paddingTop: 12, marginTop: 12 }, compareValues: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginTop: 8 }, oldValue: { flex: 1, fontSize: 13, color: theme.textMuted, lineHeight: 21 }, arrow: { color: theme.textFaint, fontSize: 16 }, newValue: { flex: 1, fontSize: 13, color: theme.primary, lineHeight: 21, fontWeight: '600' },
    evidence: { backgroundColor: '#F7F9FC', borderRadius: 10, padding: 12, marginVertical: 16 }, evidenceLabel: { fontSize: 10, color: theme.textFaint, marginBottom: 6 }, evidenceText: { fontSize: 12, color: '#4B6080', lineHeight: 21 }, proposalActions: { flexDirection: 'row', gap: 10 },
    empty: { borderRadius: 16, paddingVertical: 36, paddingHorizontal: 24, alignItems: 'center' }, emptyIcon: { width: 56, height: 56, borderRadius: 18, backgroundColor: '#EFF6FF', justifyContent: 'center', alignItems: 'center', marginBottom: 16 }, emptySymbol: { fontSize: 25, color: theme.primary }, emptyTitle: { fontSize: 15, fontWeight: '600', color: theme.text, marginBottom: 8 }, emptyHint: { fontSize: 12, lineHeight: 21, color: theme.textMuted, textAlign: 'center' },
    historyCard: { borderRadius: 16, padding: 18 }, historyRow: { flexDirection: 'row', gap: 14 }, timeline: { width: 10, alignItems: 'center', paddingTop: 4 }, timelineDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#93B5FA' }, timelineLine: { width: 1, backgroundColor: '#E1E9F6', flex: 1, marginTop: 5 }, historyContent: { flex: 1, paddingBottom: 23 }, historyDate: { fontSize: 11, color: theme.textFaint, marginBottom: 7 }, historyText: { fontSize: 13, color: theme.text, lineHeight: 22 },
});
