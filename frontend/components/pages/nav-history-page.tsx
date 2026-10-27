'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  type FundNavPoint,
  getFundNavPage,
} from '@/lib/fund-api';
import {
  formatDate,
  formatNumber,
  formatReturn,
  trendClass,
} from '@/lib/fund-format';

export function NavHistoryPage({
  token,
  code,
  onBack,
}: {
  token: string;
  code: string;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<FundNavPoint[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    void getFundNavPage(token, code, null)
      .then((page) => {
        if (cancelled) return;
        setRows([...page.points].reverse());
        setTotal(page.total ?? page.points.length);
        setHasMore(Boolean(page.has_more));
        setLoading(false);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : '读取净值失败');
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, code]);

  async function loadMore() {
    if (!rows.length || loadingMore) return;
    setLoadingMore(true);
    setError('');
    try {
      const page = await getFundNavPage(
        token,
        code,
        rows[rows.length - 1].nav_date,
      );
      setRows((current) => [...current, ...[...page.points].reverse()]);
      setHasMore(Boolean(page.has_more));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '加载更多失败');
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          NAV HISTORY
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          净值明细{total ? `（${total}）` : ''}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          基金 {code} · 每次加载 30 条
        </p>
      </div>

      <section className="mt-5 overflow-hidden rounded-[24px] border border-border bg-card/75">
        <div className="flex border-b border-border bg-secondary/35 px-5 py-3 text-[10px] text-text-faint">
          <span className="flex-1">日期</span>
          <span className="w-24 text-right">单位净值</span>
          <span className="w-20 text-right">日涨幅</span>
        </div>
        {loading ? (
          <p className="flex items-center gap-2 px-5 py-8 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读净值…
          </p>
        ) : rows.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            还没有净值记录。
          </p>
        ) : (
          rows.map((row) => (
            <div
              key={row.nav_date}
              className="flex border-b border-border/60 px-5 py-2.5 text-[12px] last:border-0"
            >
              <span className="flex-1 text-foreground">{formatDate(row.nav_date)}</span>
              <span className="w-24 text-right tabular-nums text-foreground">
                {formatNumber(row.unit_nav, 4)}
              </span>
              <span className={`w-20 text-right tabular-nums ${trendClass(row.daily_return)}`}>
                {formatReturn(row.daily_return, { points: true })}
              </span>
            </div>
          ))
        )}
      </section>

      {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
      {hasMore && (
        <Button
          variant="outline"
          className="mt-3 h-9 rounded-xl"
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? <RefreshCw className="animate-spin" /> : null} 加载更早的净值
        </Button>
      )}
    </div>
  );
}
