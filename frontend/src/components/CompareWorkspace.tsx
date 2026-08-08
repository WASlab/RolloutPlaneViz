import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Dashboard, Estimate } from '../types'
import { EChart } from './EChart'

const label = (value: number | null) => value === null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`

export function CompareWorkspace({ data }: { data: Dashboard }) {
  const [baseline, setBaseline] = useState(data.bundles[0])
  const [candidate, setCandidate] = useState(data.bundles.at(-1) ?? data.bundles[0])
  const comparison = useQuery({
    queryKey: ['compare', data.run.run_id, baseline, candidate],
    queryFn: () => api.compare(data.run.run_id, baseline, candidate),
    enabled: baseline !== candidate,
  })
  const estimates = comparison.data?.estimates ?? []
  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 450,
    grid: { left: 190, right: 70, top: 18, bottom: 30 },
    tooltip: { trigger: 'axis', valueFormatter: value => `${Number(value).toFixed(2)}%` },
    xAxis: { type: 'value', axisLabel: { formatter: (value: number) => `${value}%` }, splitLine: { lineStyle: { color: '#dfe4df', type: 'dashed' } } },
    yAxis: { type: 'category', inverse: true, data: estimates.map(item => item.metric), axisLine: { show: false }, axisTick: { show: false } },
    series: [{
      type: 'bar',
      barWidth: 16,
      data: estimates.map(item => ({ value: (item.relative_delta ?? 0) * 100, itemStyle: { color: (item.relative_delta ?? 0) >= 0 ? '#00a9a5' : '#ef765e' } })),
      label: { show: true, position: 'right', formatter: (item) => `${Number(item.value).toFixed(1)}%`, color: '#171b19' },
    }],
  }), [estimates])

  return <section className="mode-workspace compare-workspace">
    <div className="mode-heading"><div><p className="eyebrow">BUNDLE COMPARISON</p><h2>Candidate effect against baseline</h2><p>Independent 95% confidence intervals are calculated from recorded metric samples.</p></div><div className="compare-controls"><label>Baseline<select value={baseline} onChange={event => setBaseline(event.target.value)}>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label><span>→</span><label>Candidate<select value={candidate} onChange={event => setCandidate(event.target.value)}>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label></div></div>
    {baseline === candidate ? <div className="empty-state">Choose two different bundles.</div> : comparison.isLoading ? <div className="empty-state">Calculating comparison…</div> : <>
      <article className="panel comparison-chart"><div className="panel-title"><div><p>Relative movement</p><h2>Change in metric means</h2></div><span>candidate − baseline</span></div><EChart option={option} /></article>
      <article className="estimate-table"><div className="panel-title"><div><p>Statistical evidence</p><h2>Estimates and uncertainty</h2></div></div><table><thead><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Δ absolute</th><th>Δ relative</th><th>95% CI for Δ</th><th>n</th></tr></thead><tbody>{estimates.map(item => <EstimateRow key={item.metric} item={item} />)}</tbody></table></article>
    </>}
  </section>
}

function EstimateRow({ item }: { item: Estimate }) {
  const significant = item.confidence_low > 0 || item.confidence_high < 0
  return <tr><td><code>{item.metric}</code><small>{item.unit}</small></td><td>{item.baseline_mean.toFixed(4)}</td><td>{item.candidate_mean.toFixed(4)}</td><td className={item.absolute_delta >= 0 ? 'good' : 'bad'}>{item.absolute_delta >= 0 ? '+' : ''}{item.absolute_delta.toFixed(4)}</td><td>{label(item.relative_delta)}</td><td className={significant ? 'significant' : ''}>[{item.confidence_low.toFixed(4)}, {item.confidence_high.toFixed(4)}]</td><td>{item.sample_count_baseline} / {item.sample_count_candidate}</td></tr>
}
