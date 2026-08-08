import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { BreakdownChart, TaskChart, ThroughputChart, TimelineChart } from './components/Charts'
import { CompareWorkspace } from './components/CompareWorkspace'
import { ReportsWorkspace } from './components/ReportsWorkspace'
import { api } from './lib/api'
import type { KPI, RolloutRow } from './types'

function displayKpi(kpi: KPI) {
  if (kpi.unit === 'ratio') return `${(kpi.value * 100).toFixed(1)}%`
  if (kpi.unit === 'token/s') return kpi.value.toFixed(1)
  if (kpi.unit === 's') return `${kpi.value.toFixed(1)}s`
  return kpi.value.toFixed(3)
}

function delta(kpi: KPI) {
  if (kpi.delta === null) return '—'
  return `${kpi.delta >= 0 ? '+' : ''}${(kpi.delta * 100).toFixed(1)}%`
}

export default function App() {
  const [mode, setMode] = useState<'observe' | 'compare' | 'reports'>('observe')
  const metadata = useQuery({ queryKey: ['metadata'], queryFn: api.metadata, staleTime: 60_000 })
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs, refetchInterval: 30_000 })
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const runId = selectedRun ?? runs.data?.[0]?.run_id
  const dashboard = useQuery({
    queryKey: ['dashboard', runId],
    queryFn: () => api.dashboard(runId!),
    enabled: Boolean(runId),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  })
  const [range, setRange] = useState<[number, number]>([0, 100])
  const [selectedRollout, setSelectedRollout] = useState<string | null>(null)
  const [rolloutQuery, setRolloutQuery] = useState('')
  const [rolloutStatus, setRolloutStatus] = useState('')
  const [rolloutBundle, setRolloutBundle] = useState('')
  const trace = useQuery({
    queryKey: ['trace', selectedRollout],
    queryFn: () => api.trace(selectedRollout!),
    enabled: Boolean(selectedRollout),
  })
  const rolloutPage = useQuery({
    queryKey: ['rollouts', runId, rolloutQuery, rolloutStatus, rolloutBundle],
    queryFn: () => api.rollouts(runId!, {
      offset: 0,
      limit: 200,
      query: rolloutQuery,
      status: rolloutStatus,
      bundle_id: rolloutBundle,
    }),
    enabled: Boolean(runId),
    placeholderData: keepPreviousData,
  })
  const syncRange = useCallback((next: [number, number]) => setRange(current => (
    Math.abs(current[0] - next[0]) + Math.abs(current[1] - next[1]) < 0.2
      ? current
      : next
  )), [])

  useEffect(() => {
    setRange([0, 100])
    setSelectedRollout(null)
    setRolloutQuery('')
    setRolloutStatus('')
    setRolloutBundle('')
  }, [runId])

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedRollout(null)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  const learning = useMemo(() => dashboard.data?.series.filter(item => [
    'reward.mean',
    'success.rate',
    'validation.success_rate',
  ].includes(item.name)) ?? [], [dashboard.data])
  const inference = useMemo(() => dashboard.data?.series.filter(item => [
    'throughput.target_tokens',
    'inference.target_tokens_per_second',
    'speculation.acceptance',
  ].includes(item.name)) ?? [], [dashboard.data])

  if (runs.isLoading || (dashboard.isLoading && !dashboard.data)) return <div className="loading"><span />Reading rollout evidence</div>
  if (runs.isError || dashboard.isError || !dashboard.data) return <div className="loading error">The visualization source is unavailable.</div>
  const data = dashboard.data
  const visibleRollouts = rolloutPage.data?.items ?? data.rollouts
  const activeBundle = data.bundle_details.find(bundle => bundle.bundle_id === data.run.current_bundle)

  return <div className="app-shell">
    <aside className="rail">
      <div className="brand"><span className="brand-mark">RP</span><span>viz</span></div>
      <nav aria-label="Workspace">
        <button aria-pressed={mode === 'observe'} className={mode === 'observe' ? 'active' : ''} onClick={() => setMode('observe')}>Observe</button>
        <button aria-pressed={mode === 'compare'} className={mode === 'compare' ? 'active' : ''} onClick={() => setMode('compare')}>Compare</button>
        <button aria-pressed={mode === 'reports'} className={mode === 'reports' ? 'active' : ''} onClick={() => setMode('reports')}>Reports</button>
      </nav>
      <div className="rail-foot"><i className="live-dot" /> {metadata.data?.source_kind === 'demo' ? 'demo' : 'live'}<br /><small>{metadata.data?.refresh_seconds ? `${metadata.data.refresh_seconds}s source cache` : 'deterministic'}</small></div>
    </aside>

    <main>
      <header className="topbar">
        <div>
          <div className="run-state"><p className="eyebrow">RUN / {data.run.status.toUpperCase()}</p><span key={data.generated_at_ns}>snapshot {new Date(data.generated_at_ns / 1_000_000).toLocaleTimeString()}</span></div>
          <h1>{data.run.name}</h1>
          <p className="context">{data.run.model} · {data.run.environment}{data.run.algorithm ? ` · ${data.run.algorithm}` : ''}</p>
        </div>
        <div className="controls">
          <label>Run<select value={data.run.run_id} onChange={event => setSelectedRun(event.target.value)}>{runs.data?.map(run => <option key={run.run_id} value={run.run_id}>{run.name}</option>)}</select></label>
          <label>Active bundle<select value={data.run.current_bundle} disabled><option>{data.run.current_bundle}</option></select></label>
          <div className="policy-generation"><span>policy step</span><strong>{activeBundle?.policy_step ?? 'legacy'}</strong></div>
        </div>
      </header>

      {mode === 'observe' && <div className="mode-enter">
        <section className="kpis" aria-label="Selected KPIs">
          {data.kpis.map(kpi => <div className="kpi" key={kpi.label}><span>{kpi.label}</span><strong>{displayKpi(kpi)}</strong><em className={kpi.direction}>{delta(kpi)}</em></div>)}
        </section>

        <section className="workspace two-up">
          <article className="panel dominant"><div className="panel-title"><div><p>Learning signal</p><h2>Reward and validation success</h2></div><span>linked time range · drag or wheel</span></div><TimelineChart series={learning} range={range} onRangeChange={syncRange} /></article>
          <article className="panel"><div className="panel-title"><div><p>Inference plane</p><h2>Target throughput × draft acceptance</h2></div><span>same cursor and range</span></div><ThroughputChart series={inference} range={range} onRangeChange={syncRange} /></article>
        </section>

        <section className="workspace triage-grid">
          <article className="panel task-panel"><div className="panel-title"><div><p>Curriculum</p><h2>Success by task</h2></div><span>{data.tasks.reduce((sum, task) => sum + task.attempts, 0)} attempts</span></div><TaskChart tasks={data.tasks} /></article>
          <article className="panel compact"><div className="panel-title"><div><p>Wall-clock</p><h2>Time allocation</h2></div></div><BreakdownChart values={data.wallclock} /></article>
          <article className="panel compact"><div className="panel-title"><div><p>Outcomes</p><h2>Termination causes</h2></div></div><BreakdownChart values={data.terminations} /></article>
        </section>

        <section className="rollout-section">
          <div className="panel-title"><div><p>Evidence ledger</p><h2>Rollouts</h2></div><span>{rolloutPage.data?.total ?? data.rollouts.length} matching · select a row for trace</span></div>
          <div className="rollout-filters"><label>Search<input value={rolloutQuery} onChange={event => setRolloutQuery(event.target.value)} placeholder="task, worker, stop reason" /></label><label>Status<select value={rolloutStatus} onChange={event => setRolloutStatus(event.target.value)}><option value="">All</option><option value="active">Active</option><option value="completed">Completed</option><option value="truncated">Truncated</option><option value="failed">Failed</option></select></label><label>Bundle<select value={rolloutBundle} onChange={event => setRolloutBundle(event.target.value)}><option value="">All bundles</option>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label></div>
          <div className="table-wrap"><table><thead><tr><th>Rollout</th><th>Task</th><th>Bundle</th><th>Reward</th><th>Wall-clock</th><th>Turns</th><th>Stop reason</th></tr></thead><tbody>{visibleRollouts.map(row => <RolloutRowView key={row.rollout_id} row={row} onClick={() => setSelectedRollout(row.rollout_id)} />)}</tbody></table>{!visibleRollouts.length && <div className="empty-table">No rollout matches these filters.</div>}</div>
        </section>
      </div>}
      {mode === 'compare' && <CompareWorkspace data={data} />}
      {mode === 'reports' && <ReportsWorkspace data={data} range={range} />}
    </main>

    <div className={`scrim ${selectedRollout ? 'visible' : ''}`} onClick={() => setSelectedRollout(null)} />
    <aside className={`inspector ${selectedRollout ? 'open' : ''}`} aria-hidden={!selectedRollout} aria-label="Rollout trace">
      <button className="close" onClick={() => setSelectedRollout(null)} aria-label="Close trace">×</button>
      {trace.isLoading && <div className="trace-loading">Reading trace…</div>}
      {trace.data && <><p className="eyebrow">ROLLOUT TRACE</p><h2>{trace.data.rollout.rollout_id}</h2><p className="trace-task">{trace.data.rollout.task} · {trace.data.rollout.task_family}</p><div className="trace-meta"><span>reward <b>{trace.data.rollout.reward.toFixed(3)}</b></span><span>duration <b>{trace.data.rollout.duration_seconds.toFixed(1)}s</b></span><span>chunk <b>{trace.data.rollout.decision_chunk}</b></span></div><ol className="trace-list">{trace.data.events.map(event => <li key={`${event.sequence}:${event.event_type}`}><time>+{event.elapsed_seconds.toFixed(1)}s</time><div><code>{event.event_type}</code><p>{event.summary}</p></div></li>)}</ol></>}
    </aside>
  </div>
}

function RolloutRowView({ row, onClick }: { row: RolloutRow; onClick: () => void }) {
  return <tr onClick={onClick}><td><code>{row.rollout_id}</code><small>{row.worker_id ?? 'unknown worker'}</small></td><td>{row.task}<small>{row.task_family}</small></td><td className="muted">{row.bundle_id}</td><td className={row.reward > 0.7 ? 'good' : row.reward < 0.3 ? 'bad' : ''}>{row.reward.toFixed(3)}</td><td>{row.duration_seconds.toFixed(1)}s</td><td>{row.turns}</td><td><span className={`status ${row.status}`}>{row.termination_reason}</span></td></tr>
}
