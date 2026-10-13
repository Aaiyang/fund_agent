import type { FundChart } from '../../shared/fund-chart';
import { FundPerformanceCard } from '@/components/FundPerformanceCard';

/** Legacy blocks also use only the fund code; model-supplied NAV/cost/labels are never drawn. */
export function FundAnalysisChart({ chart }: { chart: FundChart }) {
  return <FundPerformanceCard key={chart.fund_code} fundCode={chart.fund_code} />;
}
