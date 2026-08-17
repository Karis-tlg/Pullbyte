'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowDownIcon,
  CheckCircleIcon,
  CheckIcon,
  ClipboardIcon,
  FilmSlateIcon,
  ImageIcon,
  LinkIcon,
  MusicNotesIcon,
  SpinnerGapIcon,
  TrashIcon,
  WarningCircleIcon,
  WaveformIcon,
} from '@phosphor-icons/react'
import {
  engine,
  helper,
  type Codec,
  type EngineHealth,
  type Job,
  type Mode,
  type Probe,
  type Status,
} from '@/lib/downloader'

const RUNNING: Status[] = ['queued', 'downloading', 'processing']
const NBSP = ' '
const STATUS_TEXT: Record<Status, string> = {
  queued: 'Queued',
  downloading: 'Downloading',
  processing: 'Processing',
  done: 'Ready',
  error: 'Failed',
}

const CODECS: { id: Codec; name: string; note: string; lossless?: boolean }[] = [
  { id: 'mp3', name: 'MP3', note: 'Universal' },
  { id: 'm4a', name: 'M4A', note: 'Apple friendly' },
  { id: 'opus', name: 'Opus', note: 'Small + clean' },
  { id: 'vorbis', name: 'OGG', note: 'Open format' },
  { id: 'flac', name: 'FLAC', note: 'Lossless', lossless: true },
  { id: 'alac', name: 'ALAC', note: 'Apple lossless', lossless: true },
  { id: 'wav', name: 'WAV', note: 'Uncompressed', lossless: true },
]
const BITRATES = [128, 192, 256, 320]

