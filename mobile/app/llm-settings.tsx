/**
 * 模型设置：当前模型、个人档案列表与编辑面板。
 *
 * 后端语义照旧：
 * 1. `POST /agent/llm/settings` 是**整份替换**，所以删除档案 = 提交一份少了它的列表；
 * 2. `api_key` 传空串 = 沿用服务端已存的那把。改名或更换接口地址时服务端无法确定
 *    沿用哪把，必须重新填写；
 * 3. 基础 GLM Flash 档案只读，个人档案可增删改；切换只影响当前登录用户。
 *
 * 编辑做成底部面板、提交即保存，不再有「填进列表 → 再保存到服务端」两步。
 */

import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Async, EmptyState, describeError } from '@/components/states';
import { Badge, Button, Card, Chip, Divider, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import type { LlmProfileItem, LlmProfiles } from '@/hooks/useLlmProfiles';
import { useLlmProfiles, useSaveLlmProfiles, useSwitchLlmProfile, useVendorModels } from '@/hooks/useLlmProfiles';
import { confirmAction } from '@/utils/confirm';

/** 列表里的一行档案：keyHint 是给人看的掩码，apiKey 只在本次会话里临时存在。 */
type Draft = { name: string; model: string; base_url: string; apiKey: string };
type Editor = { mode: 'new' } | { mode: 'edit'; index: number };

function personalProfiles(data: LlmProfiles): LlmProfileItem[] {
  return data.profiles.filter((profile) => !profile.read_only);
}

/** 当前生效的档案；服务端保证 active 一定在列表里。 */
function activeProfile(data: LlmProfiles): LlmProfileItem {
  return data.profiles.find((profile) => profile.name === data.active) ?? data.profiles[0];
}

function ProfileAvatar({ name, active }: { name: string; active: boolean }) {
  return (
    <View
      style={{
        width: 40,
        height: 40,
        borderRadius: 13,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: active ? theme.primary : theme.surfaceMuted,
        borderWidth: 1,
        borderColor: active ? theme.primary : theme.border,
      }}
    >
      <Text style={{ fontSize: 15, fontWeight: '700', color: active ? theme.primaryInk : theme.textMuted }}>
        {name.slice(0, 1).toUpperCase()}
      </Text>
    </View>
  );
}

function CurrentModelCard({ data }: { data: LlmProfiles }) {
  const current = activeProfile(data);
  if (!current) return null;
  return (
    <Card style={{ backgroundColor: theme.surfaceStrong }}>
      <Text style={{ fontSize: 10, fontWeight: '700', letterSpacing: 1.4, color: theme.gold }}>CURRENT MODEL</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 12 }}>
        <ProfileAvatar name={current.name} active />
        <View style={{ flex: 1, minWidth: 0, marginLeft: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 7 }}>
            <Text numberOfLines={1} style={{ flexShrink: 1, fontSize: 19, fontWeight: '600', color: theme.text }}>
              {current.name}
            </Text>
            {current.read_only ? <Badge label="基础" tone="muted" /> : null}
          </View>
          <Text numberOfLines={1} style={{ marginTop: 3, fontSize: 13, color: theme.textMuted }}>{current.model}</Text>
          <Text numberOfLines={1} style={{ marginTop: 2, fontSize: 11, color: theme.textFaint }}>{current.base_url}</Text>
        </View>
        <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: theme.primary, alignItems: 'center', justifyContent: 'center', marginLeft: 10 }}>
          <SymbolView name={{ ios: 'checkmark', android: 'check', web: 'check' }} tintColor={theme.primaryInk} size={14} />
        </View>
      </View>
      <Divider style={{ marginTop: 14, marginBottom: 10 }} />
      <Text style={{ fontSize: 12, color: theme.textFaint }}>共 {data.profiles.length} 个档案</Text>
    </Card>
  );
}

