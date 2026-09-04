import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowDownToLine,
  Ban,
  Box,
  Check,
  ChevronDown,
  CircleX,
  Clock3,
  Download,
  Filter,
  HardDrive,
  KeyRound,
  ListFilter,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  Search,
  Server,
  ShieldAlert,
  SlidersHorizontal,
  Wifi,
} from 'lucide-react'
import {
  HashRouter,
  Navigate,
  Route,
  Routes,
  useSearchParams,
} from 'react-router-dom'
import { api } from './api'
import { LocalDrawer, ModelDrawer } from './components/Drawers'
import { HubModelRow, LocalModelRow } from './components/RepositoryRows'
import Shell from './components/Shell'
import type { DownloadJob, Health, HubModel, LocalModel } from './types'
import { formatBytes, relativeTime } from './utils'

type ToastTone = 'success' | 'error'
type ToastHandler = (message: string, tone?: ToastTone) => void

const taskOptions = [
  ['text-generation', 'Text Generation'],
  ['image-text-to-text', 'Image-Text-to-Text'],
  ['text-to-image', 'Text-to-Image'],
  ['feature-extraction', 'Embeddings'],
  ['automatic-speech-recognition', 'Speech Recognition'],
]
const libraryOptions = [
  ['transformers', 'Transformers'],
  ['gguf', 'GGUF'],
  ['diffusers', 'Diffusers'],
  ['safetensors', 'Safetensors'],
]
const appOptions = [
  ['vllm', 'vLLM'],
  ['llama.cpp', 'llama.cpp'],
  ['ollama', 'Ollama'],
  ['lm-studio', 'LM Studio'],
]
const parameterOptions = [
  ['max:1B', '< 1B'],
  ['min:1B,max:7B', '1B – 7B'],
  ['min:7B,max:32B', '7B – 32B'],
  ['min:32B,max:128B', '32B – 128B'],
  ['min:128B', '> 128B'],
]

function FilterGroup({
  title,
  options,
  value,
  onChange,
}: {
  title: string
  options: string[][]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <section className="filter-group">
      <h3>{title}</h3>
      {options.map(([id, label]) => (
        <button
          type="button"
          key={id}
          className={value === id ? 'selected' : ''}
          onClick={() => onChange(value === id ? '' : id)}
        >
          <span className="filter-check">{value === id && <Check size={12} />}</span>
          {label}
        </button>
      ))}
    </section>
  )
}

