import type {
  DownloadJob,
  DownloadMode,
  Health,
  HubModel,
  HubModelDetails,
  LocalModel,
  LocalModelDetails,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed with status ${response.status}`)
  }
  return payload as T
}

const repoPath = (repoId: string) =>
  repoId
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/')

export const api = {
  health: () => request<Health>('/api/health'),
  searchModels: (params: URLSearchParams) =>
    request<{ items: HubModel[]; count: number }>(`/api/hub/models?${params.toString()}`),
  modelDetails: (repoId: string) =>
    request<HubModelDetails>(`/api/hub/models/${repoPath(repoId)}`),
  downloads: () => request<{ items: DownloadJob[]; active: number }>('/api/downloads'),
  startDownload: (payload: {
    repo_id: string
    revision?: string
    allow_patterns?: string[]
    ignore_patterns?: string[]
    mode?: DownloadMode
  }) =>
    request<DownloadJob>('/api/downloads', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelDownload: (downloadId: string) =>
    request<DownloadJob>(`/api/downloads/${encodeURIComponent(downloadId)}/cancel`, {
      method: 'POST',
    }),
  localModels: (query = '') =>
    request<{ items: LocalModel[]; count: number; total_bytes: number }>(
      `/api/local-models?query=${encodeURIComponent(query)}`,
    ),
  scanLocalModels: () =>
    request<{ count: number; models: LocalModel[]; scanned_at: string }>(
      '/api/local-models/scan',
      { method: 'POST' },
    ),
  localModelDetails: (repoId: string) =>
    request<LocalModelDetails>(`/api/local-models/${repoPath(repoId)}`),
}
