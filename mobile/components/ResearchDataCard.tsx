import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import type { ResearchCard } from '../../shared/research-card';
import { MarketChart } from '@/components/MarketChart';
import { Async, EmptyState, ErrorState, describeError } from '@/components/states';
import { Card, Chip, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import type { NavRange } from '@/hooks/useFunds';
import { useMarketHistory, useMarketQuote } from '@/hooks/useMarket';
import { useAllocationResearchCard, useSectorResearchCard, type AllocationCard, type SectorCard } from '@/hooks/useResearchCards';
import { formatMoney, formatPrice, formatRate, formatReturnPoints } from '@/utils/format';

const note = { color: theme.textMuted, fontSize: 11, lineHeight: 17, marginTop: 6 } as const;

function tone(value: number | null | undefined): 'up' | 'down' | 'normal' {
  return value == null || value === 0 ? 'normal' : value > 0 ? 'up' : 'down';
}

function StockCard({ card }: { card: Extract<ResearchCard, { type: 'stock_price' }> }) {
  const [range, setRange] = useState<NavRange>('1y');
  const quote = useMarketQuote(card.symbol);
  const history = useMarketHistory(card.symbol, 'day', range);
  return <Card>
    <SectionTitle title="股票价格走势" />
    <Text style={note}>{quote.data?.name ?? card.symbol} · {card.symbol} · {quote.data?.currency ?? '币种待核验'}</Text>
    {quote.data ? <View style={{ flexDirection: 'row' }}>
      <Stat label="最新报价" value={formatPrice(quote.data.price)} />
      <Stat label="涨跌幅" value={formatReturnPoints(quote.data.change_pct)} tone={tone(quote.data.change_pct)} />
    </View> : null}
    {quote.isError ? <ErrorState message={describeError(quote.error)} onRetry={() => void quote.refetch()} /> : null}
    <Async query={history}>{(data) => data.bars.length > 1
      ? <MarketChart key={`${card.symbol}:${range}`} bars={data.bars} volumeUnit={quote.data?.volume_unit} />
      : <EmptyState title="暂无足够价格历史" hint="稍后重试或调整时间范围" />}</Async>
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      {([['1m', '1月'], ['3m', '3月'], ['6m', '6月'], ['1y', '1年']] as const).map(([key, label]) =>
        <Chip key={key} label={label} active={range === key} onPress={() => setRange(key)} />)}
    </ScrollView>
    <Text style={note}>报价时间：{quote.data?.quote_time || '未核验'}。前复权日K，未计股息再投资；图表随查询更新，可能与回答时不同。公开报价可能延迟。</Text>
  </Card>;
}

function SectorCardView({ card }: { card: SectorCard }) {
  const query = useSectorResearchCard(card);
  return <Card><SectionTitle title="板块行情" />
    <Async query={query}>{(data) => {
      const row = data.sectors.find((item) => item.sector_code === card.sector_code && item.sector_type === card.sector_type);
      if (!row) return <EmptyState title="未找到对应板块" />;
      return <>
        <Text style={note}>{row.name} · {row.sector_code} · {row.sector_type === 'industry' ? '行业' : '概念'}</Text>
        <View style={{ flexDirection: 'row' }}><Stat label="最新点位" value={formatPrice(row.price)} />
          <Stat label="涨跌幅" value={formatReturnPoints(row.change_pct)} tone={tone(row.change_pct)} /></View>
        <Text style={note}>报价时间：{row.quote_time ?? '未核验'}{row.stale ? ' · 数据可能延迟' : ''}</Text>
        {row.error_code ? <Text style={note}>本次报价不完整，请稍后重试。</Text> : null}
        {data.warnings.map((warning, index) => <Text key={index} style={note}>{warning}</Text>)}
        <View style={{ backgroundColor: theme.background, padding: 12, borderRadius: theme.radius, marginTop: 8 }}>
          <Text style={note}>历史走势图暂未接入，当前展示最新可用行情快照。</Text>
        </View>
      </>;
    }}</Async>
  </Card>;
}

function AllocationCardView({ card }: { card: AllocationCard }) {
  const query = useAllocationResearchCard(card);
  return <Card><SectionTitle title="操作前后配置" />
    <Text style={note}>{card.fund_code} · {card.account_id === null ? '全部基金账户' : `账户 ${card.account_id}`} · 拟操作 {formatMoney(card.amount)}</Text>
    {query.isPending && query.fetchStatus === 'idle' ? <Text style={note}>请登录后查看个人配置试算。</Text> : <Async query={query}>{(data) => {
      const scenario = data.scenario;
      if (!scenario.available) return <EmptyState title="暂不能计算操作比例" hint={scenario.reason} />;
      return <>
        {([
          ['操作前', scenario.before_weight_ratio, scenario.before_target_value],
          ['操作后', scenario.after_weight_ratio, scenario.after_target_value],
        ] as const).map(([label, ratio, value]) => <View key={label} style={{ marginTop: 12 }}>
          <Text style={{ color: theme.text, fontSize: 13 }}>{label}：{formatMoney(value)} · {formatRate(ratio)}</Text>
          <View style={{ height: 8, backgroundColor: theme.background, borderRadius: 4, marginTop: 6 }}>
            {ratio !== null && ratio !== undefined && Number.isFinite(ratio) ? <View style={{ height: 8, borderRadius: 4, backgroundColor: theme.primary, width: `${Math.min(100, Math.max(0, ratio * 100))}%` }} /> : null}
          </View>
        </View>)}
        <Text style={note}>{scenario.assumption}</Text>
        <Text style={note}>基金资产：{formatMoney(scenario.before_fund_assets)} → {formatMoney(scenario.after_fund_assets)}。比例分母随资金进出变化，仅试算，不执行交易。</Text>
        <Text style={note}>当前账本读取时间（UTC）：{data.captured_at}；可能晚于回答时数据。</Text>
        {data.warnings.map((warning, index) => <Text key={index} style={note}>{warning}</Text>)}
      </>;
    }}</Async>}
  </Card>;
}

/** New adapters only; original fund detail and market chart components are unchanged. */
export function ResearchDataCard({ card }: { card: ResearchCard }) {
  if (card.type === 'stock_price') return <StockCard card={card} />;
  if (card.type === 'sector_quote') return <SectorCardView card={card} />;
  return <AllocationCardView card={card} />;
}
