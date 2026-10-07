/**
 * 给 web 端的横向 ScrollView 补上鼠标拖动平移。
 *
 * 浏览器里滚轮和触摸都能平移滚动容器，但鼠标按住拖动默认什么都不做，
 * 桌面窗口够不到右边缘之外的条目。监听器要绑在真正的 DOM 滚动节点上，
 * 因为 web 端 ScrollView 不保证透传 React Native 的 responder props。
 *
 * 原生端自带平移手势，这个 hook 在原生端什么都不做。
 *
 * `enabled` 同时充当重新绑定的信号：有些滚动容器要等父容器量出尺寸后才
 * 挂载（比如等 `onLayout` 的图表），否则这个 hook 会绑了个空、再不重试。
 */

import { type RefObject, useEffect } from 'react';
import { Platform, type ScrollView } from 'react-native';

export function useDragScroll(ref: RefObject<ScrollView | null>, enabled = true) {
  useEffect(() => {
    if (!enabled || Platform.OS !== 'web') return;
    const node = ref.current?.getScrollableNode() as HTMLElement | null;
    if (!node) return;

    let startX = 0;
    let startLeft = 0;
    let dragging = false;

    const onMouseDown = (event: MouseEvent) => {
      dragging = true;
      startX = event.clientX;
      startLeft = node.scrollLeft;
    };
    const onMouseMove = (event: MouseEvent) => {
      if (!dragging) return;
      // 上界浏览器自己会夹住，下界得靠这个 Math.max 自己守。
      node.scrollLeft = Math.max(startLeft + (startX - event.clientX), 0);
    };
    const stop = () => {
      dragging = false;
    };

    node.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', stop);
    return () => {
      node.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', stop);
    };
  }, [ref, enabled]);
}
