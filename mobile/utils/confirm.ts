/**
 * 破坏性操作的确认，走应用自己的弹窗。
 *
 * `Alert.alert` 在 react-native-web 上已被证实是空操作（导出就是个空函数），
 * `window.confirm` 在 webview 里同样可能被吞——两种做法按下按钮都毫无动静。
 * 由根布局挂载一个弹窗，全平台共用，确认这一步才看得见。
 */

import { useConfirmStore } from '@/stores/confirm';

export function confirmAction(title: string, message: string, onConfirm: () => void): void {
  useConfirmStore.getState().show({ title, message, confirmLabel: '确定', onConfirm });
}
