export interface StorageHealth {
  path: string
  total_bytes: number
  used_bytes: number
  free_bytes: number
  writable: boolean
}

export interface Health {
  status: string
  app: string
  version: string
  storage: StorageHealth
  hf_token_configured: boolean
  hf_endpoint: string
}

export interface HubFile {
  path: string
  size: number
  blob_id?: string | null
}

export interface HubModel {
  id: string
  author?: string | null
  pipeline_tag?: string | null
  library_name?: string | null
  tags: string[]
  downloads: number
  downloads_all_time: number
  likes: number
  trending_score: number
  last_modified?: string | null
  created_at?: string | null
  private: boolean
  gated: boolean | string
  sha?: string | null
  license?: string | null
  parameter_count?: number | null
  local?: boolean
}

export interface HubModelDetails extends HubModel {
  revision: string
  files: HubFile[]
  total_bytes: number
  security_status?: unknown
  source_url: string
  model_card?: string | null
}

export type DownloadMode = 'full' | 'safetensors' | 'gguf' | 'metadata' | 'custom'

export interface DownloadJob {
  id: string
  repo_id: string
  revision: string
  status: 'queued' | 'preparing' | 'downloading' | 'complete' | 'failed' | 'cancelled'
  total_bytes: number
  downloaded_bytes: number
  progress: number
  speed_bps: number
  error?: string | null
  target_path?: string | null
  payload: {
    allow_patterns?: string[]
    ignore_patterns?: string[]
    mode?: DownloadMode
  }
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  completed_at?: string | null
}

export interface LocalModel {
  repo_id: string
  relative_path: string
  size_bytes: number
  file_count: number
  modified_at: string
  downloaded_at?: string | null
  revision?: string | null
  sha?: string | null
  pipeline_tag?: string | null
  library_name?: string | null
  license?: string | null
  tags: string[]
  config: Record<string, unknown>
  source_url?: string | null
  managed: boolean
}

export interface LocalFile {
  path: string
  size: number
  modified_at: string
  unsafe_serialization: boolean
}

export interface LocalModelDetails {
  model: LocalModel
  files: LocalFile[]
  unsafe_file_count: number
  truncated: boolean
}
