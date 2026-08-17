# Contributing to Pullbyte

Pullbyte is intentionally small. Before adding code, check whether the existing
engine contract, browser platform, or standard library already solves the need.

## Development

```bash
cd web
npm ci
npm run dev
```

The web app probes Pullbyte Helper on `localhost:8765` first. Start the helper
from another terminal when working on the full local flow:

```bash
./helper/start-unix.sh
```

To verify the static Pages build:

```bash
BUILD_TARGET=pages npm run build
```

The static build contains no native downloader; yt-dlp and ffmpeg run in the
loopback helper. `NEXT_PUBLIC_API_BASE_URL` is optional and only configures a
remote fallback. Use `NEXT_PUBLIC_LOCAL_HELPER_PORT` to point a test build at a
non-default helper port.

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