function bytes(n: number | null | undefined) {
  if (!n) return null
  const units = ['B', 'KB', 'MB', 'GB']
  let value = n
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value < 10 && index > 0 ? value.toFixed(1) : Math.round(value)}${NBSP}${units[index]}`
}

function clock(sec: number | null | undefined) {
  if (sec == null) return null
  const rounded = Math.round(sec)
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

function tier(height: number | null) {
  if (!height) return null
  if (height >= 4320) return '8K'
  if (height >= 2160) return '4K'
  if (height >= 1440) return '2K'
  if (height >= 1080) return 'Full HD'
  if (height >= 720) return 'HD'
  return 'SD'
}

function BrandMark({ size = 38 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" className="shrink-0">
      <rect x="1.5" y="1.5" width="45" height="45" rx="13" fill="#c6f24e" />
      <path
        d="M24 11.5v18M24 30.5 15.5 22M24 30.5 32.5 22M14 36h20"
        stroke="#0b0c0a"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}

function DownloadList({
  jobs,
  confirmId,
  onConfirm,
  onDelete,
  local,
}: {
  jobs: Job[]
  confirmId: string | null
  onConfirm: (id: string | null) => void
  onDelete: (id: string) => void
  local: boolean
}) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-card border border-dashed border-ink-line p-7 text-center">
        <ArrowDownIcon size={26} className="mx-auto text-muted/55" aria-hidden="true" />
        <p className="mt-3 font-medium text-cream">Queue is clear</p>
        <p className="mt-1 text-sm leading-6 text-muted">Inspect a link and your download will show up here.</p>
      </div>
    )
  }

  return (
    <ul className="space-y-2">
      {jobs.map((job) => {
        const running = RUNNING.includes(job.status)
        const percent = job.percent ?? 0
        const name = job.filename || job.title || job.url
        const Icon = job.mode === 'audio' ? MusicNotesIcon : job.mode === 'image' ? ImageIcon : FilmSlateIcon
        const fileUrl = job.status === 'done' ? engine.fileUrl(job.id) : null
        return (
          <li key={job.id} className="rounded-[16px] border border-ink-line bg-ink p-4">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-ink-line bg-ink-soft text-muted">
                <Icon size={18} aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-cream">{name}</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                  <span className={job.status === 'error' ? 'text-danger' : job.status === 'done' ? 'text-acid' : ''}>
                    {STATUS_TEXT[job.status]}
                  </span>
                  {job.step ? <span>{job.step}</span> : null}
                  {job.status === 'done' && job.size ? <span className="tnum">{bytes(job.size)}</span> : null}
                  {job.status === 'downloading' && job.total ? (
                    <span className="tnum">{bytes(job.downloaded)} / {bytes(job.total)}</span>
                  ) : null}
                  {job.status === 'downloading' && job.speed ? <span className="tnum">{bytes(job.speed)}/s</span> : null}
                  {job.status === 'downloading' && job.eta != null ? <span className="tnum">{clock(job.eta)} left</span> : null}
                </div>
                {job.error ? <p className="mt-1 text-xs break-words text-danger">{job.error}</p> : null}
                {running ? (
                  <div
                    role="progressbar"
                    aria-valuenow={job.status === 'processing' ? undefined : Math.round(percent)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${STATUS_TEXT[job.status]} ${name}`}
                    className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-soft"
                  >
                    <div
                      className={`h-full w-full rounded-full bg-acid ${job.status === 'processing' ? 'animate-pulse' : ''}`}
                      style={{
                        transformOrigin: 'left',
                        transform: `scaleX(${job.status === 'processing' ? 1 : percent / 100})`,
                        transition: 'transform 240ms linear',
                      }}
                    />
                  </div>
                ) : null}
              </div>
            </div>

            {!running ? (
              <div className="mt-3 flex items-center justify-end gap-2 border-t border-ink-line/70 pt-3">
                {fileUrl ? (
                  <>
                    {local ? <span className="mr-auto text-xs text-acid">Saved locally</span> : null}
                    <a href={fileUrl} className="button-secondary">
                      <CheckCircleIcon size={15} weight="bold" aria-hidden="true" /> {local ? 'Download copy' : 'Save file'}
                    </a>
                  </>
                ) : job.status === 'done' ? (
                  <span className="mr-auto text-xs text-danger">File unavailable from the connected engine.</span>
                ) : null}
                {confirmId === job.id ? (
                  <>
                    <button type="button" onClick={() => onDelete(job.id)} className="button-danger">Remove</button>
                    <button type="button" onClick={() => onConfirm(null)} className="button-ghost">Cancel</button>
                  </>
                ) : (
                  <button type="button" onClick={() => onConfirm(job.id)} className="button-icon" aria-label={`Remove ${name}`}>
                    <TrashIcon size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

export default function Page() {
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<Mode>('video')
  const [probe, setProbe] = useState<Probe | null>(null)
  const [formatId, setFormatId] = useState('')
  const [codec, setCodec] = useState<Codec>('mp3')
  const [bitrate, setBitrate] = useState(192)
  const [probing, setProbing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [health, setHealth] = useState<EngineHealth | null>(null)
  const [announce, setAnnounce] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const seen = useRef<Record<string, Status>>({})
  const primed = useRef(false)
  const urlRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async (): Promise<number> => {
    try {
      const list = await engine.listJobs()
      setJobs(list)
      for (const job of list) {
        if (seen.current[job.id] === job.status) continue
        seen.current[job.id] = job.status
        if (!primed.current) continue
        const name = job.title || job.filename || 'Download'
        if (job.status === 'done') setAnnounce(`${name} is ready.`)
        else if (job.status === 'error') setAnnounce(`${name} failed. ${job.error ?? ''}`)
        else if (job.status === 'processing') setAnnounce(`${name} is processing.`)
        else if (job.status === 'downloading') setAnnounce(`${name} is downloading.`)
      }
      primed.current = true
      return list.some((job) => RUNNING.includes(job.status)) ? 700 : 4000
    } catch {
      return 4000
    }
  }, [])

  useEffect(() => {
    let handle: ReturnType<typeof setTimeout>
    let stopped = false
    const check = async () => {
      const status = await engine.health()
      if (stopped) return
      setHealth(status)
      handle = setTimeout(check, 5000)
    }
    check()
    return () => {
      stopped = true
      clearTimeout(handle)
    }
  }, [])

  useEffect(() => {
    if (!health?.ready) {
      setJobs([])
      return
    }
    let handle: ReturnType<typeof setTimeout>
    let stopped = false
    const tick = async () => {
      const delay = await refresh()
      if (!stopped) handle = setTimeout(tick, delay)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(handle)
    }
  }, [health?.ready, refresh])

  function fail(message: string) {
    setError(message)
    urlRef.current?.focus()
  }

  async function inspectLink(event: React.FormEvent) {
    event.preventDefault()
    const value = url.trim()
    if (!value) {
      fail('Paste a link first.')
      return
    }
    setProbing(true)
    setError(null)
    setProbe(null)
    try {
      const result = await engine.probe(value)
      setProbe(result)
      if (result.kind === 'image') {
        setMode('image')
        setFormatId('')
      } else {
        setMode('video')
        setFormatId(result.formats.find((format) => format.kind === 'video')?.format_id ?? '')
      }
      setAnnounce(`Link inspected. ${result.title}.`)
    } catch (caught) {
      fail((caught as Error).message)
    } finally {
      setProbing(false)
    }
  }

  async function pasteLink() {
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        setUrl(text.trim())
        setError(null)
        urlRef.current?.focus()
      }
    } catch {
      fail('Clipboard access was blocked. Paste the link manually.')
    }
  }

  async function startDownload() {
    if (!probe) return
    setError(null)
    try {
      await engine.createJob({
        url: probe.url,
        mode,
        format_id: mode === 'image' ? null : formatId || null,
        audio_codec: codec,
        audio_quality: bitrate,
      })
      setProbe(null)
      setUrl('')
      setAnnounce('Download queued.')
      urlRef.current?.focus()
      refresh()
    } catch (caught) {
      fail((caught as Error).message)
    }
  }

  async function deleteJob(id: string) {
    try {
      await engine.deleteJob(id)
      setJobs((current) => current.filter((job) => job.id !== id))
      setConfirmId(null)
      setAnnounce('Download removed.')
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  const pool = probe
    ? probe.formats.filter((format) => (mode === 'audio' ? format.kind === 'audio' : format.kind === 'video'))
    : []
  const canDownload = !!probe && (probe.kind === 'image' || pool.length > 0)
  const isLossless = CODECS.find((item) => item.id === codec)?.lossless === true

  return (
    <div className="min-h-dvh">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5 sm:px-8 sm:py-7">
        <div className="flex items-center gap-3">
          <BrandMark />
          <p className="text-xl font-semibold tracking-[-0.03em] text-cream" translate="no">Pullbyte</p>
        </div>
        <span className="rounded-full border border-ink-line bg-ink-soft px-3 py-1.5 text-xs font-medium text-muted">
          {health?.ready ? (health.kind === 'local' ? 'Local helper' : 'Engine connected') : health ? 'Helper offline' : 'Checking helper'}
        </span>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl px-5 pb-16 outline-none sm:px-8 sm:pb-24">
        <section className="pt-8 lg:pt-16">
          <div className="mx-auto max-w-4xl">
            <section className="mt-3 rounded-card border border-ink-line bg-ink-soft p-5 shadow-[0_24px_80px_rgba(0,0,0,0.28)] sm:p-7" aria-labelledby="composer-heading">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="eyebrow">New download</p>
                  <h2 id="composer-heading" className="mt-1 text-xl font-semibold text-cream">Inspect a link</h2>
                </div>
                <span
                  className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                    health?.ready
                      ? 'border-acid/35 bg-acid/8 text-acid'
                      : health
                        ? 'border-danger/35 bg-danger/8 text-danger'
                        : 'border-ink-line bg-ink text-muted'
                  }`}
                >
                  {health?.ready ? 'Ready' : health ? 'Offline' : 'Checking'}
                </span>
              </div>

              <form onSubmit={inspectLink} noValidate className="mt-5">
                <label htmlFor="url" className="sr-only">Media link</label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <div className="relative min-w-0 flex-1">
                    <LinkIcon size={18} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-muted" aria-hidden="true" />
                    <input
                      ref={urlRef}
                      id="url"
                      name="url"
                      type="url"
                      inputMode="url"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="Paste a YouTube, TikTok, image…"
                      value={url}
                      onChange={(event) => setUrl(event.target.value)}
                      aria-invalid={error ? true : undefined}
                      aria-describedby={error ? 'url-error url-help' : 'url-help'}
                      className="control h-12 w-full pr-20 pl-10"
                    />
                    <button type="button" onClick={pasteLink} className="absolute top-1/2 right-2 -translate-y-1/2 rounded-[8px] px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-ink-soft hover:text-cream">
                      <ClipboardIcon size={14} className="mr-1 inline" aria-hidden="true" /> Paste
                    </button>
                  </div>
                  <button type="submit" disabled={probing || !health?.ready} className="button-primary h-12 px-6">
                    {probing ? <><SpinnerGapIcon size={17} weight="bold" className="animate-spin" aria-hidden="true" />Inspecting…</> : 'Inspect link'}
                  </button>
                </div>
                <p id="url-help" className="mt-2 text-xs leading-5 text-muted">
                  Single items only. Playlists stay out of scope until the core flow is solid.
                </p>
              </form>

              {health && !health.ready ? (
                <div role="status" className="mt-4 flex items-start gap-3 rounded-[12px] border border-danger/30 bg-danger/7 p-3 text-sm leading-6 text-muted">
                  <WarningCircleIcon size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <p><strong className="font-semibold text-cream">Local helper is not running.</strong> {health.detail}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <a href={helper.startUrl} className="button-secondary">Start helper</a>
                      <a href={helper.setupUrl} target="_blank" rel="noreferrer" className="button-ghost">Install helper</a>
                    </div>
                  </div>
                </div>
              ) : null}

              {error ? (
                <p id="url-error" role="alert" className="mt-4 flex items-start gap-2 rounded-[12px] border border-danger/35 bg-danger/8 p-3 text-sm text-danger">
                  <WarningCircleIcon size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
                  <span className="min-w-0 break-words">{error}</span>
                </p>
              ) : null}

              {probe ? (
                <div className="mt-6 border-t border-ink-line pt-6">
                  <div className="flex items-center gap-4">
                    {probe.thumbnail ? (
                      <img src={probe.thumbnail} alt="" width={128} height={72} loading="eager" className="h-[72px] w-32 shrink-0 rounded-[12px] object-cover" />
                    ) : (
                      <span className="grid h-[72px] w-32 shrink-0 place-items-center rounded-[12px] border border-ink-line bg-ink text-muted">
                        {probe.kind === 'image' ? <ImageIcon size={28} aria-hidden="true" /> : <FilmSlateIcon size={28} aria-hidden="true" />}
                      </span>
                    )}
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-cream">{probe.title}</p>
                      <p className="mt-1 truncate text-sm text-muted">
                        {[probe.uploader, probe.duration ? clock(probe.duration) : probe.kind === 'image' ? 'Image' : null].filter(Boolean).join(` ${NBSP}·${NBSP} `)}
                      </p>
                    </div>
                  </div>

                  {probe.kind === 'media' ? (
                    <>
                      <fieldset className="mt-6">
                        <legend className="field-label">Output</legend>
                        <div className="mt-2 grid grid-cols-2 gap-2">
                          {([
                            ['video', 'Video', 'Picture + sound', FilmSlateIcon],
                            ['audio', 'Audio', 'Extract only audio', MusicNotesIcon],
                          ] as const).map(([value, label, note, Icon]) => (
                            <label key={value} className={`choice-card ${mode === value ? 'choice-card-active' : ''}`}>
                              <input
                                type="radio"
                                name="mode"
                                value={value}
                                checked={mode === value}
                                onChange={() => {
                                  setMode(value)
                                  setFormatId(probe.formats.find((format) => value === 'audio' ? format.kind === 'audio' : format.kind === 'video')?.format_id ?? '')
                                }}
                                className="sr-only"
                              />
                              <Icon size={20} className={mode === value ? 'text-acid' : 'text-muted'} aria-hidden="true" />
                              <span>
                                <span className="block text-sm font-semibold text-cream">{label}</span>
                                <span className="block text-xs text-muted">{note}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      </fieldset>

                      {mode === 'video' ? (
                        <fieldset className="mt-6">
                          <legend className="field-label">Quality</legend>
                          {pool.length === 0 ? (
                            <p className="mt-2 rounded-[12px] border border-dashed border-ink-line p-4 text-sm text-muted">No video formats available. Try audio instead.</p>
                          ) : (
                            <ul className="scroll-contain mt-2 max-h-64 space-y-1.5 overflow-y-auto pr-1">
                              {pool.map((format) => {
                                const selected = formatId === format.format_id
                                return (
                                  <li key={format.format_id}>
                                    <label className={`quality-row ${selected ? 'quality-row-active' : ''}`}>
                                      <input type="radio" name="format" value={format.format_id} checked={selected} onChange={() => setFormatId(format.format_id)} className="sr-only" />
                                      <span aria-hidden="true" className={`grid size-5 shrink-0 place-items-center rounded-full border ${selected ? 'border-acid bg-acid text-ink' : 'border-muted/45'}`}>
                                        {selected ? <CheckIcon size={11} weight="bold" /> : null}
                                      </span>
                                      <span className="min-w-0 flex-1">
                                        <span className="flex flex-wrap items-center gap-2">
                                          <span className="text-sm font-semibold text-cream tnum">{format.height ? `${format.height}p` : format.label}</span>
                                          {tier(format.height) ? <span className="meta-chip">{tier(format.height)}</span> : null}
                                          {format.fps && format.fps >= 50 ? <span className="text-xs text-muted tnum">{Math.round(format.fps)} fps</span> : null}
                                        </span>
                                        <span className="mt-0.5 block truncate text-xs text-muted">{[format.ext?.toUpperCase(), format.vcodec, bytes(format.filesize)].filter(Boolean).join(' · ')}</span>
                                      </span>
                                    </label>
                                  </li>
                                )
                              })}
                            </ul>
                          )}
                        </fieldset>
                      ) : (
                        <>
                          <fieldset className="mt-6">
                            <legend className="field-label">Audio format</legend>
                            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                              {CODECS.map((item) => {
                                const selected = codec === item.id
                                return (
                                  <label key={item.id} className={`choice-card py-2.5 ${selected ? 'choice-card-active' : ''}`}>
                                    <input type="radio" name="codec" value={item.id} checked={selected} onChange={() => setCodec(item.id)} className="sr-only" />
                                    <span>
                                      <span className="block text-sm font-semibold text-cream">{item.name}</span>
                                      <span className="block text-[11px] text-muted">{item.note}</span>
                                    </span>
                                  </label>
                                )
                              })}
                            </div>
                          </fieldset>
                          <fieldset className="mt-6">
                            <legend className="field-label">Bitrate</legend>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {BITRATES.map((value) => {
                                const selected = bitrate === value && !isLossless
                                return (
                                  <label key={value} className={`bitrate-pill ${isLossless ? 'opacity-40' : selected ? 'bitrate-pill-active' : ''}`}>
                                    <input type="radio" name="bitrate" value={value} checked={selected} disabled={isLossless} onChange={() => setBitrate(value)} className="sr-only" />
                                    <WaveformIcon size={14} aria-hidden="true" />
                                    <span className="tnum">{value} kbps</span>
                                  </label>
                                )
                              })}
                            </div>
                            <p className="mt-2 text-xs text-muted">{isLossless ? 'Lossless formats ignore bitrate.' : '192 kbps is the sensible default for most listening.'}</p>
                          </fieldset>
                        </>
                      )}
                    </>
                  ) : null}

                  <button type="button" onClick={startDownload} disabled={!canDownload} className="button-primary mt-6 w-full py-3.5">
                    <ArrowDownIcon size={18} weight="bold" aria-hidden="true" />
                    Start download
                  </button>
                </div>
              ) : null}
            </section>

            <section className="mt-5 rounded-card border border-ink-line bg-ink-soft p-5 sm:p-6" aria-labelledby="downloads-heading">
              <div className="mb-4 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="eyebrow">Activity</p>
                  <h2 id="downloads-heading" className="mt-1 text-lg font-semibold text-cream">Downloads</h2>
                  {health?.kind === 'local' && health.downloadDir ? (
                    <p className="mt-1 truncate text-xs text-muted" title={health.downloadDir}>Saving locally to {health.downloadDir}</p>
                  ) : null}
                </div>
                <span className="rounded-full bg-ink px-2.5 py-1 text-xs font-semibold text-muted tnum">{jobs.length}</span>
              </div>
              <DownloadList
                jobs={jobs}
                confirmId={confirmId}
                onConfirm={setConfirmId}
                onDelete={deleteJob}
                local={health?.kind === 'local'}
              />
            </section>
          </div>
        </section>
      </main>

      <div aria-live="polite" className="sr-only">{announce}</div>
    </div>
  )
}
