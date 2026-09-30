/**
 * Destructive-action confirmation, asked of the app's own dialog.
 *
 * `Alert.alert` is a verified no-op in react-native-web (its export is an empty
 * function) and a webview can swallow `window.confirm` too — either way the
 * button looks pressed and nothing happens. One dialog mounted by the root
 * layout answers for every platform, so the confirm step can be seen.
 */

import { useConfirmStore } from '@/stores/confirm';

export function confirmAction(title: string, message: string, onConfirm: () => void): void {
  useConfirmStore.getState().show({ title, message, confirmLabel: '确定', onConfirm });
}
