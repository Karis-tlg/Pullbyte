# Pullbyte

A local-first media downloader interface. Paste a link, choose the output, and
hand the heavy work to the download engine you trust.

Pullbyte is being developed web-first: the UI is a static Next.js export that can
live on GitHub Pages, while download engines remain replaceable. The repository
also contains the existing FastAPI + yt-dlp + ffmpeg engine, which is useful for
local development today and can become the remote/VPS engine later.

> **Project status:** the GitHub Pages build runs in an explicit preview mode.
> It simulates probe/download progress so the full UX can be developed and
> reviewed without pretending that a browser-only yt-dlp engine exists. Real
> downloads use the FastAPI engine for now. A localhost helper is a later
> milestone.

## Why Pullbyte

- **Static web first.** The frontend can be hosted on GitHub Pages with no Node
  server and no media bandwidth on the host.
- **Engine boundary.** UI code talks to a small downloader contract instead of
  hard-coding FastAPI requests throughout the page.
- **Honest preview mode.** The public static build says when work is simulated.
- **Existing pipeline preserved.** yt-dlp/ffmpeg format selection, audio
  conversion, image downloads, and the iPhone Shortcut endpoint remain usable.
- **Small dependency surface.** React, Next.js, Tailwind, and Phosphor icons on
  the web; FastAPI, yt-dlp, and ffmpeg on the engine.

## Architecture

```text
GitHub Pages / static export
          |
          v
      Pullbyte Web
          |
          v
   DownloaderEngine
      /        \
 DemoEngine   ApiEngine
                |
                v
         FastAPI / VPS
                |
          yt-dlp + ffmpeg
```

The future localhost helper should implement the same web-facing behavior. It
is deliberately not scaffolded yet; the current contract is enough to build and
validate the web product without inventing a second backend before it is needed.

## Repository layout

```text
.
├── .github/workflows/pages.yml  # web CI + GitHub Pages deploy
├── api/
│   ├── main.py                  # FastAPI downloader engine
│   └── check.py                 # integration/regression checks
├── web/
│   ├── app/                     # Next.js UI
│   └── lib/downloader.ts        # engine contract + API/demo engines
├── Dockerfile
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

## Web development

Prerequisites: Node.js 22+.

```bash
cd web
npm ci
npm run dev
```

By default the development server rewrites `/api/*` to
`http://127.0.0.1:8000`. Override it when needed:

```bash
API_ORIGIN=http://192.0.2.10:8000 npm run dev
```

Useful checks:

```bash
npm run typecheck
npm run build
```

### Static preview

The Pages build uses the demo engine:

```bash
BUILD_TARGET=pages NEXT_PUBLIC_ENGINE=demo npm run build
```

Output is written to `web/out/`.

The demo engine validates the link shape, returns representative media formats,
and drives the real queue/progress UI. It never downloads media and never
creates a fake file.

### Connect a remote API later

The same frontend can be built against a real API engine:

```bash
BUILD_TARGET=pages \
NEXT_PUBLIC_ENGINE=api \
NEXT_PUBLIC_API_BASE_URL=https://downloads.example.com \
npm run build
```

The FastAPI server must then allow the exact GitHub Pages/custom-domain origin
through `ALLOWED_ORIGIN`.

## GitHub Pages

`.github/workflows/pages.yml` runs on pull requests and on `main`:

1. install dependencies with `npm ci`;
2. run TypeScript type checking;
3. build the static export with the demo engine;
4. deploy `web/out` on non-PR runs.

The Next.js config derives the project-site base path from
`GITHUB_REPOSITORY`, so a repository such as `owner/pullbyte` works at
`https://owner.github.io/pullbyte/` without a hard-coded repository name.

After creating the GitHub repository, set **Settings → Pages → Source** to
**GitHub Actions**.

## FastAPI engine

Prerequisites:

- Python 3.13+
- ffmpeg + ffprobe on `PATH`
- dependencies from `requirements.txt`

Start it locally:

```bash
pip install -r requirements.txt
python -m uvicorn api.main:app --port 8000
```

Then run the web dev server in another terminal.

### What the engine does

- video/audio extraction with yt-dlp;
- ffmpeg merge/transcode;
- MP4 `+faststart` output;
- MP3, M4A, Opus, Vorbis, FLAC, ALAC, and WAV audio outputs;
- direct image streaming with a 64 MB cap and content-type validation;
- in-memory active jobs plus completed-job metadata on disk;
- H.264 + AAC compatibility mode for the one-shot iPhone endpoint.

At most three downloads execute concurrently. Completed jobs are persisted as
`<DOWNLOAD_DIR>/<job-id>/meta.json`.

## Backend checks

Syntax-only check:

```bash
python -m py_compile api/main.py api/check.py
```

Full integration suite:

```bash
python api/check.py
```

The full suite needs ffmpeg, ffprobe, yt-dlp, and network access. It checks the
real merge/transcode pipeline, codecs, bitrate behavior, URL/selector hardening,
image handling, iOS-compatible output, and `/api/grab` behavior.

## iPhone Shortcut endpoint

`GET /api/grab` performs a blocking one-shot download and returns the file in
one response:

```text
GET /api/grab?url=<encoded-url>&token=<token>
```

Important parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `url` | required | Media URL |
| `mode` | `video` | `video`, `audio`, or `image` |
| `quality` | `best` | height cap such as `720` or `1080` |
| `codec` | `mp3` | audio output codec |
| `bitrate` | `192` | lossy audio bitrate |
| `compat` | `1` | prefer H.264 + AAC for iOS |
| `keep` | `0` | delete server copy after response |
| `token` | conditional | shared secret when `API_TOKEN` is configured |

Without `API_TOKEN`, `/api/grab` only accepts loopback callers. For any
internet-facing deployment, use TLS and authentication; do not publish the raw
FastAPI port as an anonymous downloader.

## Docker

The Docker image builds the same web UI with the API engine and serves the
static export from FastAPI:

```bash
docker build -t pullbyte .
docker run --rm -p 8000:8000 -v pullbyte-data:/data pullbyte
```

For an exposed deployment, configure a token:

```bash
docker run --rm -p 8000:8000 \
  -v pullbyte-data:/data \
  -e API_TOKEN=<token> \
  pullbyte
```

Open `http://localhost:8000`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `C:\dl` on Windows, `/data` elsewhere | app-owned download root |
| `ALLOWED_ORIGIN` | `http://localhost:3000` | exact browser origin allowed by CORS |
| `MAX_FILESIZE` | 8 GiB | yt-dlp per-download cap |
| `API_TOKEN` | empty | shared secret for `/api/grab` |
| `GRAB_TIMEOUT` | `600` | `/api/grab` timeout in seconds |
| `NEXT_PUBLIC_ENGINE` | `api` unless set | frontend engine: `api` or `demo` |
| `NEXT_PUBLIC_API_BASE_URL` | empty | cross-origin API base URL |
| `BUILD_TARGET` | `dev` | `dev`, `pages`, or `api` |

`DOWNLOAD_DIR` is a **Pullbyte-owned database root**, not a general shared
folder. Startup cleanup removes subdirectories that are not valid completed job
directories.

## Current limits

- Playlists are intentionally unsupported.
- Active jobs do not survive an engine restart.
- The FastAPI job API has no user accounts or multi-tenancy.
- Running jobs cannot yet be cancelled through the current backend.
- The static Pages preview does not download real media.
- A localhost helper is planned, not implemented.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Small, focused changes are preferred.
Security-sensitive changes should also read [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

Only download content you have the rights or permission to download.
