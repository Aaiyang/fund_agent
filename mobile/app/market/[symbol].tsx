/**
 * Analysis screen for one listed instrument: reached from the home market tape
 * (an index) and from a fund's 重仓股 table (a stock).
 *
 * Sections a market has no data for are dropped rather than rendered as "--":
 * an index has no 市净率, a Hong Kong listing has no company profile on this
 * source. The layout stays identical across the four markets on purpose.
 */

import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Async } from '@/components/states';
import { Card, NavTab, Screen, SectionTitle, Stat } from '@/components/ui';
import { MarketChart } from '@/components/MarketChart';
import { theme } from '@/constants/theme';
import type { NavRange } from '@/hooks/useFunds';
import {
  type MarketPeriod,
  useMarketCompany,
  useMarketHistory,
  useMarketIntraday,
  useMarketQuote,
} from '@/hooks/useMarket';
import {
  currencySign,
  formatDate,
  formatCompact,
  formatPoints,
  formatPrice,
  formatReturnPoints,
  formatSignedRate,
  formatYi,
  trendColor,
} from '@/utils/format';

type Mode = 'intraday' | 'fiveday' | 'day' | 'week' | 'month';

const MODES: { key: Mode; label: string }[] = [
  { key: 'intraday', label: '分时' },
  { key: 'fiveday', label: '五日' },
  { key: 'day', label: '日K' },
  { key: 'week', label: '周K' },
  { key: 'month', label: '月K' },
];

// The chart pans sideways through this window instead of offering range buttons.
// Monthly bars need a longer window to be worth looking at.
const HISTORY: Record<'day' | 'week' | 'month', { range: NavRange; label: string }> = {
  day: { range: '1y', label: '近1年' },
  week: { range: '1y', label: '近1年' },
  month: { range: '3y', label: '近3年' },
};

