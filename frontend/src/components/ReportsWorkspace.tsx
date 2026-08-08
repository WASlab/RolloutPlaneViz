import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Dashboard, ReportReceipt, ReportRequest } from '../types'

const availableSections = [
  ['overview', 'Run overview'],
  ['learning', 'Learning signal'],
  ['inference', 'Inference performance'],
  ['tasks', 'Curriculum results'],
  ['rollouts', 'Rollout evidence'],
  ['provenance', 'Bundle provenance'],
]

export function ReportsWorkspace({ data, range }: { data: Dashboard; range: [number, number] }) {
  const queryClient = useQueryClient()
  const [sections, setSections] = useState(availableSections.map(([value]) => value))
  const [selected, setSelected] = useState<ReportReceipt | null>(null)
  const reports = useQuery({ queryKey: ['reports'], queryFn: api.reports })
  const report = useMutation({
    mutationFn: api.createReport,
    onSuccess: receipt => {
      setSelected(receipt)
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
    },
  })
  const active = selected ?? report.data ?? null
  const verification = useQuery({
    queryKey: ['report-verification', active?.report_id],
    queryFn: () => api.verifyReport(active!.report_id),
    enabled: Boolean(active),
    staleTime: 0,
  })

  useEffect(() => {
    setSelected(null)
  }, [data.run.run_id])

  const request: ReportRequest = {
    run_id: data.run.run_id,
    baseline_bundle: data.bundles[0] ?? null,
    candidate_bundle: data.bundles.at(-1) ?? null,
    range_start_percent: range[0],
    range_end_percent: range[1],
    sections,
  }
  const toggle = (section: string) => setSections(current => current.includes(section)
    ? current.filter(item => item !== section)
    : [...current, section])

  return <section className="mode-workspace report-workspace">
    <div className="mode-heading">
      <div><p className="eyebrow">REPRODUCIBLE REPORT</p><h2>Freeze the evidence behind this view</h2><p>The receipt binds exact timestamps, filters, bundle provenance, and source data to a SHA-256 digest.</p></div>
    </div>
    <div className="report-grid">
      <article className="report-config">
        <p className="section-label">Included sections</p>
        {availableSections.map(([value, title]) => <label className="check-row" key={value}><input type="checkbox" checked={sections.includes(value)} onChange={() => toggle(value)} /><span>{title}</span></label>)}
        <dl><div><dt>Visible time range</dt><dd>{range[0].toFixed(1)}–{range[1].toFixed(1)}%</dd></div><div><dt>Baseline</dt><dd>{request.baseline_bundle}</dd></div><div><dt>Candidate</dt><dd>{request.candidate_bundle}</dd></div></dl>
        <button className="primary-action" disabled={!sections.length || report.isPending} onClick={() => report.mutate(request)}>{report.isPending ? 'Freezing…' : 'Create report receipt'}</button>
        {report.isError && <p className="action-error">{report.error.message}</p>}
      </article>

      <article className="report-receipt">
        {active ? <Receipt receipt={active} verified={verification.data?.verified ?? null} /> : <div className="receipt-placeholder"><span>SHA-256</span><p>Create a receipt to lock this run, range, and section selection.</p></div>}
      </article>
    </div>

    <section className="report-catalog">
      <div className="panel-title"><div><p>Stored snapshots</p><h2>Report catalog</h2></div><span>{reports.data?.length ?? 0} receipts</span></div>
      {reports.isLoading ? <div className="empty-state compact-empty">Reading report store…</div> : reports.isError ? <div className="empty-state compact-empty">The report catalog is unavailable.</div> : reports.data?.length ? <table><thead><tr><th>Receipt</th><th>Run</th><th>Captured</th><th>Range</th><th>Evidence</th><th>Source</th></tr></thead><tbody>{reports.data.map(receipt => <tr key={receipt.report_id} className={active?.report_id === receipt.report_id ? 'selected-row' : ''} onClick={() => setSelected(receipt)}><td><code>{receipt.report_id}</code></td><td>{receipt.request.run_id}</td><td>{new Date(receipt.created_at_ns / 1_000_000).toLocaleString()}</td><td>{new Date(receipt.range_start_ns / 1_000_000).toLocaleTimeString()} → {new Date(receipt.range_end_ns / 1_000_000).toLocaleTimeString()}</td><td>{receipt.metric_count} points · {receipt.rollout_count} rollouts</td><td>{receipt.source_kind}</td></tr>)}</tbody></table> : <div className="empty-state compact-empty">No immutable receipts have been stored.</div>}
    </section>
  </section>
}

function Receipt({ receipt, verified }: { receipt: ReportReceipt; verified: boolean | null }) {
  return <>
    <div className="receipt-heading"><div><p className="section-label">Immutable receipt</p><h3>{receipt.report_id}</h3></div><span className={`verification ${verified === true ? 'verified' : verified === false ? 'invalid' : ''}`}>{verified === true ? 'verified' : verified === false ? 'digest mismatch' : 'verifying'}</span></div>
    <div className="digest"><span>DATA DIGEST</span><code>{receipt.data_digest}</code></div>
    <dl><div><dt>Metric points</dt><dd>{receipt.metric_count.toLocaleString()}</dd></div><div><dt>Rollouts / tasks</dt><dd>{receipt.rollout_count} / {receipt.task_count}</dd></div><div><dt>Exact range</dt><dd>{new Date(receipt.range_start_ns / 1_000_000).toLocaleString()}<br />{new Date(receipt.range_end_ns / 1_000_000).toLocaleString()}</dd></div><div><dt>Captured</dt><dd>{new Date(receipt.created_at_ns / 1_000_000).toLocaleString()}</dd></div></dl>
    <div className="receipt-actions"><a href={`/api/v1/reports/${receipt.report_id}/export.zip`}>Download evidence ZIP</a><a className="secondary-link" href={`/api/v1/reports/${receipt.report_id}/metrics.csv`}>Metrics CSV</a><button onClick={() => window.print()}>Print vector report</button></div>
  </>
}
