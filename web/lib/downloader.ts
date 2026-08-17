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
  readonly kind: 'api' | 'demo'
  health(): Promise<EngineHealth>
  probe(url: string): Promise<Probe>
  listJobs(): Promise<Job[]>
  createJob(input: CreateJob): Promise<Job>
  deleteJob(id: string): Promise<void>
  fileUrl(id: string): string | null
}

const HEADERS = { 'Content-Type': 'application/json', 'X-Requested-By': 'pullbyte' }
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? '').replace(/\/$/, '')

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

const DEMO_FORMATS: Format[] = [
  {
    format_id: 'demo-2160',
    kind: 'video',
    ext: 'mp4',
    height: 2160,
    fps: 60,
    abr: null,
    vcodec: 'avc1',
    acodec: 'mp4a',
    filesize: 1_260_000_000,
    label: '2160p60',
  },
  {
    format_id: 'demo-1080',
    kind: 'video',
    ext: 'mp4',
    height: 1080,
    fps: 60,
    abr: null,
    vcodec: 'avc1',
    acodec: 'mp4a',
    filesize: 418_000_000,
    label: '1080p60',
  },
  {
    format_id: 'demo-720',
    kind: 'video',
    ext: 'mp4',
    height: 720,
    fps: 30,
    abr: null,
    vcodec: 'avc1',
    acodec: 'mp4a',
    filesize: 184_000_000,
    label: '720p',
  },
  {
    format_id: 'demo-480',
    kind: 'video',
    ext: 'mp4',
    height: 480,
    fps: 30,
    abr: null,
    vcodec: 'avc1',
    acodec: 'mp4a',
    filesize: 92_000_000,
    label: '480p',
  },
  {
    format_id: 'demo-audio',
    kind: 'audio',
    ext: 'm4a',
    height: null,
    fps: null,
    abr: 128,
    vcodec: null,
    acodec: 'mp4a',
    filesize: 8_900_000,
    label: 'Best audio',
  },
]

type DemoJob = Job & { demoSize: number }
let demoJobs: DemoJob[] = []

function demoId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10)
}

function materialize(job: DemoJob): Job {
  const age = Date.now() / 1000 - job.created
  if (age < 0.8) return { ...job, status: 'queued', percent: 0, step: 'Waiting for engine' }
  if (age < 5.8) {
    const percent = Math.min(96, Math.round(((age - 0.8) / 5) * 96))
    return {
      ...job,
      status: 'downloading',
      percent,
      downloaded: Math.round((job.demoSize * percent) / 100),
      total: job.demoSize,
      speed: 12_400_000,
      eta: Math.max(0, Math.ceil((5.8 - age) * 1.1)),
      step: 'Downloading media',
    }
  }
  if (age < 7.2) {
    return {
      ...job,
      status: 'processing',
      percent: null,
      downloaded: job.demoSize,
      total: job.demoSize,
      speed: null,
      eta: null,
      step: job.mode === 'image' ? 'Finalizing' : 'Merging streams',
    }
  }
  return {
    ...job,
    status: 'done',
    percent: 100,
    downloaded: job.demoSize,
    total: job.demoSize,
    speed: null,
    eta: null,
    step: null,
    filename: job.filename ?? `pullbyte-demo.${job.mode === 'audio' ? 'mp3' : job.mode === 'image' ? 'jpg' : 'mp4'}`,
    size: job.demoSize,
  }
}

const demoEngine: DownloaderEngine = {
  kind: 'demo',
  async health() {
    return {
      ready: true,
      name: 'Web preview',
      detail: 'Downloads are simulated. No media leaves your browser.',
    }
  },
  async probe(value) {
    let url: URL
    try {
      url = new URL(value)
    } catch {
      throw new Error('Enter a complete http:// or https:// link.')
    }
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error('Only http:// and https:// links are supported.')
    }
    const image = /\.(avif|gif|jpe?g|png|webp)$/i.test(url.pathname)
    if (image) {
      return {
        kind: 'image',
        url: value,
        title: url.pathname.split('/').filter(Boolean).at(-1) || 'Image',
        uploader: url.hostname,
        duration: null,
        thumbnail: null,
        extractor: 'demo',
        formats: [],
      }
    }
    return {
      kind: 'media',
      url: value,
      title: 'Local-first download preview',
      uploader: url.hostname,
      duration: 11 * 60 + 42,
      thumbnail: null,
      extractor: 'demo',
      formats: DEMO_FORMATS,
    }
  },
  async listJobs() {
    return demoJobs.map(materialize).sort((a, b) => b.created - a.created)
  },
  async createJob(input) {
    const now = Date.now() / 1000
    const size = input.mode === 'audio' ? 18_400_000 : input.mode === 'image' ? 4_800_000 : 418_000_000
    const job: DemoJob = {
      id: demoId(),
      url: input.url,
      mode: input.mode,
      title: input.mode === 'image' ? 'Preview image' : 'Local-first download preview',
      status: 'queued',
      percent: 0,
      downloaded: 0,
      total: size,
      speed: null,
      eta: null,
      step: 'Waiting for engine',
      error: null,
      filename: null,
      size: null,
      created: now,
      demoSize: size,
    }
    demoJobs = [job, ...demoJobs]
    return materialize(job)
  },
  async deleteJob(id) {
    demoJobs = demoJobs.filter((job) => job.id !== id)
  },
  fileUrl() {
    return null
  },
}

export const engine = process.env.NEXT_PUBLIC_ENGINE === 'demo' ? demoEngine : apiEngine
