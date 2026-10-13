import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View } from 'react-native';

import { Async, EmptyState, describeError } from '@/components/states';
import { Button, Card, Chip, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useUiStore } from '@/stores/ui';
import { confirmAction } from '@/utils/confirm';
import {
  useCreateWatchlistGroup,
  useDeleteWatchlistGroup,
  useUpdateWatchlistGroup,
  useWatchlist,
  useWatchlistGroups,
  type WatchlistGroup,
} from '@/hooks/useWatchlist';

/** 分组管理：新建、改名、删除与组内排序（spec 3.3）。 */
export default function WatchlistGroupsScreen() {
  const groups = useWatchlistGroups();
  const create = useCreateWatchlistGroup();
  const update = useUpdateWatchlistGroup();
  const remove = useDeleteWatchlistGroup();
  const groupId = useUiStore((state) => state.groupId);
  const setGroupId = useUiStore((state) => state.setGroupId);
  const [name, setName] = useState('');
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null);

  /** 键盘的回车与“创建”按钮走同一条路径，免得两处各写一份成功回调。 */
  function createGroup() {
    const trimmed = name.trim();
    if (!trimmed || create.isPending) return;
    create.mutate(
      { name: trimmed },
      {
        onSuccess: (group) => {
          setName('');
          setSelectedGroup(group.id);
        },
      },
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <Card>
          <SectionTitle title="新建分组" />
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="请输入分组名称"
            placeholderTextColor={theme.textFaint}
            returnKeyType="done"
            onSubmitEditing={createGroup}
            style={{
              borderWidth: 1,
              borderColor: theme.border,
              borderRadius: 10,
              paddingHorizontal: 12,
              paddingVertical: 10,
              fontSize: 15,
              color: theme.text,
              backgroundColor: theme.surface,
              marginBottom: 10,
            }}
          />
          <Button label="创建" disabled={!name.trim()} loading={create.isPending} onPress={createGroup} />
        </Card>

        <Card>
          <SectionTitle title="分组列表" />
          <Async
            query={groups}
            empty={(data) =>
              data.items.length === 0 ? <EmptyState title="还没有分组" hint="默认视图“全部”始终可用" /> : null
            }
          >
            {(data) => (
              <View>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                  {data.items.map((group) => (
                    <Chip
                      key={group.id}
                      label={`${group.name}(${group.fund_count})`}
                      active={selectedGroup === group.id}
                      onPress={() => setSelectedGroup(group.id)}
                    />
                  ))}
                </View>
                {data.items.map((group) => (
                  <GroupRow
                    key={group.id}
                    group={group}
                    update={update}
                    remove={remove}
                    onDeleted={() => {
                      // 筛选若还指向被删除的分组，自选页会停在一张空列表上无从退出，
                      // 所以删除后要把本组和全局两处选中态都清空。
                      if (selectedGroup === group.id) setSelectedGroup(null);
                      if (groupId === group.id) setGroupId(null);
                    }}
                  />
                ))}
              </View>
            )}
          </Async>
        </Card>

        {/* 用 key 按分组重新挂载编辑器：它只按打开时那个分组初始化顺序，
            否则会把上一个分组的列表带到当前分组界面上。 */}
        {selectedGroup !== null ? <GroupOrderEditor key={selectedGroup} groupId={selectedGroup} update={update} /> : null}
      </Screen>
    </KeyboardAvoidingView>
  );
}

