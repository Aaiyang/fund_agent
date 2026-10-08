/**
 * 模型供应商设置。
 *
 * 三个口径照 Web 端保持一致：
 * 1. `POST /agent/llm/settings` 是**整份替换**，所以"删除某个档案"= 保存一份
 *    少了它的列表，服务端没有单条删除接口；
 * 2. `api_key` 传空串 = 沿用服务端已存的那把。界面回显的是 `key_hint` 掩码，
 *    明文 Key 只在点"保存"的那一次请求里出门，本地状态也只留刚输入的这一份；
 * 3. 至少保留一个档案，客户端先挡一次，服务端也会 400。
 *
 * 「设为当前」是立刻生效的全局切换，和"保存列表"是两件事：Agent 页与 Web 端
 * 用的是同一个当前档案，不是每条会话各选一个。
 */

import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { Async, EmptyState, describeError } from '@/components/states';
import { Badge, Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import type { LlmProfileItem } from '@/hooks/useLlmProfiles';
import { useLlmProfiles, useSaveLlmProfiles, useSwitchLlmProfile, useVendorModels } from '@/hooks/useLlmProfiles';

/** 列表里的一行档案：keyHint 是给人看的掩码，apiKey 只在本次会话里临时存在。 */
type Draft = { name: string; model: string; base_url: string; keyHint: string; apiKey: string };

function toDraft(profile: LlmProfileItem): Draft {
  return { name: profile.name, model: profile.model, base_url: profile.base_url, keyHint: profile.key_hint ?? '', apiKey: '' };
}

/** 掩码规则和服务端一致：只露前四位。 */
function keyHint(key: string): string {
  return key ? `${key.slice(0, 4)}****` : '';
}

function ProfileForm({
  initial,
  isNew,
  onCancel,
  onSubmit,
}: {
  initial: Draft;
  isNew: boolean;
  onCancel: () => void;
  onSubmit: (draft: Draft) => void;
}) {
  const [name, setName] = useState(initial.name);
  const [model, setModel] = useState(initial.model);
  const [baseUrl, setBaseUrl] = useState(initial.base_url);
  const [apiKey, setApiKey] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const probe = useVendorModels();

  function fetchModels() {
    if (!baseUrl.trim()) {
      setProblem('先填写接口地址');
      return;
    }
    if (!apiKey.trim()) {
      setProblem('先填写 API Key 才能查询该厂家有哪些模型');
      return;
    }
    setProblem(null);
    probe.mutate(
      { base_url: baseUrl.trim(), api_key: apiKey.trim() },
      { onError: (error) => setProblem(describeError(error)) },
    );
  }

  function submit() {
    if (!name.trim() || !model.trim() || !baseUrl.trim()) {
      setProblem('名称、模型、接口地址都要填');
      return;
    }
    if (isNew && !apiKey.trim()) {
      setProblem('新档案需要填写 API Key');
      return;
    }
    onSubmit({
      name: name.trim(),
      model: model.trim(),
      base_url: baseUrl.trim(),
      keyHint: apiKey.trim() ? keyHint(apiKey) : initial.keyHint,
      apiKey: apiKey.trim(),
    });
  }

  return (
    <Card>
      <SectionTitle title={isNew ? '新增档案' : `编辑 ${initial.name}`} />
      <Field label="名称" value={name} onChangeText={setName} placeholder="例如 DeepSeek" />
      <Field label="接口地址" value={baseUrl} onChangeText={setBaseUrl} placeholder="https://api.example.com/v1" autoCapitalize="none" />
      <Field
        label="API Key"
        value={apiKey}
        onChangeText={setApiKey}
        secureTextEntry
        autoCapitalize="none"
        placeholder={isNew ? '填写厂家提供的 API Key' : `已配置 ${initial.keyHint || '（无）'}，留空保持不变`}
      />
      <Pressable accessibilityRole="button" onPress={fetchModels} style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 13, color: theme.primary }}>{probe.isPending ? '正在查询…' : '获取该 Key 可用的模型列表'}</Text>
      </Pressable>
      {probe.data?.models?.length ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ alignItems: 'center', marginBottom: 8 }}>
          {probe.data.models.slice(0, 40).map((item) => (
            <Chip key={item} label={item} active={item === model} onPress={() => setModel(item)} />
          ))}
        </ScrollView>
      ) : null}
      <Field label="模型" value={model} onChangeText={setModel} placeholder="deepseek-chat" autoCapitalize="none" />
      {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginBottom: 10 }}>{problem}</Text> : null}
      <View style={{ flexDirection: 'row' }}>
        <View style={{ flex: 1, marginRight: 8 }}>
          <Button label="取消" variant="secondary" onPress={onCancel} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="填进列表" onPress={submit} />
        </View>
      </View>
    </Card>
  );
}

