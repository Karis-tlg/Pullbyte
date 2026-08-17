export type Mode = 'video' | 'audio' | 'image'
export type Codec = 'mp3' | 'm4a' | 'opus' | 'vorbis' | 'flac' | 'alac' | 'wav'
export type Status = 'queued' | 'downloading' | 'processing' | 'done' | 'error'
export type EngineKind = 'local' | 'remote' | 'none'

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
  kind: EngineKind
  name: string
  detail: string
  downloadDir?: string
}

export interface DownloaderEngine {
  health(): Promise<EngineHealth>
  probe(url: string): Promise<Probe>
  listJobs(): Promise<Job[]>
  createJob(input: CreateJob): Promise<Job>
  deleteJob(id: string): Promise<void>
  fileUrl(id: string): string | null
}

const HEADERS = { 'Content-Type': 'application/json', 'X-Requested-By': 'pullbyte' }
const LOCAL_PORT = process.env.NEXT_PUBLIC_LOCAL_HELPER_PORT ?? '8765'
const LOCAL_BASES = [`http://localhost:${LOCAL_PORT}`, `http://127.0.0.1:${LOCAL_PORT}`] as const
const REMOTE_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? '').replace(/\/$/, '')
const HEALTH_TIMEOUT_MS = 1600

let activeBase = ''
let activeKind: EngineKind = 'none'

function withTimeout(timeoutMs: number) {
  const controller = new AbortController()
  const handle = setTimeout(() => controller.abort(), timeoutMs)
  return { controller, done: () => clearTimeout(handle) }
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      // Keep proxy / HTML failures readable in the UI.
    }
  }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : null
    throw new Error(detail || `Request failed (${response.status}).`)
  }
  return data as T
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!activeBase) throw new Error('Local helper is not connected.')
  const response = await fetch(`${activeBase}${path}`, { cache: 'no-store', ...init })
  return readJson<T>(response)
}

async function checkBase(base: string, kind: Exclude<EngineKind, 'none'>): Promise<EngineHealth | null> {
  const timer = withTimeout(HEALTH_TIMEOUT_MS)
  try {
    const response = await fetch(`${base}/api/health`, {
      cache: 'no-store',
      signal: timer.controller.signal,
      headers: { 'X-Requested-By': 'pullbyte' },
    })
    if (!response.ok) return null
    const data = await readJson<{ engine?: string; download_dir?: string }>(response)
    activeBase = base
    activeKind = kind
    if (kind === 'local') {
      return {
        ready: true,
        kind,
        name: 'Local helper connected',
        detail: 'Downloads run on this computer.',
        downloadDir: data.download_dir,
      }
    }
    return {
      ready: true,
      kind,
      name: 'Remote engine connected',
      detail: new URL(base).host,
      downloadDir: data.download_dir,
    }
  } catch {
    return null
  } finally {
    timer.done()
  }
}

const apiEngine: DownloaderEngine = {
  async health() {
    for (const base of LOCAL_BASES) {
      const local = await checkBase(base, 'local')
      if (local) return local
    }
    if (REMOTE_BASE) {
      const remote = await checkBase(REMOTE_BASE, 'remote')
      if (remote) return remote
    }

    activeBase = ''
    activeKind = 'none'
    return {
      ready: false,
      kind: 'none',
      name: 'Local helper not running',
      detail: 'Start Pullbyte Helper on this computer. Your browser may ask for local network access.',
    }
  },
  probe(url) {
    return request<Probe>('/api/probe', {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ url }),
    })
  },
  listJobs() {
    return request<Job[]>('/api/jobs')
  },
  createJob(input) {
    return request<Job>('/api/jobs', {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify(input),
    })
  },
  async deleteJob(id) {
    await request(`/api/jobs/${id}`, { method: 'DELETE', headers: HEADERS })
  },
  fileUrl(id) {
    return activeBase ? `${activeBase}/api/jobs/${id}/file` : null
  },
}

export const engine = apiEngine
export const helper = {
  baseUrl: LOCAL_BASES[0],
  startUrl: 'pullbyte://start',
  setupUrl: 'https://github.com/Karis-tlg/Pullbyte#local-helper',
  get kind() {
    return activeKind
  },
}
