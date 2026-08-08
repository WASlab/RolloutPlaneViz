import type {
  Comparison,
  ComparisonRequest,
  Dashboard,
  ReportDocument,
  ReportReceipt,
  ReportRequest,
  ReportVerification,
  RolloutPage,
  RolloutTrace,
  RunSummary,
  ServiceMetadata,
} from '../types'

async function responseError(response: Response) {
  const body = await response.json().catch(() => null) as { detail?: string } | null
  return new Error(body?.detail ?? `${response.status} ${response.statusText}`)
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw await responseError(response)
  return response.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await responseError(response)
  return response.json() as Promise<T>
}

export const api = {
  metadata: () => get<ServiceMetadata>('/api/v1/metadata'),
  runs: () => get<RunSummary[]>('/api/v1/runs'),
  dashboard: (runId: string) => get<Dashboard>(`/api/v1/runs/${encodeURIComponent(runId)}/dashboard`),
  compare: (request: ComparisonRequest) => post<Comparison>('/api/v1/comparisons', request),
  trace: (rolloutId: string) => get<RolloutTrace>(`/api/v1/rollouts/${encodeURIComponent(rolloutId)}`),
  rollouts: (runId: string, parameters: Record<string, string | number | null>) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(parameters)) {
      if (value !== null && value !== '') query.set(key, String(value))
    }
    return get<RolloutPage>(`/api/v1/runs/${encodeURIComponent(runId)}/rollouts?${query}`)
  },
  reports: () => get<ReportReceipt[]>('/api/v1/reports'),
  createReport: (request: ReportRequest) => post<ReportReceipt>('/api/v1/reports', request),
  reportSnapshot: (reportId: string) => get<ReportDocument>(`/api/v1/reports/${encodeURIComponent(reportId)}/snapshot`),
  verifyReport: (reportId: string) => get<ReportVerification>(`/api/v1/reports/${encodeURIComponent(reportId)}/verify`),
}
