/**
 * Shared Query cache. Lives on its own so signing out can clear it: the store
 * cannot reach into the layout module without closing an import cycle.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/api/client';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Client-side rejections (401/404/409/422) never succeed on retry.
      retry: (failureCount, error) => {
        const status = error instanceof ApiError ? error.status : undefined;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});
