export type Mode = 'video' | 'audio' | 'image'
export type Codec = 'mp3' | 'm4a' | 'opus' | 'vorbis' | 'flac' | 'alac' | 'wav'
export type Status = 'queued' | 'downloading' | 'processing' | 'done' | 'error'

export type Format = {
  format_id: string
  kind: 'video' | 'audio'
  ext: string | null
  height: number | null
  fps: number | null
  abr: number | null
  vcodec: string | null
  acodec: string | null
  filesize: number | null
  label: string
}

export type Probe = {
  kind: 'media' | 'image'
  url: string
  title: string
  uploader: string | null
  duration: number | null
  thumbnail: string | null
  extractor: string | null
  formats: Format[]
}

export type Job = {
  id: string
  url: string
  mode: Mode
  title: string | null
  status: Status
  percent: number | null
  downloaded: number
  total: number | null
  speed: number | null
  eta: number | null
  step: string | null
  error: string | null
  filename: string | null
  size: number | null
  created: number
}

export type CreateJob = {
  url: string
  mode: Mode
  format_id: string | null
  audio_codec: Codec
  audio_quality: number
}

export type EngineHealth = {
  ready: boolean
  name: string
  detail: string
}

export interface DownloaderEngine {
  readonly kind: 'api'
  health(): Promise<EngineHealth>
  probe(url: string): Promise<Probe>
  listJobs(): Promise<Job[]>
  createJob(input: CreateJob): Promise<Job>
  deleteJob(id: string): Promise<void>
  fileUrl(id: string): string | null
}

const HEADERS = { 'Content-Type': 'application/json', 'X-Requested-By': 'pullbyte' }
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? '').replace(/\/$/, '')

function isUnconfiguredPagesBuild() {
  return !API_BASE && typeof window !== 'undefined' && window.location.hostname.endsWith('.github.io')
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      // Proxies and misconfigured API routes often answer with HTML. Keep the
      // error actionable instead of leaking a JSON parser exception into UI.
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : null
    throw new Error(detail || `Request failed (${response.status}).`)
  }
  return data as T
}

const apiEngine: DownloaderEngine = {
  kind: 'api',
  async health() {
    if (isUnconfiguredPagesBuild()) {
      return {
        ready: false,
        name: 'Download engine not configured',
        detail: 'This site has no download engine configured yet.',
      }
    }
    try {
      await json('/api/health')
      return {
        ready: true,
        name: API_BASE ? 'Remote engine' : 'Local API',
        detail: API_BASE ? new URL(API_BASE).host : 'FastAPI on this origin',
      }
    } catch {
      return {
        ready: false,
        name: API_BASE ? 'Remote engine offline' : 'API not connected',
        detail: API_BASE || 'Start the FastAPI backend to download files.',
      }
    }
  },
  probe(url) {
    return json<Probe>('/api/probe', {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ url }),
    })
  },
  listJobs() {
    return json<Job[]>('/api/jobs')
  },
  createJob(input) {
    return json<Job>('/api/jobs', {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify(input),
    })
  },
  async deleteJob(id) {
    await json(`/api/jobs/${id}`, { method: 'DELETE', headers: HEADERS })
  },
  fileUrl(id) {
    return `${API_BASE}/api/jobs/${id}/file`
  },
}

export const engine = apiEngine
