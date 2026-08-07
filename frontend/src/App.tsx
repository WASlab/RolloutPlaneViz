import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { BreakdownChart, TaskChart, ThroughputChart, TimelineChart } from './components/Charts'
import { api } from './lib/api'
import type { KPI, RolloutRow } from './types'

function displayKpi(kpi: KPI) {
  if (kpi.unit === 'ratio') return `${(kpi.value * 100).toFixed(1)}%`
  if (kpi.unit === 'token/s') return `${kpi.value.toFixed(1)}`
  if (kpi.unit === 's') return `${kpi.value.toFixed(1)}s`
  return kpi.value.toFixed(3)
}

function delta(kpi: KPI) {
  if (kpi.delta === null) return '—'
  return `${kpi.delta >= 0 ? '+' : ''}${(kpi.delta * 100).toFixed(1)}%`
}

export default function App() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const runId = selectedRun ?? runs.data?.[0]?.run_id
  const dashboard = useQuery({ queryKey: ['dashboard', runId], queryFn: () => api.dashboard(runId!), enabled: Boolean(runId), refetchInterval: 15_000 })
  const [range, setRange] = useState<[number, number]>([0, 100])
  const [selectedRollout, setSelectedRollout] = useState<string | null>(null)
  const trace = useQuery({ queryKey: ['trace', selectedRollout], queryFn: () => api.trace(selectedRollout!), enabled: Boolean(selectedRollout) })
  const syncRange = useCallback((next: [number, number]) => setRange(current => Math.abs(current[0] - next[0]) + Math.abs(current[1] - next[1]) < .2 ? current : next), [])

  const learning = useMemo(() => dashboard.data?.series.filter(item => ['reward.mean', 'success.rate'].includes(item.name)) ?? [], [dashboard.data])
  const inference = useMemo(() => dashboard.data?.series.filter(item => ['throughput.target_tokens', 'speculation.acceptance'].includes(item.name)) ?? [], [dashboard.data])

  if (runs.isLoading || dashboard.isLoading) return <div className="loading"><span />Reading rollout evidence</div>
  if (runs.isError || dashboard.isError || !dashboard.data) return <div className="loading error">The visualization source is unavailable.</div>
  const data = dashboard.data

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand"><span className="brand-mark">RP</span><span>viz</span></div>
        <nav>
          <button className="active">Observe</button>
          <button disabled>Compare</button>
          <button disabled>Reports</button>
        </nav>
        <div className="rail-foot"><i className="live-dot" /> live<br /><small>15s refresh</small></div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="eyebrow">RUN / {data.run.status.toUpperCase()}</p>
            <h1>{data.run.name}</h1>
            <p className="context">{data.run.model} · {data.run.environment}</p>
          </div>
          <div className="controls">
            <label>Run<select value={data.run.run_id} onChange={event => setSelectedRun(event.target.value)}>{runs.data?.map(run => <option key={run.run_id} value={run.run_id}>{run.name}</option>)}</select></label>
            <label>Active bundle<select value={data.run.current_bundle} disabled>{data.bundles.map(bundle => <option key={bundle}>{bundle}</option>)}</select></label>
          </div>
        </header>

        <section className="kpis" aria-label="Selected KPIs">
          {data.kpis.map(kpi => <div className="kpi" key={kpi.label}><span>{kpi.label}</span><strong>{displayKpi(kpi)}</strong><em className={kpi.direction}>{delta(kpi)}</em></div>)}
        </section>

        <section className="workspace two-up">
          <article className="panel dominant">
            <div className="panel-title"><div><p>Learning signal</p><h2>Reward and validation success</h2></div><span>linked time range</span></div>
            <TimelineChart series={learning} range={range} onRangeChange={syncRange} />
          </article>
          <article className="panel">
            <div className="panel-title"><div><p>Inference plane</p><h2>Target throughput × draft acceptance</h2></div><span>strict verification</span></div>
            <ThroughputChart series={inference} range={range} onRangeChange={syncRange} />
          </article>
        </section>

        <section className="workspace triage-grid">
          <article className="panel task-panel"><div className="panel-title"><div><p>Curriculum</p><h2>Success by task</h2></div><span>{data.tasks.reduce((sum, task) => sum + task.attempts, 0)} attempts</span></div><TaskChart tasks={data.tasks} /></article>
          <article className="panel compact"><div className="panel-title"><div><p>Wall-clock</p><h2>Time allocation</h2></div></div><BreakdownChart values={data.wallclock} /></article>
          <article className="panel compact"><div className="panel-title"><div><p>Outcomes</p><h2>Termination causes</h2></div></div><BreakdownChart values={data.terminations} /></article>
        </section>

        <section className="rollout-section">
          <div className="panel-title"><div><p>Evidence ledger</p><h2>Recent rollouts</h2></div><span>Select a row to inspect its trace</span></div>
          <div className="table-wrap"><table><thead><tr><th>Rollout</th><th>Task</th><th>Bundle</th><th>Reward</th><th>Wall-clock</th><th>Turns</th><th>Stop reason</th></tr></thead><tbody>{data.rollouts.map(row => <RolloutRowView key={row.rollout_id} row={row} onClick={() => setSelectedRollout(row.rollout_id)} />)}</tbody></table></div>
        </section>
      </main>

      <div className={`scrim ${selectedRollout ? 'visible' : ''}`} onClick={() => setSelectedRollout(null)} />
      <aside className={`inspector ${selectedRollout ? 'open' : ''}`} aria-hidden={!selectedRollout}>
        <button className="close" onClick={() => setSelectedRollout(null)} aria-label="Close trace">×</button>
        {trace.data && <><p className="eyebrow">ROLLOUT TRACE</p><h2>{trace.data.rollout.rollout_id}</h2><p className="trace-task">{trace.data.rollout.task}</p><div className="trace-meta"><span>reward <b>{trace.data.rollout.reward.toFixed(3)}</b></span><span>duration <b>{trace.data.rollout.duration_seconds}s</b></span></div><ol className="trace-list">{trace.data.events.map(event => <li key={event.sequence}><time>+{event.elapsed_seconds.toFixed(1)}s</time><div><code>{event.event_type}</code><p>{event.summary}</p></div></li>)}</ol></>}
      </aside>
    </div>
  )
}

function RolloutRowView({ row, onClick }: { row: RolloutRow; onClick: () => void }) {
  return <tr onClick={onClick}><td><code>{row.rollout_id}</code></td><td>{row.task}</td><td className="muted">{row.bundle_id}</td><td className={row.reward > .7 ? 'good' : row.reward < .3 ? 'bad' : ''}>{row.reward.toFixed(3)}</td><td>{row.duration_seconds.toFixed(1)}s</td><td>{row.turns}</td><td><span className={`status ${row.status}`}>{row.termination_reason}</span></td></tr>
}
