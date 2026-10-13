/**
 * squarified treemap 布局（纯几何，不依赖渲染）.
 *
 * 规则：面积按数值等比分配，数值降序一条条切边——每往当前条里多放一块，
 * 都要求"这一条里最差的长宽比"不再变差，否则就先把这条落定、换一条。
 * 这样方块接近正方形，板块名才塞得下（slice-and-dice 会把窄条切成细长条）。
 */

export type TreemapCell<T> = { item: T; x: number; y: number; w: number; h: number };

export type TreemapEntry<T> = { item: T; value: number };

/** 一组方块里最差的长宽比（越接近 1 越方）. */
function worst(areas: number[], side: number): number {
  if (!areas.length || side <= 0) return Number.POSITIVE_INFINITY;
  const sum = areas.reduce((total, area) => total + area, 0);
  const scale = side * side;
  const squared = sum * sum;
  return Math.max((scale * Math.max(...areas)) / squared, squared / (scale * Math.min(...areas)));
}

export function squarify<T>(entries: TreemapEntry<T>[], width: number, height: number): TreemapCell<T>[] {
  const cells: TreemapCell<T>[] = [];
  const total = entries.reduce((sum, entry) => sum + entry.value, 0);
  if (total <= 0 || width <= 0 || height <= 0) return cells;

  const scale = (width * height) / total;
  const areas = entries.map((entry) => ({ item: entry.item, area: Math.max(entry.value * scale, 0.01) }));

  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let row: typeof areas = [];

  const flush = () => {
    if (!row.length) return;
    const rowArea = row.reduce((sum, cell) => sum + cell.area, 0);
    if (w >= h) {
      // 竖着切一条贴在剩余区的左边。
      const columnWidth = rowArea / h;
      let cursor = y;
      for (const cell of row) {
        const cellHeight = cell.area / columnWidth;
        cells.push({ item: cell.item, x, y: cursor, w: columnWidth, h: cellHeight });
        cursor += cellHeight;
      }
      x += columnWidth;
      w -= columnWidth;
    } else {
      // 横着切一条贴在剩余区的上边。
      const rowHeight = rowArea / w;
      let cursor = x;
      for (const cell of row) {
        const cellWidth = cell.area / rowHeight;
        cells.push({ item: cell.item, x: cursor, y, w: cellWidth, h: rowHeight });
        cursor += cellWidth;
      }
      y += rowHeight;
      h -= rowHeight;
    }
    row = [];
  };

  for (const entry of areas) {
    const side = Math.min(w, h);
    if (side <= 0) break;
    const current = row.map((cell) => cell.area);
    if (!current.length || worst([...current, entry.area], side) <= worst(current, side)) {
      row.push(entry);
    } else {
      flush();
      row.push(entry);
    }
  }
  flush();
  return cells;
}
