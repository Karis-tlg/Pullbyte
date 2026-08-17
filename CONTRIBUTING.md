# Contributing to Pullbyte

Pullbyte is intentionally small. Before adding code, check whether the existing
engine contract, browser platform, or standard library already solves the need.

## Development

```bash
cd web
npm ci
npm run dev
```

The web app talks to the FastAPI backend by default. For a static preview:

```bash
BUILD_TARGET=pages NEXT_PUBLIC_ENGINE=demo npm run build
```

Before opening a pull request, run:

```bash
npm run typecheck
npm run build
```

Backend changes should also run `python -m py_compile api/main.py api/check.py`.
The full `python api/check.py` suite needs ffmpeg, ffprobe, yt-dlp, and network
access.

## Pull requests

Keep changes focused. Explain the user-visible problem, the root cause, and how
you verified the fix. Avoid unrelated refactors and new dependencies unless
they remove more complexity than they add.