function ModelsPage({
  onToast,
  refreshDownloads,
}: {
  onToast: ToastHandler
  refreshDownloads: () => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('search') || '')
  const [task, setTask] = useState('')
  const [library, setLibrary] = useState('')
  const [appFilter, setAppFilter] = useState('')
  const [parameters, setParameters] = useState('')
  const [sort, setSort] = useState('trending')
  const [models, setModels] = useState<HubModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)

  useEffect(() => {
    const next = searchParams.get('search') || ''
    setSearch(next)
  }, [searchParams])

  const fetchModels = useCallback(() => {
    const params = new URLSearchParams({
      search,
      sort,
      limit: '30',
    })
    if (task) params.set('task', task)
    if (library) params.set('library', library)
    if (appFilter) params.set('app', appFilter)
    if (parameters) params.set('parameters', parameters)
    setLoading(true)
    setError('')
    api
      .searchModels(params)
      .then((payload) => setModels(payload.items))
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false))
  }, [appFilter, library, parameters, search, sort, task])

  useEffect(() => {
    const timer = window.setTimeout(fetchModels, 350)
    return () => window.clearTimeout(timer)
  }, [fetchModels])

  function submitSearch() {
    const next = new URLSearchParams(searchParams)
    if (search.trim()) next.set('search', search.trim())
    else next.delete('search')
    setSearchParams(next)
  }

  const activeFilters = [task, library, appFilter, parameters].filter(Boolean).length

  return (
    <>
      <div className="catalog-layout">
        <aside className={mobileFiltersOpen ? 'filters mobile-open' : 'filters'}>
          <div className="filters-heading">
            <Filter size={16} />
            <span>Models</span>
            {activeFilters > 0 && <em>{activeFilters}</em>}
            <button
              type="button"
              className="filter-mobile-close"
              onClick={() => setMobileFiltersOpen(false)}
              aria-label="Close filters"
            >
              <CircleX size={18} />
            </button>
          </div>
          <FilterGroup title="Tasks" options={taskOptions} value={task} onChange={setTask} />
          <FilterGroup
            title="Libraries & formats"
            options={libraryOptions}
            value={library}
            onChange={setLibrary}
          />
          <FilterGroup title="Local apps" options={appOptions} value={appFilter} onChange={setAppFilter} />
          <FilterGroup
            title="Parameters"
            options={parameterOptions}
            value={parameters}
            onChange={setParameters}
          />
          {activeFilters > 0 && (
            <button
              className="clear-filters"
              onClick={() => {
                setTask('')
                setLibrary('')
                setAppFilter('')
                setParameters('')
              }}
            >
              Reset filters
            </button>
          )}
        </aside>

        <section className="catalog-content">
          <div className="page-heading catalog-heading">
            <div>
              <span className="eyebrow">Live from the Hugging Face Hub</span>
              <h1>Explore models</h1>
              <p>Compare useful metadata at a glance, then choose the exact files your local stack needs.</p>
            </div>
            <a href="https://huggingface.co/models" target="_blank" rel="noreferrer" className="quiet-link">
              View on Hugging Face
            </a>
          </div>

          <div className="catalog-tools">
            <div className="catalog-search">
              <Search size={18} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') submitSearch()
                }}
                placeholder="Search model names, authors, and tags"
              />
              {search && (
                <button type="button" onClick={() => setSearch('')} aria-label="Clear search">
                  <CircleX size={16} />
                </button>
              )}
            </div>
            <label className="sort-control">
              <SlidersHorizontal size={15} />
              <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort models">
                <option value="trending">Trending</option>
                <option value="downloads">Most downloaded</option>
                <option value="updated">Recently updated</option>
                <option value="likes">Most liked</option>
              </select>
              <ChevronDown size={14} />
            </label>
            <button
              type="button"
              className="secondary-button mobile-filter-button"
              onClick={() => setMobileFiltersOpen(true)}
            >
              <ListFilter size={15} />
              Filters {activeFilters > 0 ? `(${activeFilters})` : ''}
            </button>
          </div>

          <div className="results-line">
            <span>{loading ? 'Contacting the Hub…' : `${models.length} models shown`}</span>
            <span>Public metadata is read live from huggingface.co</span>
          </div>

          {error && (
            <div className="page-error">
              <AlertCircle size={18} />
              <div>
                <strong>Could not reach Hugging Face</strong>
                <p>{error}</p>
              </div>
              <button onClick={fetchModels}>Retry</button>
            </div>
          )}
          {loading ? (
            <div className="model-card-grid skeleton-card-grid" aria-label="Loading models">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="model-card skeleton-card">
                  <div className="skeleton skeleton-visual" />
                  <div className="model-card-body">
                    <div className="skeleton line-short" />
                    <div className="skeleton line-strong" />
                    <div className="skeleton line-medium" />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="model-card-grid">
              {models.map((model) => (
                <HubModelRow
                  key={model.id}
                  model={model}
                  onOpen={setSelected}
                  onDownload={setSelected}
                />
              ))}
              {!error && models.length === 0 && (
                <div className="empty-state">
                  <Box size={30} />
                  <h2>No matching models</h2>
                  <p>Clear a filter or try a broader repository name.</p>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
      <ModelDrawer
        repoId={selected}
        onClose={() => setSelected(null)}
        onQueued={(repoId) => {
          onToast(`${repoId} was added to the download queue.`)
          refreshDownloads()
        }}
      />
    </>
  )
}

function LocalPage({ onToast }: { onToast: ToastHandler }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [models, setModels] = useState<LocalModel[]>([])
  const [totalBytes, setTotalBytes] = useState(0)
  const [query, setQuery] = useState('')
  const [scanning, setScanning] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setError('')
    Promise.all([api.health(), api.localModels(query)])
      .then(([healthPayload, modelPayload]) => {
        setHealth(healthPayload)
        setModels(modelPayload.items)
        setTotalBytes(modelPayload.total_bytes)
      })
      .catch((reason) => setError(reason.message))
  }, [query])

  useEffect(() => {
    const timer = window.setTimeout(load, 250)
    return () => window.clearTimeout(timer)
  }, [load])

  async function scan() {
    setScanning(true)
    try {
      const result = await api.scanLocalModels()
      onToast(`NAS scan complete: ${result.count} model${result.count === 1 ? '' : 's'} indexed.`)
      load()
    } catch (reason) {
      onToast(reason instanceof Error ? reason.message : 'NAS scan failed', 'error')
    } finally {
      setScanning(false)
    }
  }

  const capacityPercent = health
    ? Math.min(100, ((health.storage.total_bytes - health.storage.free_bytes) / health.storage.total_bytes) * 100)
    : 0

  return (
    <>
      <div className="standard-page">
        <div className="page-heading">
          <div>
            <span className="eyebrow">Indexed from the mounted model folder</span>
            <h1>Local library</h1>
            <p>Everything here is stored on your disk or NAS—not inside the container image.</p>
          </div>
          <button className="secondary-button" onClick={scan} disabled={scanning}>
            {scanning ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />}
            {scanning ? 'Scanning…' : 'Scan folder'}
          </button>
        </div>

        <section className="storage-strip">
          <div className="storage-icon">
            <HardDrive size={23} />
          </div>
          <div className="storage-main">
            <div className="storage-title">
              <strong>{health?.storage.writable ? 'Model storage online' : 'Model storage needs attention'}</strong>
              <code>{health?.storage.path || '/models'}</code>
            </div>
            <div className="capacity-track" aria-label={`${capacityPercent.toFixed(0)} percent of volume used`}>
              <span style={{ width: `${capacityPercent}%` }} />
            </div>
            <div className="storage-meta">
              <span>{health ? `${formatBytes(health.storage.free_bytes)} free on mounted volume` : 'Reading volume…'}</span>
              <span>{formatBytes(totalBytes)} indexed models</span>
            </div>
          </div>
          <span className={health?.storage.writable ? 'status-pill ok' : 'status-pill danger'}>
            {health?.storage.writable ? <Check size={13} /> : <AlertCircle size={13} />}
            {health?.storage.writable ? 'Writable' : 'Read only'}
          </span>
        </section>

        <div className="local-tools">
          <div className="catalog-search">
            <Search size={18} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search local models" />
          </div>
          <span>{models.length} indexed</span>
        </div>

        {error && <div className="inline-error">{error}</div>}
        <div className="repo-list bordered-list">
          {models.map((model) => (
            <LocalModelRow key={model.repo_id} model={model} onOpen={setSelected} />
          ))}
          {!error && models.length === 0 && (
            <div className="empty-state spacious">
              <HardDrive size={34} />
              <h2>Your local model library is empty</h2>
              <p>Download a model from the Models page or copy an existing repository into the mounted folder.</p>
            </div>
          )}
        </div>
      </div>
      <LocalDrawer repoId={selected} onClose={() => setSelected(null)} />
    </>
  )
}

