import {
  Boxes,
  Check,
  Download,
  FileBox,
  Heart,
  LockKeyhole,
  RefreshCw,
} from 'lucide-react'
import type { HubModel, LocalModel } from '../types'
import { formatBytes, formatNumber, initials, relativeTime, taskLabel } from '../utils'

interface HubRowProps {
  model: HubModel
  onOpen: (repoId: string) => void
  onDownload: (repoId: string) => void
  queuing?: boolean
}

function visibleTags(model: HubModel): string[] {
  const ignored = new Set([
    model.pipeline_tag || '',
    model.library_name || '',
    `license:${model.license || ''}`,
  ])
  return model.tags
    .filter((tag) => !ignored.has(tag) && !tag.startsWith('arxiv:') && tag.length < 28)
    .slice(0, 2)
}

function visualClass(task?: string | null): string {
  if (!task) return 'model-visual-neutral'
  if (task.includes('image') || task.includes('video')) return 'model-visual-vision'
  if (task.includes('audio') || task.includes('speech')) return 'model-visual-audio'
  if (task.includes('generation')) return 'model-visual-generation'
  if (task.includes('embedding') || task.includes('similarity') || task.includes('extraction')) {
    return 'model-visual-embedding'
  }
  return 'model-visual-neutral'
}

function parameterLevel(value?: number | null): number {
  if (!value) return 0
  const billions = value / 1_000_000_000
  if (billions < 1) return 1
  if (billions < 7) return 2
  if (billions < 32) return 3
  if (billions < 128) return 4
  if (billions < 500) return 5
  return 6
}

export function HubModelRow({ model, onOpen, onDownload, queuing }: HubRowProps) {
  const [owner, ...nameParts] = model.id.split('/')
  const name = nameParts.join('/')
  const level = parameterLevel(model.parameter_count)
  return (
    <article
      className="model-card"
      onClick={() => onOpen(model.id)}
      tabIndex={0}
      role="button"
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen(model.id)
        }
      }}
      aria-label={`Open ${model.id} model details`}
      aria-haspopup="dialog"
    >
      <div className={`model-visual ${visualClass(model.pipeline_tag)}`} aria-hidden="true">
        <div className="model-visual-topline">
          <span>{taskLabel(model.pipeline_tag)}</span>
          {model.local && (
            <span className="visual-local-badge">
              <Check size={11} /> On NAS
            </span>
          )}
        </div>
        <div className="model-visual-core">
          <span className="model-monogram">{initials(model.id)}</span>
          <div className="parameter-viz">
            {Array.from({ length: 6 }).map((_, index) => (
              <span key={index} className={index < level ? 'filled' : ''} />
            ))}
          </div>
        </div>
        <div className="model-visual-caption">
          <Boxes size={13} />
          <span>{model.parameter_count ? `${formatNumber(model.parameter_count)} parameters` : 'Repository model'}</span>
        </div>
      </div>
      <div className="model-card-body">
        <div className="model-owner-line">
          <span>{owner}</span>
          {model.gated && (
            <span className="tiny-icon" title="Gated repository">
              <LockKeyhole size={13} />
            </span>
          )}
        </div>
        <h3 title={model.id}>{name || model.id}</h3>
        <div className="repo-tags">
          {model.library_name && <span>{model.library_name}</span>}
          {visibleTags(model).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className="model-card-meta">
          <span>Updated {relativeTime(model.last_modified)}</span>
          <span>
            <Download size={13} /> {formatNumber(model.downloads)}
          </span>
          <span>
            <Heart size={13} /> {formatNumber(model.likes)}
          </span>
        </div>
        <button
          type="button"
          className={model.local ? 'secondary-button compact model-card-action' : 'download-button compact model-card-action'}
          disabled={queuing}
          onClick={(event) => {
            event.stopPropagation()
            onDownload(model.id)
          }}
        >
          {queuing ? <RefreshCw size={15} className="spin" /> : <Download size={15} />}
          {model.local ? 'Update model' : 'Download'}
        </button>
      </div>
    </article>
  )
}

interface LocalRowProps {
  model: LocalModel
  onOpen: (repoId: string) => void
}

export function LocalModelRow({ model, onOpen }: LocalRowProps) {
  return (
    <article
      className="repo-row local-row"
      onClick={() => onOpen(model.repo_id)}
      tabIndex={0}
      role="button"
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') onOpen(model.repo_id)
      }}
    >
      <div className="repo-avatar local-avatar" aria-hidden="true">
        {initials(model.repo_id)}
      </div>
      <div className="repo-main">
        <div className="repo-title-line">
          <h3>{model.repo_id}</h3>
          {model.managed && <span className="local-badge">Managed</span>}
        </div>
        <div className="repo-tags">
          {model.pipeline_tag && <span className="task-tag">{taskLabel(model.pipeline_tag)}</span>}
          {model.library_name && <span>{model.library_name}</span>}
          {model.license && <span>{model.license}</span>}
        </div>
        <div className="repo-meta">
          <span>
            <FileBox size={13} /> {model.file_count} files
          </span>
          <span>{formatBytes(model.size_bytes)}</span>
          <span>Indexed {relativeTime(model.modified_at)}</span>
        </div>
        <code className="repo-path">{model.relative_path}</code>
      </div>
    </article>
  )
}
