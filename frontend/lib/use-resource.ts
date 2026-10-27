import { useCallback, useEffect, useRef, useState } from 'react';

export type ResourceState<T> = {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
};

type Snapshot<T> = {
  requestKey: string;
  data: T | null;
  error: string;
};

/**
 * 很小的 GET 资源 hook；页面自己控制依赖，失败保留错误文案。
 * loading 由“当前请求键是否已有结果”推导，避免在 effect 里同步 setState。
 */
export function useResource<T>(
  loader: () => Promise<T>,
  key: string,
): ResourceState<T> {
  const [version, setVersion] = useState(0);
  const requestKey = `${key}:${version}`;
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({
    requestKey: '',
    data: null,
    error: '',
  });
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  useEffect(() => {
    let cancelled = false;
    void loaderRef
      .current()
      .then((value) => {
        if (!cancelled) setSnapshot({ requestKey, data: value, error: '' });
      })
      .catch((loadError: unknown) => {
        if (!cancelled)
          setSnapshot({
            requestKey,
            data: null,
            error: loadError instanceof Error ? loadError.message : '加载失败',
          });
      });
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const settled = snapshot.requestKey === requestKey;
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return {
    data: settled ? snapshot.data : null,
    loading: !settled,
    error: settled ? snapshot.error : '',
    reload,
  };
}
