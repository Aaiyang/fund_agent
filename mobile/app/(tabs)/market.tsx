/**
 * 行情 tab：大盘指数的迷你行情卡，三个一排、按目录条数往下排。
 *
 * 每张卡三样东西都是**盘中实时**同一口径：点位与涨跌来自腾讯快照（30 秒一轮），
 * 迷你线是当日分时（60 秒一轮），虚线是昨收。不掺 `/indexes/quotes` 那种按昨收
 * 算出来的涨幅——一屏里一半实时一半昨天，读的人没法判断自己看的是什么时候。
 *
 * 目录现在给 5 只，所以是 3 + 2；后端目录补到 6 只就自动排满两排，这里不写死数量。
 * 下面两张板块卡（热力图与涨跌榜）都读 `/sectors/board`，行业/概念这个开关由本页
 * 持有，两张卡共用，免得各选各的。
 */

import { router } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Dimensions, Pressable, Text, View } from 'react-native';

import { EmptyState, ErrorState, LoadingState, describeError } from '@/components/states';
import { MiniTrend } from '@/components/MiniTrend';
import { SectorTreemap } from '@/components/SectorTreemap';
import { Card, Chip, NavTab, Row, Screen, SectionTitle } from '@/components/ui';
import { queryKeys } from '@/api/queries';
import { theme } from '@/constants/theme';
import { useIndexCatalog } from '@/hooks/useIndexes';
import { useMarketIntraday, useMarketQuotes, type MarketQuote } from '@/hooks/useMarket';
import {
  SECTOR_KIND_LABELS,
  SECTOR_ORDER_LABELS,
  SECTOR_SORT_LABELS,
  SECTOR_SORTS,
  useSectorBoard,
  type SectorBoardItem,
  type SectorKind,
  type SectorOrder,
  type SectorSort,
} from '@/hooks/useSectors';
import { formatPrice, formatReturnPoints, trendColor } from '@/utils/format';

const COLUMNS = 3;
const SECTOR_ROWS = 6;
/** 热力图一次画 30 块：再多名字就装不下了，且面积差距会被压平。 */
const TREEMAP_CELLS = 30;
const TREEMAP_HEIGHT = 300;
/** 迷你卡底色：直接取 `trendColor()` 的色相再压透明度（末尾 `0F` ≈ 6%），
 *  免得在这里抄一遍涨跌的十六进制值、和文字颜色对不上。 */
const TREND_TINT_ALPHA = '0F';

/** 涨跌方向决定底色，平盘/缺数不上色——与 `trendColor()` 同一套判据。 */
function trendTint(changePct: number | null | undefined): string {
  if (!changePct) return theme.surface;
  return `${trendColor(changePct)}${TREND_TINT_ALPHA}`;
}

export default function MarketScreen() {
  const catalog = useIndexCatalog();
  const client = useQueryClient();
  // 类别是两张板块卡共用的一个开关，放在页面层，免得两处各选各的。
  const [sectorKind, setSectorKind] = useState<SectorKind>('industry');
  const codes = (catalog.data?.items ?? []).map((item) => item.index_code);
  const names = Object.fromEntries((catalog.data?.items ?? []).map((item) => [item.index_code, item.name]));
  const batch = useMarketQuotes(codes);

  function refresh() {
    void Promise.all([
      catalog.refetch(),
      batch.refetch(),
      client.invalidateQueries({ queryKey: queryKeys.markets }),
      // 板块榜的查询在卡片内部，下拉时按前缀整体失效即可。
      client.invalidateQueries({ queryKey: queryKeys.sectors }),
    ]);
  }

  if (catalog.isPending) {
    return (
      <Screen scroll={false}>
        <LoadingState label="正在读指数目录…" />
      </Screen>
    );
  }
  if (catalog.isError) {
    return (
      <Screen scroll={false}>
        <ErrorState message={describeError(catalog.error)} onRetry={refresh} />
      </Screen>
    );
  }

  const quotes = Object.fromEntries((batch.data ?? []).map((row) => [row.symbol, row.quote]));
  const rows: string[][] = [];
  for (let index = 0; index < codes.length; index += COLUMNS) {
    rows.push(codes.slice(index, index + COLUMNS));
  }

  return (
    <Screen refreshing={batch.isFetching} onRefresh={refresh}>
      <Card>
        <SectionTitle title="大盘指数" />
        {codes.length === 0 ? (
          <EmptyState title="还没有指数数据" hint="下拉刷新可重新读取指数目录" />
        ) : (
          rows.map((row) => (
            <View key={row[0]} style={{ flexDirection: 'row', marginBottom: 8 }}>
              {row.map((code) => (
                <View key={code} style={{ flex: 1, marginHorizontal: 4 }}>
                  <IndexTile code={code} name={names[code] ?? code} quote={quotes[code] ?? null} />
                </View>
              ))}
              {/* 最后一排不满时补空位，保证已有的卡还是三分之一宽、不会被拉宽。 */}
              {Array.from({ length: COLUMNS - row.length }).map((_, index) => (
                <View key={`gap-${index}`} style={{ flex: 1, marginHorizontal: 4 }} />
              ))}
            </View>
          ))
        )}
        <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 4 }}>
          点位与涨跌为盘中实时，曲线是当日分时、虚线为昨收；点一张卡看详细分析。
        </Text>
      </Card>

      <SectorHeatmapCard kind={sectorKind} onKind={setSectorKind} />
      <SectorBoardCard kind={sectorKind} />
    </Screen>
  );
}

