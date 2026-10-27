/** 加载/失败/空状态三件套，保证每个页面都不致于摆一块空面板（spec Phase 6）。 */

import { type ReactNode } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';

import type { UseQueryResult } from '@tanstack/react-query';

import { Button } from '@/components/ui';
import { theme } from '@/constants/theme';

export function LoadingState({ label = '加载中…' }: { label?: string }) {
  return (
    <View style={{ padding: 24, alignItems: 'center' }}>
      <ActivityIndicator color={theme.primary} />
      <Text style={{ marginTop: 8, color: theme.textMuted, fontSize: 13 }}>{label}</Text>
    </View>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <View style={{ padding: 28, alignItems: 'center' }}>
      <View
        style={{
          width: 44,
          height: 44,
          borderRadius: 22,
          marginBottom: 12,
          backgroundColor: theme.primarySoft,
          borderWidth: 1,
          borderColor: theme.border,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: theme.primary, opacity: 0.5 }} />
      </View>
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>{title}</Text>
      {hint ? <Text style={{ marginTop: 6, fontSize: 13, color: theme.textMuted, textAlign: 'center', lineHeight: 20 }}>{hint}</Text> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={{ padding: 20, alignItems: 'center' }}>
      <View style={{ backgroundColor: theme.dangerSoft, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 10, marginBottom: 12 }}>
        <Text style={{ fontSize: 14, color: theme.danger, textAlign: 'center', lineHeight: 20 }}>{message}</Text>
      </View>
      {onRetry ? <Button label="重试" variant="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

/** 渲染查询数据；渲染不了就摆出对应的状态。 */
export function Async<T>({
  query,
  children,
  empty,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  empty?: (data: T) => ReactNode;
}) {
  const data = query.data;
  // *后台*重取失败时已加载的数据仍在，但 isError 照样翻真；错误分支不能压过
  // 保留的数据：否则任何一次编辑之后，可用的页面（连同按钮）都会被
  // 换成一个孤零零的“重试”。
  if (data === undefined || data === null) {
    if (query.isPending) return <LoadingState />;
    if (query.isError) {
      return <ErrorState message={describeError(query.error)} onRetry={() => void query.refetch()} />;
    }
    return <EmptyState title="没有读到数据" hint="下拉刷新试试。" />;
  }
  const placeholder = empty ? empty(data) : null;
  if (placeholder) return placeholder;
  return (
    <>
      {query.isError ? (
        <Text style={{ fontSize: 12, color: theme.warning, marginBottom: 8 }}>刷新失败，下面是上次加载的结果</Text>
      ) : null}
      {children(data)}
    </>
  );
}

export function describeError(error: unknown): string {
  const status = (error as { status?: number } | undefined)?.status;
  const code = (error as { code?: string } | undefined)?.code;
  const message = error instanceof Error ? error.message : String(error);
  if (code === 'account_name_taken') return '该账户名称已存在';
  if (status === 401) return '登录已过期，请重新登录';
  if (status === 409) return '数据已被其他操作更新，请刷新后重试';
  return message || '请求失败';
}
