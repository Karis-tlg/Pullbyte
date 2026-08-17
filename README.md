# Pullbyte

A local-first media downloader interface. Paste a link, choose the output, and
hand the heavy work to the download engine you trust.

Pullbyte is being developed web-first: the UI is a static Next.js export that can
live on GitHub Pages, while download engines remain replaceable. The repository
also contains the existing FastAPI + yt-dlp + ffmpeg engine, which is useful for
local development today and can become the remote/VPS engine later.

> **Project status:** GitHub Pages hosts only the static interface. Real downloads
> run through Pullbyte Helper on the user's own computer. No VPS is required for
> the local flow; an optional remote API remains supported as a fallback.

## Why Pullbyte

- **Static web first.** The frontend can be hosted on GitHub Pages with no Node
  server and no media bandwidth on the host.
- **Local compute.** The web UI automatically looks for Pullbyte Helper on
  `http://localhost:8765`; yt-dlp and ffmpeg run on the user's computer.
- **Engine boundary.** UI code talks to a small downloader contract instead of
  hard-coding FastAPI requests throughout the page.
- **No fake completion states.** The UI only enables downloads when a real engine is connected.
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
          +--> http://localhost:8765
          |       Pullbyte Helper
          |       yt-dlp + ffmpeg
          |       user CPU / disk / network
          |
          `--> optional remote API / VPS
```

The web always tries the loopback helper first. A remote API is only a fallback
when `NEXT_PUBLIC_API_BASE_URL` is configured. The helper binds to loopback only
and accepts the official Pages origin plus local development origins by default.

## Repository layout

```text
.
├── .github/workflows/pages.yml  # web CI + GitHub Pages deploy
├── api/
│   ├── main.py                  # shared FastAPI downloader engine
│   └── check.py                 # integration/regression checks
├── helper/
│   ├── run.py                   # loopback-only local helper entrypoint
│   ├── install-windows.ps1      # Windows installer + pullbyte:// launcher
│   └── start-unix.sh            # macOS/Linux helper launcher
├── web/
│   ├── app/                     # Next.js UI
│   └── lib/downloader.ts        # engine contract + API engine
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

### Static Pages build

Build the web app for GitHub Pages with:

```bash
BUILD_TARGET=pages npm run build
```

Output is written to `web/out/`. No API URL is required for the normal local
flow: the browser automatically probes `http://localhost:8765` and
`http://127.0.0.1:8765`. If the helper is not running, the UI stays offline
instead of creating fake completed jobs.

## Local helper

The hosted web UI cannot execute native yt-dlp or ffmpeg by itself. Pullbyte
therefore uses a small loopback helper that runs on the user's own machine. The
helper listens only on `127.0.0.1:8765`; GitHub Pages automatically detects it.

### Windows

Download `helper/install-windows.ps1` from this repository and run it with
PowerShell. The installer:

1. installs Python 3.13 and ffmpeg through winget when they are missing;
2. installs Pullbyte under `%LOCALAPPDATA%\Pullbyte`;
3. creates an isolated Python environment and installs `requirements.txt`;
4. registers `pullbyte://start` for the **Start helper** button on the website;
5. starts the helper.

The helper stores completed jobs under `%USERPROFILE%\Downloads\Pullbyte` by
default. Keep the helper window open while downloading. Re-running the installer
updates the local source from `main`.

### macOS / Linux

With Python 3 and ffmpeg installed:

```bash
./helper/start-unix.sh
```

This creates `.helper-venv`, installs the pinned Python dependencies, and starts
the helper on loopback. Downloads default to `~/Downloads/Pullbyte`.

### Browser permission

Modern browsers may ask whether the Pullbyte Pages origin can access devices or
services on the local network. Allow that permission for Pullbyte so the page can
reach the loopback helper. The helper also validates the browser `Origin` and
keeps the existing `X-Requested-By` CSRF guard.

### Connect a remote API

Point the static frontend at a real Pullbyte API:

```bash
BUILD_TARGET=pages \
NEXT_PUBLIC_API_BASE_URL=https://downloads.example.com \
npm run build
```

For GitHub Pages, set the repository variable `NEXT_PUBLIC_API_BASE_URL` to the
HTTPS API origin. The FastAPI server must allow the exact GitHub Pages/custom-
domain origin through `ALLOWED_ORIGIN`.

## GitHub Pages

`.github/workflows/pages.yml` runs on pull requests and on `main`:

1. install dependencies with `npm ci`;
2. run TypeScript type checking;
3. build the static export;
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
| `DOWNLOAD_DIR` | helper: `~/Downloads/Pullbyte`; server: `C:\dl` or `/data` | app-owned download root |
| `ALLOWED_ORIGINS` | helper: official Pages + localhost dev origins | comma-separated exact browser origins |
| `ALLOWED_ORIGIN` | `http://localhost:3000` | legacy single-origin server setting |
| `PULLBYTE_HELPER` | empty | `1` enables loopback-helper defaults |
| `PULLBYTE_HELPER_PORT` | `8765` | helper listen port |
| `MAX_FILESIZE` | 8 GiB | yt-dlp per-download cap |
| `API_TOKEN` | empty | shared secret for `/api/grab` |
| `GRAB_TIMEOUT` | `600` | `/api/grab` timeout in seconds |
| `NEXT_PUBLIC_LOCAL_HELPER_PORT` | `8765` | local helper port baked into the web build |
| `NEXT_PUBLIC_API_BASE_URL` | empty | optional remote API fallback |
| `BUILD_TARGET` | `dev` | `dev`, `pages`, or `api` |

`DOWNLOAD_DIR` is a **Pullbyte-owned database root**, not a general shared
folder. Startup cleanup removes subdirectories that are not valid completed job
directories.

## Current limits

- Playlists are intentionally unsupported.
- Active jobs do not survive an engine restart.
- The FastAPI job API has no user accounts or multi-tenancy.
- Running jobs cannot yet be cancelled through the current backend.
- Static Pages requires the local helper or an optional configured remote API.
- The browser cannot start native yt-dlp/ffmpeg until the helper has been installed once.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Small, focused changes are preferred.
Security-sensitive changes should also read [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

Only download content you have the rights or permission to download.
