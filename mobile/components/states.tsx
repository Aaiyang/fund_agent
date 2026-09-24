/** Loading / error / empty states, so no screen renders a blank panel (spec Phase 6). */

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
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>{title}</Text>
      {hint ? <Text style={{ marginTop: 6, fontSize: 13, color: theme.textMuted, textAlign: 'center' }}>{hint}</Text> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={{ padding: 20, alignItems: 'center' }}>
      <Text style={{ fontSize: 14, color: theme.danger, textAlign: 'center', marginBottom: 12 }}>{message}</Text>
      {onRetry ? <Button label="重试" variant="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

/** Render a query's data, or the right state for it. */
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
  // A failed *background* refetch keeps the data already loaded but still flips
  // isError on, so the error branch must not win over retained data: that would
  // swap a working screen (and its buttons) for a bare 重试 after any edit.
  if (data === undefined || data === null) {
    if (query.isPending) return <LoadingState />;
    if (query.isError) {
      return <ErrorState message={describeError(query.error)} onRetry={() => void query.refetch()} />;
    }
    return <EmptyState title="暂无数据" />;
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
  const message = error instanceof Error ? error.message : String(error);
  if (status === 401) return '登录已过期，请重新登录';
  if (status === 409) return '数据已被其他操作更新，请刷新后重试';
  return message || '请求失败';
}
