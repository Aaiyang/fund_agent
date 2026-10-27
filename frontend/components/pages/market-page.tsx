'use client';

import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  type IndexQuote,
  type SectorItem,
  getIndexQuotes,
  getSectorBoard,
} from '@/lib/fund-api';
import { formatReturn, trendClass } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

export function MarketPage({
  token,
  onOpenSymbol,
}: {
  token: string;
  onOpenSymbol: (symbol: string) => void;
}) {
  const [kind, setKind] = useState<'industry' | 'concept'>('industry');
  const quotes = useResource<IndexQuote[]>(() => getIndexQuotes(token), token);
  const sectors = useResource<SectorItem[]>(
    () => getSectorBoard(token, kind),
    `${token}:${kind}`,
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
            MARKET
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            行情
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            看一眼大盘和板块温度，再回到具体基金。
          </p>
        </div>
        <Button
          variant="outline"
          className="rounded-xl"
          onClick={() => {
            quotes.reload();
            sectors.reload();
          }}
        >
          <RefreshCw
            className={quotes.loading || sectors.loading ? 'animate-spin' : ''}
          />
          刷新
        </Button>
      </div>

      <section className="mt-6 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">大盘指数</p>
          <span className="text-[10px] text-text-faint">
            收盘口径 · 数据日期以接口为准
          </span>
        </div>
        {quotes.loading ? (
          <p className="mt-5 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读指数…
          </p>
        ) : quotes.error ? (
          <p className="mt-4 text-sm text-destructive">{quotes.error}</p>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {quotes.data?.map((quote) => (
              <button
                key={quote.index_code}
                type="button"
                onClick={() => onOpenSymbol(quote.index_code)}
                className="rounded-2xl border border-border bg-card/70 p-4 text-left transition-colors hover:border-primary/25"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-medium text-foreground">
                    {quote.name}
                  </p>
                  <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-text-faint">
                    {quote.trade_date}
                  </span>
                </div>
                <p className="mt-3 text-2xl font-semibold tabular-nums text-foreground">
                  {quote.close.toLocaleString('zh-CN', {
                    maximumFractionDigits: 2,
                  })}
                </p>
                <p
                  className={`mt-1 flex items-center gap-1 text-xs tabular-nums ${trendClass(quote.change_pct)}`}
                >
                  {quote.change_pct >= 0 ? (
                    <ArrowUpRight className="size-3.5" />
                  ) : (
                    <ArrowDownRight className="size-3.5" />
                  )}
                  {formatReturn(quote.change_pct, { points: true })}
                </p>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-foreground">板块涨跌</p>
            <p className="mt-1 text-[11px] text-text-faint">
              按当日涨跌幅排序，只看前 10 个板块。
            </p>
          </div>
          <div className="flex gap-1 rounded-full border border-border bg-secondary/40 p-1">
            {(
              [
                ['industry', '行业'],
                ['concept', '概念'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setKind(value)}
                className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                  kind === value
                    ? 'bg-card font-medium text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {sectors.loading ? (
          <p className="mt-5 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读板块…
          </p>
        ) : sectors.error ? (
          <p className="mt-4 text-sm text-destructive">{sectors.error}</p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {sectors.data?.map((sector, index) => (
              <div
                key={sector.code}
                className="flex items-center gap-3 rounded-xl border border-border/70 bg-background/40 px-3 py-2.5"
              >
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-secondary text-[10px] text-text-faint">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-foreground">{sector.name}</p>
                  <p className="truncate text-[10px] text-text-faint">
                    {sector.leading_stock
                      ? `领涨 ${sector.leading_stock.name ?? sector.leading_stock.code}`
                      : '暂无领涨股'}
                  </p>
                </div>
                <span
                  className={`text-sm font-medium tabular-nums ${trendClass(sector.change_pct)}`}
                >
                  {formatReturn(sector.change_pct, { points: true })}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