const activeDownloadStatuses = ['queued', 'preparing', 'downloading']

const downloadModeLabels = {
  full: 'Full repository',
  safetensors: 'SafeTensors',
  gguf: 'GGUF selection',
  metadata: 'Metadata only',
  custom: 'Custom selection',
}

function DownloadStatus({
  job,
  onCancel,
  cancelling,
}: {
  job: DownloadJob
  onCancel?: (job: DownloadJob) => void
  cancelling?: boolean
}) {
  const isActive = activeDownloadStatuses.includes(job.status)
  const remaining = Math.max(0, job.total_bytes - job.downloaded_bytes)
  const eta = job.speed_bps > 0 ? Math.round(remaining / job.speed_bps) : 0
  const etaLabel = eta
    ? eta > 3600
      ? `${Math.round(eta / 3600)}h remaining`
      : eta > 60
        ? `${Math.round(eta / 60)}m remaining`
        : `${eta}s remaining`
    : ''
  const modeLabel = downloadModeLabels[job.payload.mode || 'full']

  return (
    <article className="download-row">
      <div className={`download-state-icon ${job.status}`}>
        {job.status === 'complete' ? (
          <PackageCheck size={19} />
        ) : job.status === 'failed' ? (
          <AlertCircle size={18} />
        ) : job.status === 'cancelled' ? (
          <Ban size={18} />
        ) : (
          <ArrowDownToLine size={18} />
        )}
      </div>
      <div className="download-main">
        <div className="download-title">
          <div>
            <h3>{job.repo_id}</h3>
            <span>{modeLabel} · revision {job.revision}</span>
          </div>
          <div className="download-title-actions">
            <strong className={`job-status ${job.status}`}>{job.status}</strong>
            {isActive && onCancel && (
              <button
                type="button"
                className="cancel-download-button"
                onClick={() => onCancel(job)}
                disabled={cancelling}
              >
                {cancelling ? <LoaderCircle size={14} className="spin" /> : <Ban size={14} />}
                {cancelling ? 'Cancelling…' : 'Cancel'}
              </button>
            )}
          </div>
        </div>
        {isActive && (
          <>
            <div className="job-progress" aria-label={`${job.progress.toFixed(0)} percent downloaded`}>
              <span style={{ width: `${Math.max(job.progress, job.status === 'preparing' ? 2 : 0)}%` }} />
            </div>
            <div className="download-stats">
              <span>
                {formatBytes(job.downloaded_bytes)}
                {job.total_bytes > 0 && ` of ${formatBytes(job.total_bytes)}`}
              </span>
              <span>{job.speed_bps > 0 ? `${formatBytes(job.speed_bps)}/s` : 'Preparing repository…'}</span>
              {etaLabel && <span>{etaLabel}</span>}
              {typeof job.metadata.file_count === 'number' && <span>{job.metadata.file_count} repository files</span>}
            </div>
          </>
        )}
        {job.status === 'complete' && (
          <div className="download-stats">
            <span>{formatBytes(job.downloaded_bytes)} stored</span>
            <span>Completed {relativeTime(job.completed_at)}</span>
            <code>{job.target_path}</code>
          </div>
        )}
        {job.status === 'cancelled' && (
          <div className="download-stats cancelled-copy">
            <span>{formatBytes(job.downloaded_bytes)} retained</span>
            <span>Partial files stay in place so a future download can resume.</span>
          </div>
        )}
        {job.status === 'failed' && (
          <div className="download-error">
            <AlertCircle size={15} />
            <span>{job.error}</span>
          </div>
        )}
      </div>
    </article>
  )
}

