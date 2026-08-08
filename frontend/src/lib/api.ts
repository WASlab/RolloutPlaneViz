import type { Comparison, Dashboard, ReportReceipt, ReportRequest, RolloutTrace, RunSummary } from '../types'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

export const api = {
  runs: () => get<RunSummary[]>('/api/v1/runs'),
  dashboard: (runId: string) => get<Dashboard>(`/api/v1/runs/${runId}/dashboard`),
  compare: (runId: string, baseline: string, candidate: string) => {
    const query = new URLSearchParams({ baseline, candidate })
    return get<Comparison>(`/api/v1/runs/${runId}/compare?${query}`)
  },
  trace: (rolloutId: string) => get<RolloutTrace>(`/api/v1/rollouts/${rolloutId}`),
  createReport: (request: ReportRequest) => post<ReportReceipt>('/api/v1/reports', request),
}
