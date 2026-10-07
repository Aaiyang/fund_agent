/**
 * 共享的查询缓存。单独成模块是为了退出登录时能清掉它：否则 store 想够到
 * layout 模块就得绕一个导入环。
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/api/client';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // 客户端就已被拒绝的 4xx（401/404/409/422）重试也不会成功。
      retry: (failureCount, error) => {
        const status = error instanceof ApiError ? error.status : undefined;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});