function ProfileList({ initial, activeName }: { initial: Draft[]; activeName: string }) {
  const [drafts, setDrafts] = useState<Draft[]>(initial);
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useSaveLlmProfiles();
  const switchProfile = useSwitchLlmProfile();

  function commit(draft: Draft) {
    setDrafts((prev) => (editing === null ? [...prev, draft] : prev.map((item, index) => (index === editing ? draft : item))));
    setEditing(null);
    setAdding(false);
    setNotice('已填进列表，还没保存到服务端');
  }

  function remove(index: number) {
    if (drafts.length <= 1) {
      setProblem('至少需要保留一个供应商档案');
      return;
    }
    setDrafts((prev) => prev.filter((_, position) => position !== index));
    setNotice('已移出列表，还没保存到服务端');
  }

  function saveAll() {
    if (!drafts.length) {
      setProblem('至少需要保留一个供应商档案');
      return;
    }
    setProblem(null);
    save.mutate(
      // 没重新输入 Key 的行传空串，意思是"沿用服务端已存的那把"。
      drafts.map(({ name, model, base_url, apiKey }) => ({ name, model, base_url, api_key: apiKey })),
      {
        onSuccess: () => setNotice('已保存，立即生效。密钥只保存在服务端。'),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <>
      <Card>
        <SectionTitle
          title="供应商档案"
          action="新增档案"
          onAction={() => {
            setAdding(true);
            setEditing(null);
          }}
        />
        {drafts.map((item, index) => (
          <View
            key={`${item.name}-${index}`}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              paddingVertical: 10,
              borderTopWidth: 1,
              borderTopColor: theme.border,
            }}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Text style={{ fontSize: 15, color: theme.text, fontWeight: '500' }}>{item.name || '（未命名）'}</Text>
                {activeName === item.name ? (
                  <View style={{ marginLeft: 8 }}>
                    <Badge label="当前" tone="muted" />
                  </View>
                ) : null}
              </View>
              <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
                {item.model} · {item.keyHint ? `Key ${item.keyHint}` : '未配置 Key'}
              </Text>
              <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }} numberOfLines={1}>
                {item.base_url}
              </Text>
            </View>
            {activeName !== item.name ? (
              <Pressable
                accessibilityRole="button"
                hitSlop={8}
                onPress={() => switchProfile.mutate(item.name)}
                style={{ paddingHorizontal: 8 }}
              >
                <Text style={{ fontSize: 13, color: theme.primary }}>
                  {switchProfile.isPending && switchProfile.variables === item.name ? '切换中…' : '设为当前'}
                </Text>
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="编辑这个档案"
              hitSlop={8}
              onPress={() => {
                setEditing(index);
                setAdding(false);
              }}
              style={{ paddingHorizontal: 8 }}
            >
              <Text style={{ fontSize: 13, color: theme.textMuted }}>编辑</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="删除这个档案"
              hitSlop={8}
              disabled={drafts.length <= 1}
              onPress={() => remove(index)}
              style={{ paddingHorizontal: 8, opacity: drafts.length <= 1 ? 0.35 : 1 }}
            >
              <Text style={{ fontSize: 13, color: theme.danger }}>删除</Text>
            </Pressable>
          </View>
        ))}
      </Card>

      {adding ? (
        <ProfileForm
          initial={{ name: '', model: '', base_url: '', keyHint: '', apiKey: '' }}
          isNew
          onCancel={() => setAdding(false)}
          onSubmit={commit}
        />
      ) : null}
      {editing !== null && drafts[editing] ? (
        <ProfileForm
          key={`edit-${editing}`}
          initial={drafts[editing]}
          isNew={false}
          onCancel={() => setEditing(null)}
          onSubmit={commit}
        />
      ) : null}

      <Card>
        {notice ? <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 10 }}>{notice}</Text> : null}
        {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginBottom: 10 }}>{problem}</Text> : null}
        <Button label="保存到服务端" loading={save.isPending} onPress={saveAll} />
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 8, lineHeight: 18 }}>
          保存后立即生效；API Key 只存在服务端，本机不留。整份列表会被替换，删除档案也一样要点保存才落地。
        </Text>
      </Card>
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
        {(data) => {
          const items = data.profiles ?? [];
          // key 用档案名单：保存后名单变了会整体重挂，草稿状态自然回到新数据上。
          return <ProfileList key={items.map((item) => item.name).join('|')} initial={items.map(toDraft)} activeName={data.active} />;
        }}
      </Async>
    </Screen>
  );
}