function DownloadsPage({
  jobs,
  onToast,
  refreshDownloads,
}: {
  jobs: DownloadJob[]
  onToast: ToastHandler
  refreshDownloads: () => void
}) {
  const [cancelling, setCancelling] = useState<string | null>(null)
  const active = jobs.filter((job) => activeDownloadStatuses.includes(job.status))
  const finished = jobs.filter((job) => !active.includes(job))
  const totalSpeed = active.reduce((total, job) => total + job.speed_bps, 0)
  const remainingBytes = active.reduce(
    (total, job) => total + Math.max(0, job.total_bytes - job.downloaded_bytes),
    0,
  )
  const completedCount = jobs.filter((job) => job.status === 'complete').length

  async function cancel(job: DownloadJob) {
    setCancelling(job.id)
    try {
      await api.cancelDownload(job.id)
      onToast(`${job.repo_id} was cancelled. Partial files were kept for resume.`)
      refreshDownloads()
    } catch (reason) {
      onToast(reason instanceof Error ? reason.message : 'Unable to cancel download', 'error')
    } finally {
      setCancelling(null)
    }
  }

  return (
    <div className="standard-page downloads-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Persistent background transfers</span>
          <h1>Downloads</h1>
          <p>Monitor precise transfer activity, stop work safely, and keep partial files ready to resume.</p>
        </div>
      </div>

      <section className="transfer-overview" aria-label="Download activity summary">
        <div><span>Active transfers</span><strong>{active.length}</strong><small>queued or downloading</small></div>
        <div><span>Combined speed</span><strong>{totalSpeed > 0 ? `${formatBytes(totalSpeed)}/s` : '—'}</strong><small>across active jobs</small></div>
        <div><span>Remaining</span><strong>{remainingBytes > 0 ? formatBytes(remainingBytes) : '—'}</strong><small>known repository data</small></div>
        <div><span>Completed</span><strong>{completedCount}</strong><small>stored in the library</small></div>
      </section>

      <section className="download-section">
        <h2>Active</h2>
        <div className="download-list">
          {active.map((job) => (
            <DownloadStatus
              key={job.id}
              job={job}
              onCancel={cancel}
              cancelling={cancelling === job.id}
            />
          ))}
          {active.length === 0 && (
            <div className="empty-compact">
              <Clock3 size={18} /> No active downloads.
            </div>
          )}
        </div>
      </section>
      <section className="download-section">
        <h2>History</h2>
        <div className="download-list">
          {finished.map((job) => (
            <DownloadStatus key={job.id} job={job} />
          ))}
          {finished.length === 0 && <div className="empty-compact">Completed, cancelled, and failed jobs appear here.</div>}
        </div>
      </section>
    </div>
  )
}