export default function MarketScreen() {
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const [mode, setMode] = useState<Mode>('day');
  const target = symbol ?? null;
  const quote = useMarketQuote(target);
  const isMinute = mode === 'intraday' || mode === 'fiveday';
  const period: MarketPeriod = isMinute ? 'day' : mode;
  const history = useMarketHistory(target, period, HISTORY[period].range);
  const intraday = useMarketIntraday(target, isMinute, mode === 'fiveday' ? 5 : 1);
  const company = useMarketCompany(target);
  const data = quote.data;
  const sign = currencySign(data?.currency);
  const profile = company.data?.company;
  // The feed serves minute lines for A股 and 港股 only, for one session or five;
  // a US market would offer two tabs that can only fail, so neither is shown.
  // The symbol shape is checked too so the tabs never appear for one frame
  // before the quote lands.
  const modes = data?.currency === 'USD' || /^us[A-Za-z]/.test(symbol ?? '') ? MODES.slice(2) : MODES;

  const refresh = () => {
    void Promise.all([quote.refetch(), history.refetch(), intraday.refetch()]);
  };

  const metrics = data
    ? [
        {
          label: '成交量',
          value: data.volume == null ? null : `${formatCompact(data.volume)}${data.volume_unit ?? ''}`,
        },
        { label: '成交额', value: data.amount == null ? null : `${sign}${formatCompact(data.amount)}` },
        { label: '换手率', value: data.turnover_rate == null ? null : formatPoints(data.turnover_rate) },
        { label: '振幅', value: data.amplitude == null ? null : formatPoints(data.amplitude) },
        { label: '市盈率', value: data.pe == null ? null : formatPrice(data.pe) },
        { label: '市净率', value: data.pb == null ? null : formatPrice(data.pb) },
        { label: '流通市值', value: data.float_market_cap == null ? null : formatYi(data.float_market_cap) },
        { label: '总市值', value: data.total_market_cap == null ? null : formatYi(data.total_market_cap) },
        { label: '52周高', value: data.week52_high == null ? null : formatPrice(data.week52_high) },
        { label: '52周低', value: data.week52_low == null ? null : formatPrice(data.week52_low) },
      ].filter((metric): metric is { label: string; value: string } => metric.value !== null)
    : [];

  return (
    <Screen refreshing={quote.isRefetching || history.isRefetching} onRefresh={refresh}>
      <Stack.Screen options={{ title: data?.name ?? '行情分析' }} />

      <Card>
        <Text style={{ fontSize: 18, fontWeight: '700', color: theme.text }}>{data?.name ?? symbol}</Text>
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
          {data?.listing_code ?? symbol} · {data?.kind === 'index' ? '指数' : '个股'}
          {data?.currency ? ` · ${data.currency}` : ''}
        </Text>
        <View style={{ flexDirection: 'row', alignItems: 'baseline', marginTop: 10 }}>
          <Text style={{ fontSize: 32, fontWeight: '700', color: trendColor(data?.change_pct) }}>
            {formatPrice(data?.price)}
          </Text>
          <Text style={{ fontSize: 15, marginLeft: 8, color: trendColor(data?.change_pct) }}>
            {signed(data?.change)}
          </Text>
          <Text style={{ fontSize: 15, marginLeft: 6, color: trendColor(data?.change_pct) }}>
            {formatReturnPoints(data?.change_pct)}
          </Text>
        </View>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 10 }}>
          <Stat label="今开" value={formatPrice(data?.open)} tone="muted" />
          <Stat label="最高" value={formatPrice(data?.high)} tone="muted" />
          <Stat label="最低" value={formatPrice(data?.low)} tone="muted" />
          <Stat label="昨收" value={formatPrice(data?.prev_close)} tone="muted" />
        </View>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>
          行情时间 {data?.quote_time ?? '--'} · 停留页面期间每 30 秒刷新
        </Text>
      </Card>

      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <View style={{ flexDirection: 'row' }}>
            {modes.map((entry) => (
              <NavTab key={entry.key} label={entry.label} active={mode === entry.key} onPress={() => setMode(entry.key)} />
            ))}
          </View>
          {isMinute ? null : (
            <Text style={{ fontSize: 12, color: theme.textMuted }}>
              {HISTORY[period].label} {formatSignedRate(history.data?.period_return)}
            </Text>
          )}
        </View>

        {isMinute ? (
          <Async query={intraday}>
            {(series) => (
              <MarketChart minutes={series.points ?? []} prevClose={series.prev_close} volumeUnit={data?.volume_unit} />
            )}
          </Async>
        ) : (
          <Async query={history}>
            {(series) => <MarketChart bars={series.bars ?? []} volumeUnit={data?.volume_unit} />}
          </Async>
        )}

        {isMinute ? (
          <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 6 }}>
            {mode === 'fiveday'
              ? `最近 5 个交易日、每天 ${Math.round((intraday.data?.total ?? 0) / 5)} 个分钟点，虚线是 ${formatPrice(intraday.data?.prev_close)}（窗口前一日收盘）`
              : `分时为最近一个交易日的分钟线，虚线是昨收 ${formatPrice(intraday.data?.prev_close)}`}
          </Text>
        ) : (
          <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 6 }}>
            {`${HISTORY[period].label} ${history.data?.total ?? 0} 根，点选看单根行情，超出一屏可左右拖动`}
          </Text>
        )}
      </Card>

      {metrics.length ? (
        <Card>
          <SectionTitle title="关键指标" />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
            {metrics.map((metric) => (
              <Stat key={metric.label} label={metric.label} value={metric.value} tone="muted" />
            ))}
          </View>
        </Card>
      ) : null}

      {profile ? (
        <Card>
          <SectionTitle title="公司简介" />
          <Text style={{ fontSize: 13, color: theme.text, marginBottom: 8 }}>{profile.name}</Text>
          <InfoRow label="所属行业" value={profile.industry} />
          <InfoRow label="所在地区" value={profile.region} />
          <InfoRow label="上市日期" value={profile.list_date ? formatDate(profile.list_date) : null} />
          <InfoRow label="员工人数" value={profile.employees == null ? null : `${formatCompact(profile.employees)}人`} />
          <InfoRow label="主营业务" value={profile.main_business} />
          {profile.description ? (
            <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 8, lineHeight: 18 }}>{profile.description}</Text>
          ) : null}
          {profile.concepts?.length ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 10 }}>
              {profile.concepts.slice(0, 12).map((concept) => (
                <View
                  key={concept}
                  style={{ backgroundColor: theme.background, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 3, marginRight: 6, marginBottom: 6 }}
                >
                  <Text style={{ fontSize: 11, color: theme.textMuted }}>{concept}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </Card>
      ) : null}
    </Screen>
  );
}

function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <View style={{ flexDirection: 'row', marginBottom: 6 }}>
      <Text style={{ width: 64, fontSize: 12, color: theme.textFaint }}>{label}</Text>
      <Text style={{ flex: 1, fontSize: 12, color: theme.text }}>{value}</Text>
    </View>
  );
}
