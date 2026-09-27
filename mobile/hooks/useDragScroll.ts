/**
 * Mouse-drag panning for a horizontal ScrollView on the web.
 *
 * Browsers pan a scroll box with the wheel and with touch, but a press-and-drag
 * with a mouse does nothing, so a desktop panel cannot reach the items past its
 * right edge. The listeners go on the real DOM scroller because React Native's
 * responder props are not reliably forwarded by ScrollView on web.
 *
 * Native keeps its own pan gesture, so this is a no-op there.
 */

import { type RefObject, useEffect } from 'react';
import { Platform, type ScrollView } from 'react-native';

export function useDragScroll(ref: RefObject<ScrollView | null>) {
  useEffect(() => {
    if (Platform.OS !== 'web') return;
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
      // The browser clamps the upper bound; the lower one needs the Math.max.
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
  }, [ref]);
}