function ProfileRow({
  profile,
  active,
  busy,
  disabled,
  onSwitch,
  onEdit,
  onDelete,
}: {
  profile: LlmProfileItem;
  active: boolean;
  busy: boolean;
  disabled: boolean;
  onSwitch: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  return (
    <View style={{ paddingVertical: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <ProfileAvatar name={profile.name} active={active} />
        <View style={{ flex: 1, minWidth: 0, marginLeft: 11 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text numberOfLines={1} style={{ flexShrink: 1, fontSize: 15, fontWeight: '600', color: theme.text }}>
              {profile.name}
            </Text>
            {active ? <Badge label="当前" tone="success" /> : null}
            {profile.read_only ? <Badge label="只读" tone="muted" /> : null}
          </View>
          <Text numberOfLines={1} style={{ marginTop: 3, fontSize: 12, color: theme.textMuted }}>
            {profile.model}
            {profile.read_only ? ' · 基础模型' : profile.key_hint ? ` · Key ${profile.key_hint}` : ' · 未配置 Key'}
          </Text>
          <Text numberOfLines={1} style={{ marginTop: 2, fontSize: 11, color: theme.textFaint }}>{profile.base_url}</Text>
        </View>
        {active ? null : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`切换到 ${profile.name}`}
            disabled={disabled}
            onPress={onSwitch}
            style={({ pressed }) => ({
              marginLeft: 8,
              paddingHorizontal: 10,
              paddingVertical: 6,
              borderRadius: 999,
              borderWidth: 1,
              borderColor: theme.primary,
              backgroundColor: theme.primarySoft,
              opacity: pressed ? 0.7 : 1,
            })}
          >
            {busy ? (
              <ActivityIndicator size="small" color={theme.primary} />
            ) : (
              <Text style={{ fontSize: 12, fontWeight: '600', color: theme.primary }}>设为当前</Text>
            )}
          </Pressable>
        )}
      </View>
      {onEdit || onDelete ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', marginLeft: 51, marginTop: 7, gap: 16 }}>
          {onEdit ? (
            <Pressable accessibilityRole="button" hitSlop={8} disabled={disabled} onPress={onEdit} style={{ opacity: disabled ? 0.5 : 1 }}>
              <Text style={{ fontSize: 12, color: theme.textMuted }}>编辑</Text>
            </Pressable>
          ) : null}
          {onDelete ? (
            <Pressable accessibilityRole="button" hitSlop={8} disabled={disabled} onPress={onDelete} style={{ opacity: disabled ? 0.5 : 1 }}>
              <Text style={{ fontSize: 12, color: theme.danger }}>删除</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function ProfileEditor({
  initial,
  mode,
  readOnlyHint,
  saving,
  problem,
  onClose,
  onSubmit,
}: {
  initial: Draft;
  mode: 'new' | 'edit';
  readOnlyHint: string;
  saving: boolean;
  problem: string | null;
  onClose: () => void;
  onSubmit: (draft: Draft) => void;
}) {
  const insets = useSafeAreaInsets();
  const [name, setName] = useState(initial.name);
  const [model, setModel] = useState(initial.model);
  const [baseUrl, setBaseUrl] = useState(initial.base_url);
  const [apiKey, setApiKey] = useState('');
  const [localProblem, setLocalProblem] = useState<string | null>(null);
  const probe = useVendorModels();

  function fetchModels() {
    if (!baseUrl.trim()) {
      setLocalProblem('先填写接口地址');
      return;
    }
    if (!apiKey.trim()) {
      setLocalProblem('先填写 API Key 才能查询该厂家有哪些模型');
      return;
    }
    setLocalProblem(null);
    probe.mutate(
      { base_url: baseUrl.trim(), api_key: apiKey.trim() },
      { onError: (error) => setLocalProblem(describeError(error)) },
    );
  }

  function submit() {
    if (!name.trim() || !model.trim() || !baseUrl.trim()) {
      setLocalProblem('名称、模型、接口地址都要填');
      return;
    }
    if (mode === 'new' && !apiKey.trim()) {
      setLocalProblem('新档案需要填写 API Key');
      return;
    }
    setLocalProblem(null);
    onSubmit({
      name: name.trim(),
      model: model.trim(),
      base_url: baseUrl.trim(),
      apiKey: apiKey.trim(),
    });
  }

  return (
    <Modal transparent visible animationType="slide" onRequestClose={saving ? undefined : onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="关闭编辑面板" disabled={saving} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 14) }]} accessibilityViewIsModal>
          <View style={styles.handle} />
          <View style={styles.sheetHeader}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.eyebrow}>{mode === 'new' ? 'CREATE PROFILE' : 'EDIT PROFILE'}</Text>
              <Text style={styles.sheetTitle}>{mode === 'new' ? '新增模型档案' : '编辑模型档案'}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="关闭编辑面板"
              hitSlop={8}
              disabled={saving}
              onPress={onClose}
              style={styles.close}
            >
              <SymbolView name={{ ios: 'xmark', android: 'close', web: 'close' }} tintColor={theme.textMuted} size={17} />
            </Pressable>
          </View>

          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.sheetContent}>
            <Field label="名称" value={name} onChangeText={setName} placeholder="例如 DeepSeek" />
            <Field label="接口地址" value={baseUrl} onChangeText={setBaseUrl} placeholder="https://api.example.com/v1" autoCapitalize="none" />
            <Field
              label="API Key"
              value={apiKey}
              onChangeText={setApiKey}
              secureTextEntry
              autoCapitalize="none"
              placeholder={mode === 'new' ? '填写厂家提供的 API Key' : `${readOnlyHint ? `已配置 ${readOnlyHint}，` : ''}留空保持不变`}
            />
            <Pressable accessibilityRole="button" onPress={fetchModels} style={{ alignSelf: 'flex-start', marginBottom: 12 }}>
              <Text style={{ fontSize: 13, fontWeight: '500', color: theme.primary }}>
                {probe.isPending ? '正在查询…' : '获取该 Key 可用的模型列表'}
              </Text>
            </Pressable>
            {probe.data?.models?.length ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 4 }}>
                {probe.data.models.slice(0, 40).map((item) => (
                  <Chip key={item} label={item} active={item === model} onPress={() => setModel(item)} />
                ))}
              </ScrollView>
            ) : null}
            <Field label="模型" value={model} onChangeText={setModel} placeholder="deepseek-chat" autoCapitalize="none" />

            {mode === 'edit' ? (
              <Text style={{ fontSize: 12, lineHeight: 18, color: theme.textFaint, marginBottom: 10 }}>
                改名或更换接口地址后，需要重新填写 API Key。
              </Text>
            ) : null}
            {localProblem ?? problem ? (
              <View style={{ backgroundColor: theme.dangerSoft, borderRadius: 10, padding: 10, marginBottom: 10 }}>
                <Text style={{ fontSize: 13, lineHeight: 19, color: theme.danger }}>{localProblem ?? problem}</Text>
              </View>
            ) : null}

            <View style={{ flexDirection: 'row', gap: 10, marginTop: 2 }}>
              <View style={{ flex: 1 }}>
                <Button label="取消" variant="secondary" disabled={saving} onPress={onClose} />
              </View>
              <View style={{ flex: 1 }}>
                <Button label={mode === 'new' ? '保存档案' : '保存修改'} loading={saving} onPress={submit} />
              </View>
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function ProfilesView({ data }: { data: LlmProfiles }) {
  const save = useSaveLlmProfiles();
  const switchProfile = useSwitchLlmProfile();
  const [editor, setEditor] = useState<Editor | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const personal = personalProfiles(data);
  const current = activeProfile(data);

  function toUpdate(profiles: LlmProfileItem[]) {
    return profiles.map((profile) => ({
      name: profile.name,
      model: profile.model,
      base_url: profile.base_url,
      api_key: '',
    }));
  }

  function submit(draft: Draft) {
    if (!editor) return;
    // data.profiles 的第 0 项是基础档案，个人档案从 1 开始；
    // 编辑时保留原名不算重复。
    const nameTaken = data.profiles.some((profile) => profile.name === draft.name)
      && !(editor.mode === 'edit' && personal[editor.index]?.name === draft.name);
    if (nameTaken) {
      setProblem(`档案名称重复：${draft.name}`);
      return;
    }
    const next = personal.map((profile) => ({
      name: profile.name,
      model: profile.model,
      base_url: profile.base_url,
      api_key: '',
    }));
    if (editor.mode === 'new') {
      next.push({ name: draft.name, model: draft.model, base_url: draft.base_url, api_key: draft.apiKey });
    } else {
      const original = personal[editor.index];
      if (!original) return;
      const renamed = draft.name !== original.name;
      const moved = draft.base_url.replace(/\/+$/, '') !== original.base_url.replace(/\/+$/, '');
      if ((renamed || moved) && !draft.apiKey) {
        setProblem('改名或更换接口地址后，需要重新填写 API Key');
        return;
      }
      next[editor.index] = { name: draft.name, model: draft.model, base_url: draft.base_url, api_key: draft.apiKey };
    }
    setProblem(null);
    save.mutate(next, {
      onSuccess: () => setEditor(null),
      onError: (error) => setProblem(describeError(error)),
    });
  }

  function remove(index: number) {
    const profile = personal[index];
    if (!profile) return;
    const extra = current?.name === profile.name ? '当前模型会回到基础 GLM Flash。' : '';
    confirmAction('删除模型档案', `删除「${profile.name}」后不可恢复。${extra}`, () => {
      setProblem(null);
      save.mutate(toUpdate(personal.filter((_, position) => position !== index)), {
        onError: (error) => setProblem(describeError(error)),
      });
    });
  }

  function switchTo(name: string) {
    setProblem(null);
    switchProfile.mutate(name, { onError: (error) => setProblem(describeError(error)) });
  }

  const editorInitial = editor?.mode === 'edit' ? personal[editor.index] : null;
  const editorDraft: Draft = editorInitial
    ? { name: editorInitial.name, model: editorInitial.model, base_url: editorInitial.base_url, apiKey: '' }
    : { name: '', model: '', base_url: '', apiKey: '' };

  return (
    <>
      <CurrentModelCard data={data} />

      <Card>
        <SectionTitle title="模型档案" action="新增档案" onAction={() => { setProblem(null); setEditor({ mode: 'new' }); }} />
        {problem ? (
          <View style={{ backgroundColor: theme.dangerSoft, borderRadius: 10, padding: 10, marginBottom: 8 }}>
            <Text style={{ fontSize: 13, lineHeight: 19, color: theme.danger }}>{problem}</Text>
          </View>
        ) : null}
        {data.profiles.map((profile, index) => {
          const personalIndex = personal.findIndex((item) => item.name === profile.name);
          return (
            <View key={profile.name}>
              {index > 0 ? <Divider /> : null}
              <ProfileRow
                profile={profile}
                active={profile.name === data.active}
                busy={switchProfile.isPending && switchProfile.variables === profile.name}
                disabled={switchProfile.isPending || save.isPending}
                onSwitch={() => switchTo(profile.name)}
                onEdit={profile.read_only ? undefined : () => {
                  setProblem(null);
                  setEditor({ mode: 'edit', index: personalIndex });
                }}
                onDelete={profile.read_only ? undefined : () => remove(personalIndex)}
              />
            </View>
          );
        })}
        {!personal.length ? (
          <View style={{ backgroundColor: theme.surfaceSoft, borderRadius: 12, padding: 12, marginTop: 4 }}>
            <Text style={{ fontSize: 12, lineHeight: 19, color: theme.textMuted }}>
              还没有个人档案。新增后可以选择任意 OpenAI-compatible 厂家与模型。
            </Text>
          </View>
        ) : null}
      </Card>

      {editor ? (
        <ProfileEditor
          key={editor.mode === 'new' ? 'new' : `edit-${editor.index}`}
          initial={editorDraft}
          mode={editor.mode}
          readOnlyHint={editorInitial?.key_hint ?? ''}
          saving={save.isPending}
          problem={problem}
          onClose={() => { if (!save.isPending) { setEditor(null); setProblem(null); } }}
          onSubmit={submit}
        />
      ) : null}
    </>
  );
}

export default function LlmSettingsScreen() {
  const profiles = useLlmProfiles();

  return (
    <Screen>
      <Async
        query={profiles}
        empty={(data) =>
          !data.profiles?.length ? <EmptyState title="服务端还没有档案" hint="新增一个供应商档案后保存即可。" /> : null
        }
      >
        {(data) => <ProfilesView data={data} />}
      </Async>
    </Screen>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: theme.overlay, justifyContent: 'flex-end' },
  sheet: {
    width: '100%',
    maxHeight: '92%',
    maxWidth: 640,
    alignSelf: 'center',
    backgroundColor: theme.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: theme.border,
  },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: theme.borderStrong, alignSelf: 'center', marginTop: 10 },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  eyebrow: { fontSize: 10, fontWeight: '700', letterSpacing: 1.4, color: theme.gold },
  sheetTitle: { fontSize: 21, fontWeight: '600', color: theme.text, marginTop: 4 },
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
  sheetContent: { padding: 20, paddingBottom: 8 },
});
