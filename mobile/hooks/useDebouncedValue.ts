/** Hold a value back until typing stops, for anything that costs a request. */

import { useEffect, useState } from 'react';

export function useDebouncedValue<T>(value: T, delay = 350): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
