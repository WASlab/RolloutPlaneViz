import type { Dashboard, RolloutTrace, RunSummary } from '../types'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

export const api = {
  runs: () => get<RunSummary[]>('/api/v1/runs'),
  dashboard: (runId: string) => get<Dashboard>(`/api/v1/runs/${runId}/dashboard`),
  trace: (rolloutId: string) => get<RolloutTrace>(`/api/v1/rollouts/${rolloutId}`),
}

