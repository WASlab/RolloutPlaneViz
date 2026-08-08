import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import type { Dashboard, ReportRequest } from '../types'

const availableSections = [
  ['overview', 'Run overview'],
  ['learning', 'Learning signal'],
  ['inference', 'Inference performance'],
  ['tasks', 'Curriculum results'],
  ['rollouts', 'Rollout evidence'],
]

export function ReportsWorkspace({ data, range }: { data: Dashboard; range: [number, number] }) {
  const [sections, setSections] = useState(availableSections.map(([value]) => value))
  const report = useMutation({ mutationFn: api.createReport })
  const request: ReportRequest = {
    run_id: data.run.run_id,
    baseline_bundle: data.bundles[0] ?? null,
    candidate_bundle: data.bundles.at(-1) ?? null,
    range_start_percent: range[0],
    range_end_percent: range[1],
    sections,
  }
  const toggle = (section: string) => setSections(current => current.includes(section) ? current.filter(item => item !== section) : [...current, section])

  return <section className="mode-workspace report-workspace">
    <div className="mode-heading"><div><p className="eyebrow">REPRODUCIBLE REPORT</p><h2>Freeze the evidence behind this view</h2><p>The receipt binds filters and source data to a SHA-256 digest. Charts print as vectors.</p></div></div>
    <div className="report-grid">
      <article className="report-config"><p className="section-label">Included sections</p>{availableSections.map(([value, title]) => <label className="check-row" key={value}><input type="checkbox" checked={sections.includes(value)} onChange={() => toggle(value)} /><span>{title}</span></label>)}<dl><div><dt>Time range</dt><dd>{range[0].toFixed(1)}–{range[1].toFixed(1)}%</dd></div><div><dt>Baseline</dt><dd>{request.baseline_bundle}</dd></div><div><dt>Candidate</dt><dd>{request.candidate_bundle}</dd></div></dl><button className="primary-action" disabled={!sections.length || report.isPending} onClick={() => report.mutate(request)}>{report.isPending ? 'Freezing…' : 'Create report receipt'}</button></article>
      <article className="report-receipt">{report.data ? <><p className="section-label">Immutable receipt</p><h3>{report.data.report_id}</h3><div className="digest"><span>DATA DIGEST</span><code>{report.data.data_digest}</code></div><dl><div><dt>Metric points</dt><dd>{report.data.metric_count}</dd></div><div><dt>Rollouts</dt><dd>{report.data.rollout_count}</dd></div><div><dt>Captured</dt><dd>{new Date(report.data.created_at_ns / 1_000_000).toLocaleString()}</dd></div></dl><div className="receipt-actions"><a href={`/api/v1/reports/${report.data.report_id}/metrics.csv`}>Download metrics CSV</a><button onClick={() => window.print()}>Print vector report</button></div></> : <div className="receipt-placeholder"><span>SHA-256</span><p>Create a receipt to lock this run, range, and section selection.</p></div>}</article>
    </div>
  </section>
}