/** 板块热力图：面积随选定指标、颜色随涨跌幅；缺该指标的板块不进图。 */
function SectorHeatmapCard({ kind, onKind }: { kind: SectorKind; onKind: (kind: SectorKind) => void }) {
  const [sort, setSort] = useState<SectorSort>('amount');
  const board = useSectorBoard(kind, 'desc', sort, TREEMAP_CELLS);
  // Screen 与 Card 各有一层 theme.gap 内边距，两边都要扣。
  const width = Math.max(Dimensions.get('window').width - theme.gap * 4, 240);

  return (
    <Card>
      <SectionTitle title="板块热力图" />
      <Row>
        {SECTOR_SORTS.map((value) => (
          <Chip key={value} label={SECTOR_SORT_LABELS[value]} active={value === sort} onPress={() => setSort(value)} />
        ))}
      </Row>
      <Row>
        {(['industry', 'concept'] as SectorKind[]).map((value) => (
          <Chip key={value} label={SECTOR_KIND_LABELS[value]} active={value === kind} onPress={() => onKind(value)} />
        ))}
      </Row>

      {board.isPending ? (
        <LoadingState label="正在读板块数据…" />
      ) : board.isError || !board.data ? (
        <Text style={{ fontSize: 13, color: theme.danger, paddingVertical: 12 }}>{describeError(board.error)}</Text>
      ) : board.data.items.length === 0 ? (
        <EmptyState title="还没有板块数据" hint="换个面积口径或类别，或下拉刷新" />
      ) : (
        <>
          <SectorTreemap sectors={board.data.items} sort={sort} width={width} height={TREEMAP_HEIGHT} />
          <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 8 }}>
            面积是{SECTOR_SORT_LABELS[sort]}、颜色深浅是涨跌幅（涨红跌绿），画前 {board.data.items.length} 个；
            全市场 {board.data.total_available} 个板块该指标有数。上游不给报价时间，涨跌不等于基金涨跌。
          </Text>
        </>
      )}
    </Card>
  );
}

/** 板块涨跌榜：类别跟着上面热力图的开关走，这里只切涨幅榜/跌幅榜。 */
function SectorBoardCard({ kind }: { kind: SectorKind }) {
  const [order, setOrder] = useState<SectorOrder>('desc');
  const board = useSectorBoard(kind, order, 'change_pct', SECTOR_ROWS);

  return (
    <Card>
      <SectionTitle title={`板块涨跌榜 · ${SECTOR_KIND_LABELS[kind]}`} />
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        {(['desc', 'asc'] as SectorOrder[]).map((value) => (
          <NavTab key={value} label={SECTOR_ORDER_LABELS[value]} active={value === order} onPress={() => setOrder(value)} />
        ))}
      </View>

      {board.isPending ? (
        <LoadingState label="正在读板块榜…" />
      ) : board.isError || !board.data ? (
        <Text style={{ fontSize: 13, color: theme.danger, paddingVertical: 12 }}>{describeError(board.error)}</Text>
      ) : board.data.items.length === 0 ? (
        <EmptyState title="还没有板块数据" hint="切到另一个类别，或下拉刷新再试" />
      ) : (
        board.data.items.map((item) => <SectorRow key={item.code} item={item} />)
      )}

      {board.data ? (
        <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 8 }}>
          全市场 {board.data.total_available} 个板块可排名，这里列前 {board.data.items.length} 个。
        </Text>
      ) : null}
    </Card>
  );
}

function SectorRow({ item }: { item: SectorBoardItem }) {
  const color = trendColor(item.change_pct);
  const lead = item.leading_stock;
  const leadText = lead ? `领涨 ${lead.name ?? lead.code}${lead.change_pct != null ? ` ${formatReturnPoints(lead.change_pct)}` : ''}` : '';

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 9,
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <Text style={{ fontSize: 14, color: theme.text, maxWidth: 92 }} numberOfLines={1}>
        {item.name}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, flex: 1, textAlign: 'right', marginRight: 10 }} numberOfLines={1}>
        {leadText}
      </Text>
      <Text style={{ fontSize: 14, fontWeight: '600', color, minWidth: 62, textAlign: 'right' }}>
        {formatReturnPoints(item.change_pct)}
      </Text>
    </View>
  );
}

function IndexTile({ code, name, quote }: { code: string; name: string; quote: MarketQuote | null }) {
  const intraday = useMarketIntraday(code, true, 1);
  const color = trendColor(quote?.change_pct);
  const change = quote?.change ?? null;
  const changeText = change == null ? '--' : `${change > 0 ? '+' : ''}${formatPrice(change)}`;
  const tint = trendTint(quote?.change_pct);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`查看${name}详细行情`}
      onPress={() => router.push(`/market/${code}`)}
      style={({ pressed }) => [
        {
          flex: 1,
          borderRadius: 10,
          paddingHorizontal: 6,
          paddingTop: 10,
          paddingBottom: 6,
          backgroundColor: tint,
          opacity: pressed ? 0.85 : 1,
        },
      ]}
    >
      <Text style={{ fontSize: 13, color: theme.text, textAlign: 'center' }} numberOfLines={1}>
        {name}
      </Text>
      <Text style={{ fontSize: 20, fontWeight: '700', color, textAlign: 'center', marginTop: 6 }} numberOfLines={1}>
        {formatPrice(quote?.price)}
      </Text>
      <Text style={{ fontSize: 12, color, textAlign: 'center', marginTop: 2 }} numberOfLines={1}>
        {changeText} [{formatReturnPoints(quote?.change_pct)}]
      </Text>
      <MiniTrend
        prices={(intraday.data?.points ?? []).map((point) => point.price)}
        prevClose={intraday.data?.prev_close}
        gradientKey={code}
        style={{ marginTop: 6 }}
      />
    </Pressable>
  );
}
