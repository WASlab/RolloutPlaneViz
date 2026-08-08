import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { BundleSummary, ComparisonMethod, Dashboard, Estimate } from '../types'
import { EChart } from './EChart'

const relativeLabel = (value: number | null) => value === null
  ? '—'
  : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`

const probabilityLabel = (value: number | null) => value === null
  ? '—'
  : `${(value * 100).toFixed(1)}%`

export function CompareWorkspace({ data }: { data: Dashboard }) {
  const bundleSignature = data.bundles.join('\u0000')
  const [baseline, setBaseline] = useState(data.bundles[0] ?? '')
  const [candidate, setCandidate] = useState(data.bundles.at(-1) ?? '')
  const [method, setMethod] = useState<ComparisonMethod>('moving_block_bootstrap')
  const [confidence, setConfidence] = useState(0.95)
  const [resamples, setResamples] = useState(2_000)
  const [blockLength, setBlockLength] = useState<number | null>(null)

  useEffect(() => {
    setBaseline(data.bundles[0] ?? '')
    setCandidate(data.bundles.at(-1) ?? '')
  }, [data.run.run_id, bundleSignature])

  const request = useMemo(() => ({
    run_id: data.run.run_id,
    baseline_bundle: baseline,
    candidate_bundle: candidate,
    method,
    confidence_level: confidence,
    resamples,
    block_length: blockLength,
    metric_names: [],
  }), [baseline, blockLength, candidate, confidence, data.run.run_id, method, resamples])

  const comparison = useQuery({
    queryKey: ['compare', request],
    queryFn: () => api.compare(request),
    enabled: Boolean(baseline && candidate && baseline !== candidate),
  })
  const estimates = comparison.data?.estimates ?? []
  const option = useMemo<EChartsOption>(() => ({
    animationDuration: 450,
    aria: { enabled: true },
    grid: { left: 190, right: 70, top: 18, bottom: 30 },
    tooltip: { trigger: 'axis', valueFormatter: value => `${Number(value).toFixed(2)}%` },
    xAxis: {
      type: 'value',
      axisLabel: { formatter: (value: number) => `${value}%` },
      splitLine: { lineStyle: { color: '#dfe4df', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: estimates.map(item => item.metric),
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barWidth: 16,
      data: estimates.map(item => ({
        value: (item.relative_delta ?? 0) * 100,
        itemStyle: { color: (item.relative_delta ?? 0) >= 0 ? '#00a9a5' : '#ef765e' },
      })),
      label: {
        show: true,
        position: 'right',
        formatter: item => `${Number(item.value).toFixed(1)}%`,
        color: '#171b19',
      },
    }],
  }), [estimates])

  return <section className="mode-workspace compare-workspace">
    <div className="mode-heading">
      <div>
        <p className="eyebrow">BUNDLE COMPARISON</p>
        <h2>Candidate effect against baseline</h2>
        <p>Autocorrelation-aware intervals are calculated from the recorded metric order.</p>
      </div>
      <div className="compare-controls">
        <label>Baseline<select value={baseline} onChange={event => setBaseline(event.target.value)}>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label>
        <span>→</span>
        <label>Candidate<select value={candidate} onChange={event => setCandidate(event.target.value)}>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label>
      </div>
    </div>

    <div className="method-strip">
      <label>Estimator<select value={method} onChange={event => setMethod(event.target.value as ComparisonMethod)}><option value="moving_block_bootstrap">Moving-block bootstrap</option><option value="normal_independent">Independent normal</option></select></label>
      <label>Confidence<select value={confidence} onChange={event => setConfidence(Number(event.target.value))}><option value={0.9}>90%</option><option value={0.95}>95%</option><option value={0.99}>99%</option></select></label>
      <label>Resamples<input type="number" min={100} max={50_000} step={100} value={resamples} disabled={method !== 'moving_block_bootstrap'} onChange={event => setResamples(Math.max(100, Math.min(50_000, Number(event.target.value))))} /></label>
      <label>Block length<input type="number" min={1} placeholder="auto" value={blockLength ?? ''} disabled={method !== 'moving_block_bootstrap'} onChange={event => setBlockLength(event.target.value ? Number(event.target.value) : null)} /></label>
      {comparison.data && <code className="evidence-digest" title={comparison.data.data_digest}>{comparison.data.data_digest.slice(0, 24)}…</code>}
    </div>

    {baseline === candidate
      ? <div className="empty-state">Choose two different bundles.</div>
      : comparison.isLoading
        ? <div className="empty-state">Calculating comparison…</div>
        : comparison.isError
          ? <div className="empty-state error-copy">{comparison.error.message}</div>
          : <>
            <article className="panel comparison-chart">
              <div className="panel-title"><div><p>Relative movement</p><h2>Change in metric means</h2></div><span>candidate − baseline</span></div>
              {estimates.length ? <EChart option={option} /> : <div className="empty-state">No metric has samples in both bundles.</div>}
            </article>
            <article className="estimate-table">
              <div className="panel-title"><div><p>Statistical evidence</p><h2>Estimates and uncertainty</h2></div><span>{method === 'moving_block_bootstrap' ? `${resamples.toLocaleString()} resamples` : 'normal approximation'}</span></div>
              <table><thead><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Δ absolute</th><th>Δ relative</th><th>{Math.round(confidence * 100)}% CI for Δ</th><th>P(candidate &gt; baseline)</th><th>Effect</th><th>n</th></tr></thead><tbody>{estimates.map(item => <EstimateRow key={`${item.metric}:${item.unit}`} item={item} />)}</tbody></table>
            </article>
            <BundleComparison bundles={comparison.data?.bundle_details ?? []} />
          </>}
  </section>
}

function EstimateRow({ item }: { item: Estimate }) {
  const excludesZero = item.confidence_low > 0 || item.confidence_high < 0
  return <tr>
    <td><code>{item.metric}</code><small>{item.unit}{item.block_length ? ` · block ${item.block_length}` : ''}</small></td>
    <td>{item.baseline_mean.toFixed(4)}</td>
    <td>{item.candidate_mean.toFixed(4)}</td>
    <td className={item.absolute_delta >= 0 ? 'good' : 'bad'}>{item.absolute_delta >= 0 ? '+' : ''}{item.absolute_delta.toFixed(4)}</td>
    <td>{relativeLabel(item.relative_delta)}</td>
    <td className={excludesZero ? 'significant' : ''}>[{item.confidence_low.toFixed(4)}, {item.confidence_high.toFixed(4)}]</td>
    <td>{probabilityLabel(item.probability_candidate_greater)}</td>
    <td>{item.standardized_effect?.toFixed(2) ?? '—'}</td>
    <td>{item.sample_count_baseline} / {item.sample_count_candidate}</td>
  </tr>
}

function BundleComparison({ bundles }: { bundles: BundleSummary[] }) {
  if (!bundles.length) return null
  return <section className="provenance-compare">
    <div className="panel-title"><div><p>Runtime provenance</p><h2>What changed between bundles</h2></div><span>content-addressed identities</span></div>
    <div className="provenance-columns">{bundles.map(bundle => <article key={bundle.bundle_id}>
      <code className="bundle-id">{bundle.bundle_id}</code>
      <dl>
        <div><dt>Policy step</dt><dd>{bundle.policy_step ?? 'legacy'}</dd></div>
        <div><dt>Target</dt><dd>{bundle.target}</dd></div>
        <div><dt>Speculator</dt><dd>{bundle.speculator ?? 'none'}</dd></div>
        <div><dt>Engine</dt><dd>{bundle.engine}</dd></div>
        <div><dt>Environment</dt><dd>{bundle.environment_contract ?? 'unscoped'}</dd></div>
        <div><dt>Reward</dt><dd>{bundle.reward_contract ?? 'unscoped'}</dd></div>
      </dl>
      <code className="digest-line" title={bundle.target_digest ?? ''}>{bundle.target_digest ?? 'no target digest'}</code>
    </article>)}</div>
  </section>
}