function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined)
  }, [])
  return (
    <div className="standard-page settings-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Runtime configuration</span>
          <h1>Settings</h1>
          <p>HuggingHack is configured with environment variables so credentials never enter the browser.</p>
        </div>
      </div>

      <div className="settings-grid">
        <section className="settings-section">
          <div className="settings-section-title">
            <Server size={20} />
            <div>
              <h2>Storage mount</h2>
              <p>The container always sees your configured host folder as /models.</p>
            </div>
          </div>
          <dl className="settings-list">
            <div>
              <dt>Container path</dt>
              <dd><code>{health?.storage.path || '/models'}</code></dd>
            </div>
            <div>
              <dt>Write access</dt>
              <dd className={health?.storage.writable ? 'good-text' : 'danger-text'}>
                {health?.storage.writable ? 'Ready' : 'Not writable'}
              </dd>
            </div>
            <div>
              <dt>Free space</dt>
              <dd>{health ? formatBytes(health.storage.free_bytes) : 'Reading…'}</dd>
            </div>
          </dl>
          <div className="code-block">
            <span>.env</span>
            <code>MODEL_STORAGE_PATH=/volume1/AI/models</code>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-title">
            <KeyRound size={20} />
            <div>
              <h2>Hugging Face access</h2>
              <p>A read token is only needed for private or gated repositories.</p>
            </div>
          </div>
          <dl className="settings-list">
            <div>
              <dt>Endpoint</dt>
              <dd><code>{health?.hf_endpoint || 'https://huggingface.co'}</code></dd>
            </div>
            <div>
              <dt>HF token</dt>
              <dd className={health?.hf_token_configured ? 'good-text' : ''}>
                {health?.hf_token_configured ? 'Configured' : 'Not configured'}
              </dd>
            </div>
          </dl>
          <div className="code-block">
            <span>.env</span>
            <code>HF_TOKEN=hf_your_read_token</code>
          </div>
        </section>
      </div>

      <section className="settings-section security-section">
        <div className="settings-section-title">
          <ShieldAlert size={20} />
          <div>
            <h2>Local network safety</h2>
            <p>Downloaded model files are data until another program loads them.</p>
          </div>
        </div>
        <div className="security-columns">
          <div>
            <strong>HuggingHack never</strong>
            <p>imports model code, unpickles weights, executes repositories, or sends your NAS files elsewhere.</p>
          </div>
          <div>
            <strong>Before exposing it publicly</strong>
            <p>put the app behind authentication and TLS. The default setup is intended for a trusted home LAN.</p>
          </div>
          <div>
            <strong>For gated models</strong>
            <p>accept the publisher's terms on Hugging Face first, then use a read-only token.</p>
          </div>
        </div>
      </section>

      <div className="runtime-line">
        <Wifi size={15} />
        HuggingHack {health?.version || '1.0.0'} · unofficial, local-first, and not affiliated with Hugging Face
      </div>
    </div>
  )
}

function Application() {
  const [jobs, setJobs] = useState<DownloadJob[]>([])
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null)

  const showToast = useCallback((message: string, tone: ToastTone = 'success') => {
    setToast({ message, tone })
  }, [])

  const refreshDownloads = useCallback(() => {
    api
      .downloads()
      .then((payload) => setJobs(payload.items))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    refreshDownloads()
    const timer = window.setInterval(refreshDownloads, 1800)
    return () => window.clearInterval(timer)
  }, [refreshDownloads])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4500)
    return () => window.clearTimeout(timer)
  }, [toast])

  const activeDownloads = useMemo(
    () => jobs.filter((job) => ['queued', 'preparing', 'downloading'].includes(job.status)).length,
    [jobs],
  )

  return (
    <Shell activeDownloads={activeDownloads}>
      <Routes>
        <Route path="/" element={<Navigate to="/models" replace />} />
        <Route
          path="/models"
          element={<ModelsPage onToast={showToast} refreshDownloads={refreshDownloads} />}
        />
        <Route path="/local" element={<LocalPage onToast={showToast} />} />
        <Route
          path="/downloads"
          element={
            <DownloadsPage
              jobs={jobs}
              onToast={showToast}
              refreshDownloads={refreshDownloads}
            />
          }
        />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/models" replace />} />
      </Routes>
      {toast && (
        <div className={`toast ${toast.tone}`} role="status">
          {toast.tone === 'error' ? <AlertCircle size={16} /> : <Check size={16} />}
          {toast.message}
        </div>
      )}
    </Shell>
  )
}

export default function App() {
  return (
    <HashRouter>
      <Application />
    </HashRouter>
  )
}