function GroupRow({
  group,
  update,
  remove,
  onDeleted,
}: {
  group: WatchlistGroup;
  update: ReturnType<typeof useUpdateWatchlistGroup>;
  remove: ReturnType<typeof useDeleteWatchlistGroup>;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(group.name);
  const [problem, setProblem] = useState<string | null>(null);
  // 一次只改一行：整列共用 isPending 会让每个分组都同时显示“处理中…”。
  // 排序保存也走同一个 update，所以按这次请求到底带了哪个字段判断。
  const renaming = update.isPending && update.variables?.groupId === group.id && update.variables?.name !== undefined;
  const removing = remove.isPending && remove.variables === group.id;

  /** 键盘回车与“保存”按钮走同一条路径。 */
  function saveName() {
    const trimmed = draft.trim();
    if (!trimmed || renaming) return;
    update.mutate(
      { groupId: group.id, name: trimmed },
      {
        onSuccess: () => setEditing(false),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  if (editing) {
    return (
      <View style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.border }}>
        <TextInput
          value={draft}
          onChangeText={setDraft}
          autoFocus
          placeholder="请输入分组名称"
          placeholderTextColor={theme.textFaint}
          returnKeyType="done"
          onSubmitEditing={saveName}
          style={{
            borderWidth: 1,
            borderColor: theme.border,
            borderRadius: 8,
            paddingHorizontal: 10,
            paddingVertical: 8,
            fontSize: 14,
            color: theme.text,
            marginBottom: 8,
          }}
        />
        {problem ? <Text style={{ fontSize: 12, color: theme.danger, marginBottom: 8 }}>{problem}</Text> : null}
        <View style={{ flexDirection: 'row' }}>
          <View style={{ flex: 1, marginRight: 8 }}>
            <Button label="保存" disabled={!draft.trim()} loading={renaming} onPress={saveName} />
          </View>
          <View style={{ flex: 1 }}>
            <Button
              label="取消"
              variant="secondary"
              onPress={() => {
                setProblem(null);
                setDraft(group.name);
                setEditing(false);
              }}
            />
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.border }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Text style={{ fontSize: 15, color: theme.text, flex: 1 }}>{`${group.name} · ${group.fund_count} 只`}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`改名 ${group.name}`}
          hitSlop={10}
          onPress={() => setEditing(true)}
          style={({ pressed }) => [{ opacity: pressed ? 0.85 : 1 }]}
        >
          <Text style={{ color: theme.primary, fontSize: 13, marginRight: 14 }}>改名</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`删除分组 ${group.name}`}
          hitSlop={10}
          disabled={removing}
          onPress={() =>
            confirmAction(
              '删除分组',
              `分组“${group.name}”将被删除，删除后无法恢复；组内基金仍保留在自选。`,
              () => remove.mutate(group.id, { onSuccess: onDeleted, onError: (error) => setProblem(describeError(error)) }),
            )
          }
          style={({ pressed }) => [{ opacity: removing ? 0.55 : pressed ? 0.85 : 1 }]}
        >
          <Text style={{ color: theme.danger, fontSize: 13 }}>删除</Text>
        </Pressable>
      </View>
      {problem ? (
        <Text style={{ fontSize: 12, color: theme.danger, marginTop: 6 }} numberOfLines={2}>
          {problem}
        </Text>
      ) : null}
    </View>
  );
}

function GroupOrderEditor({
  groupId,
  update,
}: {
  groupId: number;
  update: ReturnType<typeof useUpdateWatchlistGroup>;
}) {
  const members = useWatchlist(groupId);
  const [order, setOrder] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const codes = order ?? (members.data?.items ?? []).map((item) => item.fund_code);
  const names = new Map((members.data?.items ?? []).map((item) => [item.fund_code, item.fund_name]));
  // 排序保存与改名共用同一个 mutation，按这次请求带的字段判断该不该亮“处理中…”。
  const savingOrder =
    update.isPending && update.variables?.groupId === groupId && update.variables?.fund_codes !== undefined;

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= codes.length) return;
    const next = [...codes];
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
  }

  return (
    <Card>
      <SectionTitle title="组内排序" />
      <Async
        query={members}
        empty={(data) =>
          data.items.length === 0 ? <EmptyState title="还没有基金" hint="可在自选页加自选时勾选这个分组" /> : null
        }
      >
        {(data) => (
          <View>
            {data.items.length === 0 ? null : (
              <View>
                {codes.map((code, index) => (
                  <View key={code} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8 }}>
                    <Text style={{ fontSize: 12, color: theme.textFaint, width: 24 }}>{index + 1}</Text>
                    <Text style={{ fontSize: 14, color: theme.text, flex: 1 }} numberOfLines={1}>
                      {names.get(code) ?? code}
                    </Text>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`上移 ${names.get(code) ?? code}`}
                      hitSlop={10}
                      disabled={index === 0}
                      onPress={() => move(index, -1)}
                      style={({ pressed }) => [{ opacity: index === 0 ? 0.55 : pressed ? 0.85 : 1 }]}
                    >
                      <Text style={{ color: theme.primary, fontSize: 16, marginRight: 16 }}>↑</Text>
                    </Pressable>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`下移 ${names.get(code) ?? code}`}
                      hitSlop={10}
                      disabled={index === codes.length - 1}
                      onPress={() => move(index, 1)}
                      style={({ pressed }) => [{ opacity: index === codes.length - 1 ? 0.55 : pressed ? 0.85 : 1 }]}
                    >
                      <Text style={{ color: theme.primary, fontSize: 16 }}>↓</Text>
                    </Pressable>
                  </View>
                ))}
                <Button
                  label="保存组内顺序"
                  loading={savingOrder}
                  onPress={() => {
                    update.mutate(
                      { groupId, fund_codes: codes },
                      {
                        onSuccess: () => setOrder(null),
                        onError: (error) => setProblem(describeError(error)),
                      },
                    );
                  }}
                />
                {problem ? <Text style={{ fontSize: 12, color: theme.danger, marginTop: 8 }}>{problem}</Text> : null}
                {order ? (
                  <Text style={{ fontSize: 12, color: theme.warning, marginTop: 8 }}>
                    有未保存的顺序调整，点击“保存组内顺序”写入后端。
                  </Text>
                ) : null}
              </View>
            )}
          </View>
        )}
      </Async>
    </Card>
  );
}
