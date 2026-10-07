/** 把值的更新压到停止输入之后，供那种动一下就发一次请求的场景用。 */

import { useEffect, useState } from 'react';

export function useDebouncedValue<T>(value: T, delay = 350): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
