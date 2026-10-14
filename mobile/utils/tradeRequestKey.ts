/** 同一表单参数的网络重试沿用同一键；成功后由表单清空。 */
export function tradeRequestKey(keys: Map<string, string>, payload: object): string {
  const signature = JSON.stringify(payload);
  const previous = keys.get(signature);
  if (previous) return previous;
  const key = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  keys.set(signature, key);
  return key;
}
