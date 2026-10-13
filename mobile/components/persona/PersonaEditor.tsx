import { useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button } from '@/components/ui';
import { theme } from '@/constants/theme';
import { EXPERIENCE_LEVELS, FUND_TYPES, RESPONSE_DETAILS, RESPONSE_LANGUAGES, RISK_LEVELS, formatOptionLabel, personaErrorMessage, usePersonaUpdate, type Persona, type PersonaFieldKey, type PersonaFields, } from '@/hooks/useUserPersona';
import { buildPersonaChanges, PERSONA_GROUPS, type PersonaGroup } from '@/utils/personaEditor';
const descriptions: Record<string, string> = {
    beginner: '希望先解释概念，再说明分析依据', intermediate: '了解基本概念，关注指标和比较', experienced: '熟悉基金，希望深入研究逻辑与数据',
    conservative: '更关注波动，希望优先了解风险', balanced: '兼顾增长机会和波动，关注两者的取舍', aggressive: '关注增长机会，也了解可能出现的较大波动',
    concise: '先给结论，再列少量关键依据', detailed: '展开数据、推理依据和不同情景',
};
export function PersonaEditor({ group, snapshot, currentRevision, onClose, onSaved, onReload }: {
    group: PersonaGroup;
    snapshot: Persona;
    currentRevision: number;
    onClose: () => void;
    onSaved: () => void;
    onReload: () => void;
}) {
    const insets = useSafeAreaInsets();
    const update = usePersonaUpdate(snapshot.revision);
    const [draft, setDraft] = useState<PersonaFields>({ ...snapshot.fields });
    const [horizon, setHorizon] = useState(String(snapshot.fields.investment_horizon_months ?? ''));
    const [goal, setGoal] = useState('');
    const [problem, setProblem] = useState<string | null>(null);
    const [discard, setDiscard] = useState<'close' | 'reload' | null>(null);
    const stale = currentRevision !== snapshot.revision;
    const busy = update.isPending;
    const goals = draft.investment_goals ?? [];
    const dirty = PERSONA_GROUPS[group].fields.some((key) => JSON.stringify(snapshot.fields[key] ?? null) !== JSON.stringify(draft[key] ?? null))
        || (group === 'goals' && (horizon !== String(snapshot.fields.investment_horizon_months ?? '') || Boolean(goal.trim())));
    function change(key: PersonaFieldKey, value: PersonaFields[PersonaFieldKey]) {
        setProblem(null);
        setDraft((previous) => ({ ...previous, [key]: value }));
    }
    function close() {
        if (busy)
            return;
        if (dirty)
            setDiscard('close');
        else
            onClose();
    }
    function save() {
        if (busy || stale)
            return;
        setProblem(null);
        try {
            const changes = buildPersonaChanges(group, snapshot.fields, draft, horizon, goal);
            if (Object.keys(changes).length === 0) {
                onClose();
                return;
            }
            update.mutate(changes, { onSuccess: onSaved, onError: (error) => setProblem(personaErrorMessage(error)) });
        }
        catch (error) {
            setProblem(error instanceof Error ? error.message : '请检查填写的内容。');
        }
    }
    function addGoal(value = goal) {
        const text = value.trim();
        if (!text)
            return;
        if (text.length > 120) {
            setProblem('每个目标最多 120 个字。');
            return;
        }
        if (goals.length >= 5) {
            setProblem('最多保留 5 个目标，请先移除一项。');
            return;
        }
        if (goals.includes(text)) {
            setProblem('这个目标已经在列表中。');
            return;
        }
        change('investment_goals', [...goals, text]);
        setGoal('');
    }
    function choices(key: PersonaFieldKey, options: readonly string[], title: string, hint?: string) {
        return <View style={styles.section}>
      <Text style={styles.label}>{title}</Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
      {options.map((value) => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: draft[key] === value, disabled: busy }} accessibilityLabel={`${title}：${formatOptionLabel(key, value)}`} disabled={busy} onPress={() => change(key, value as PersonaFields[PersonaFieldKey])} style={[styles.choice, draft[key] === value && styles.selected]}>
        <View style={styles.choiceText}><Text style={styles.choiceTitle}>{formatOptionLabel(key, value)}</Text>
          <Text style={styles.hint}>{value === 'balanced' ? (key === 'risk_preference' ? '兼顾增长机会和波动，关注两者的取舍' : '结论与解释兼顾，适合日常阅读') : descriptions[value] ?? (value === 'en' ? '使用英文回答' : '使用中文回答')}</Text>
        </View>
        <View style={[styles.radio, draft[key] === value && styles.radioSelected]}>{draft[key] === value ? <View style={styles.dot}/> : null}</View>
      </Pressable>)}
      <Pressable accessibilityRole="button" onPress={() => change(key, null)} disabled={busy} style={styles.unset}>
        <Text style={[styles.hint, draft[key] == null && { color: theme.primary }]}>{draft[key] == null ? '✓ 暂未设置' : '清除这一项设置'}</Text>
      </Pressable>
    </View>;
    }
    return <Modal transparent visible animationType="slide" onRequestClose={close}>
    <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityRole="button" accessibilityLabel="关闭编辑"/>
      <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]} accessibilityViewIsModal>
        <View style={styles.handle}/>
        <View style={styles.header}><View style={{ flex: 1 }}><Text style={styles.title}>编辑{PERSONA_GROUPS[group].title}</Text>
          <Text style={styles.hint}>选择完成后保存，所有信息都可选</Text></View>
          <Pressable accessibilityRole="button" accessibilityLabel="关闭编辑面板" disabled={busy} onPress={close} style={styles.close}><Text style={styles.closeText}>×</Text></Pressable>
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          {snapshot.pending_proposals.length > 0 ? <View style={styles.warning}><Text style={styles.warningText}>保存修改后，现有 {snapshot.pending_proposals.length} 条待确认建议将失效。你也可以先取消编辑，核对这些建议。</Text></View> : null}
          {stale ? <View style={styles.warning}><Text style={styles.warningText}>画像已在其他操作中更新。请重新载入后编辑，避免覆盖新内容。</Text>
            <Button label="重新载入最新画像" variant="secondary" onPress={() => { if (dirty)
                        setDiscard('reload');
        else
            onReload(); }}/></View> : null}
          {group === 'investment' ? <>
            {choices('investment_experience', EXPERIENCE_LEVELS, '你对基金投资的熟悉程度')}
            {choices('risk_preference', RISK_LEVELS, '你更倾向怎样的投资体验', '这是你自述的偏好，可随时调整。')}
            <View style={styles.section}><Text style={styles.label}>不考虑的基金类型</Text><Text style={styles.hint}>可多选；不选表示未设置限制。</Text>
              <View style={styles.tags}>{FUND_TYPES.map((type) => {
                const selected = draft.excluded_fund_types?.includes(type) ?? false;
                return <Pressable key={type} accessibilityRole="checkbox" accessibilityState={{ checked: selected, disabled: busy }} disabled={busy} onPress={() => change('excluded_fund_types', selected ? draft.excluded_fund_types?.filter((item) => item !== type) ?? [] : [...(draft.excluded_fund_types ?? []), type])} style={[styles.tag, selected && styles.selected]}><Text style={{ color: selected ? theme.primary : theme.text }}>{selected ? '✓ ' : ''}{formatOptionLabel('excluded_fund_types', type)}</Text></Pressable>;
            })}</View>
            </View>
          </> : null}
          {group === 'goals' ? <>
            <View style={styles.section}><Text style={styles.label}>计划投资多久</Text><Text style={styles.hint}>整体投资偏好；不同资金的用款安排可在对话中补充。</Text>
              <View style={styles.tags}>{[6, 12, 36, 60].map((months) => <Pressable key={months} accessibilityRole="button" accessibilityState={{ selected: horizon === String(months), disabled: busy }} disabled={busy} onPress={() => { setHorizon(String(months)); setProblem(null); }} style={[styles.tag, horizon === String(months) && styles.selected]}>
                <Text style={{ color: horizon === String(months) ? theme.primary : theme.text }}>{months < 12 ? `${months} 个月` : `${months / 12} 年`}</Text></Pressable>)}</View>
              <View style={styles.inputRow}><TextInput accessibilityLabel="自定义投资期限（月）" editable={!busy} value={horizon} onChangeText={(text) => { setHorizon(text); setProblem(null); }} keyboardType="number-pad" placeholder="自定义，或留空" placeholderTextColor={theme.textFaint} style={[styles.input, { flex: 1 }]}/><Text style={styles.hint}>个月</Text></View>
              <Text style={styles.hint}>支持 1–600 个月，留空表示暂未确定。</Text>
            </View>
            <View style={styles.section}><View style={styles.inputRow}><Text style={[styles.label, { flex: 1 }]}>希望实现的目标</Text><Text style={styles.hint}>{goals.length}/5</Text></View>
              <Text style={styles.hint}>写下自己的目标，便于助手理解你的研究需求。</Text>
              {goals.map((value, index) => <View key={index} style={styles.goalRow}>
                <TextInput accessibilityLabel={`投资目标 ${index + 1}`} editable={!busy} value={value} multiline maxLength={120} onChangeText={(text) => change('investment_goals', goals.map((item, i) => i === index ? text : item))} style={[styles.input, { flex: 1 }]}/>
                <Pressable accessibilityRole="button" accessibilityLabel={`移除目标 ${index + 1}`} disabled={busy} onPress={() => change('investment_goals', goals.filter((_, i) => i !== index))} style={styles.close}><Text style={styles.remove}>移除</Text></Pressable>
              </View>)}
              {goals.length < 5 ? <><View style={styles.inputRow}><TextInput accessibilityLabel="新增投资目标" editable={!busy} value={goal} maxLength={120} multiline onChangeText={(text) => { setGoal(text); setProblem(null); }} placeholder="例如：为三年后的购房做准备" placeholderTextColor={theme.textFaint} style={[styles.input, { flex: 1 }]}/>
                <Pressable accessibilityRole="button" disabled={busy || !goal.trim()} onPress={() => addGoal()} style={styles.close}><Text style={{ color: goal.trim() ? theme.primary : theme.textFaint }}>添加</Text></Pressable></View>
                <View style={styles.tags}>{['长期积累', '退休储备', '购房准备', '教育规划'].filter((text) => !goals.includes(text)).map((text) => <Pressable key={text} accessibilityRole="button" disabled={busy} onPress={() => addGoal(text)} style={styles.tag}><Text style={styles.hint}>＋ {text}</Text></Pressable>)}</View></> : null}
            </View>
          </> : null}
          {group === 'assistant' ? <>{choices('response_language', RESPONSE_LANGUAGES, '回复语言')}{choices('response_detail', RESPONSE_DETAILS, '回答详细度')}</> : null}
        </ScrollView>
        <View style={styles.footer}>
          {problem ? <Text accessibilityLiveRegion="polite" style={styles.error}>{problem}</Text> : null}
          {discard ? <View style={styles.warning}><Text style={styles.warningText}>还有未保存的修改，要放弃吗？</Text><View style={styles.actions}>
            <View style={{ flex: 1 }}><Button label="继续编辑" variant="secondary" onPress={() => setDiscard(null)}/></View>
            <View style={{ flex: 1 }}><Button label={discard === 'reload' ? '放弃并重新载入' : '放弃修改'} variant="secondary" onPress={discard === 'reload' ? onReload : onClose}/></View></View></View> : <View style={styles.actions}>
              <View style={{ flex: 1 }}><Button label="取消" variant="secondary" onPress={close} disabled={busy}/></View>
              <View style={{ flex: 2 }}><Button label="保存修改" onPress={save} loading={busy} disabled={!dirty || stale}/></View>
            </View>}
        </View>
      </View>
    </KeyboardAvoidingView>
  </Modal>;
}
const styles = StyleSheet.create({
    backdrop: { flex: 1, backgroundColor: 'rgba(17,24,39,0.4)', justifyContent: 'flex-end' },
    sheet: { maxHeight: '90%', width: '100%', maxWidth: 640, alignSelf: 'center', backgroundColor: theme.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
    handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: theme.border, alignSelf: 'center', marginTop: 10 },
    header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: theme.border },
    title: { fontSize: 19, fontWeight: '700', color: theme.text, marginBottom: 4 },
    content: { padding: 20 }, section: { marginBottom: 24 },
    label: { fontSize: 15, color: theme.text, fontWeight: '600', marginBottom: 6 },
    hint: { fontSize: 12, color: theme.textMuted, lineHeight: 19 },
    choice: { flexDirection: 'row', alignItems: 'center', padding: 14, borderRadius: 12, borderWidth: 1, borderColor: theme.border, marginTop: 8 },
    selected: { backgroundColor: '#EFF6FF', borderColor: '#93B5FA' },
    choiceText: { flex: 1, paddingRight: 8 }, choiceTitle: { fontSize: 14, fontWeight: '600', color: theme.text, marginBottom: 3 },
    radio: { width: 20, height: 20, borderWidth: 1.5, borderColor: '#CBD5E1', borderRadius: 10, justifyContent: 'center', alignItems: 'center' },
    radioSelected: { borderColor: theme.primary }, dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.primary },
    unset: { minHeight: 44, justifyContent: 'center', alignItems: 'flex-start' },
    tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 10 },
    tag: { minHeight: 44, paddingHorizontal: 13, justifyContent: 'center', borderRadius: 10, borderWidth: 1, borderColor: theme.border },
    inputRow: { flexDirection: 'row', gap: 10, alignItems: 'center', marginBottom: 6 },
    input: { borderWidth: 1, borderColor: theme.border, borderRadius: 10, padding: 12, color: theme.text, fontSize: 14, minHeight: 46 },
    goalRow: { flexDirection: 'row', gap: 8, alignItems: 'center', marginVertical: 6 },
    close: { minWidth: 44, minHeight: 44, justifyContent: 'center', alignItems: 'center' },
    closeText: { fontSize: 26, color: theme.textMuted }, remove: { color: theme.danger, fontSize: 12 },
    footer: { paddingHorizontal: 20, paddingTop: 12, borderTopWidth: 1, borderTopColor: theme.border },
    actions: { flexDirection: 'row', gap: 10 }, warning: { backgroundColor: '#FFFBEB', padding: 12, borderRadius: 10, marginBottom: 12 },
    warningText: { fontSize: 12, color: theme.warning, lineHeight: 20, marginBottom: 8 }, error: { color: theme.danger, fontSize: 12, lineHeight: 20, marginBottom: 10 },
});
