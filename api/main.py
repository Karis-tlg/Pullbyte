"""Video / audio / image downloader API built on yt-dlp + ffmpeg.

Progress is state, not a stream: workers mutate JOBS and the client polls it.
Dict item assignment is atomic under the GIL, so no lock or queue is needed.
"""
from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from yt_dlp import YoutubeDL

FFMPEG = shutil.which("ffmpeg")
if not FFMPEG:
    raise SystemExit("ffmpeg not found on PATH. Install ffmpeg, then restart.")

# Short root keeps us clear of the Windows 260-char path limit once a job id and
# a long remote title are appended.
ROOT = Path(os.environ.get("DOWNLOAD_DIR") or (r"C:\dl" if os.name == "nt" else "/data"))
ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
MAX_FILESIZE = int(os.environ.get("MAX_FILESIZE", 8 * 1024**3))
MAX_IMAGE = 64 * 1024**2
MIN_FREE_DISK = 2 * 1024**3
CSRF_HEADER = "pullbyte"
# Set API_TOKEN to require ?token= on /api/grab. Mandatory in practice once the
# port is reachable from a phone, since that endpoint takes no CSRF header.
API_TOKEN = os.environ.get("API_TOKEN", "").strip()
GRAB_TIMEOUT = int(os.environ.get("GRAB_TIMEOUT", 600))
if not API_TOKEN:
    # Not fatal: a loopback-only dev run is fine without one. But this service
    # has no other authentication, so anyone who can reach the port can spend
    # your bandwidth and disk once it is published to a LAN or public address.
    print(
        "WARNING: API_TOKEN is not set, so /api/grab is open to anyone who can "
        "reach this port. Set API_TOKEN before binding to anything but 127.0.0.1.",
        flush=True,
    )

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg", ".heic", ".tif", ".tiff"}
# Everything FFmpegExtractAudioPP can target. Lossless codecs ignore the bitrate.
AUDIO_CODECS = ("mp3", "m4a", "aac", "opus", "vorbis", "flac", "alac", "wav")
LOSSLESS = frozenset({"flac", "alac", "wav"})
FORMAT_ID_RE = re.compile(r"[\w.\-]{1,32}")
# Bare words that mean something to yt-dlp's format selector. "all" in
# particular selects every format and would defeat the size caps.
FORMAT_ID_KEYWORDS = frozenset(
    {"all", "best", "worst", "b", "w", "bv", "ba", "wv", "wa", "bestvideo",
     "bestaudio", "worstvideo", "worstaudio", "bv*", "ba*", "b*", "mergeall"}
)


def _valid_format_id(fid: str) -> bool:
    return bool(FORMAT_ID_RE.fullmatch(fid)) and fid.lower() not in FORMAT_ID_KEYWORDS

JOBS: dict[str, dict[str, Any]] = {}
EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="dl")


# --------------------------------------------------------------------------- #
# validation (trust boundary: every field below arrives from the network)
# --------------------------------------------------------------------------- #
def _validate_url(raw: str) -> urllib.parse.ParseResult:
    try:
        u = urllib.parse.urlparse(raw.strip())
    except ValueError:
        raise HTTPException(400, "Could not parse that URL.")
    if u.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http and https URLs are supported.")
    if not u.hostname:
        raise HTTPException(400, "That URL has no host.")
    _reject_internal(u.hostname)
    return u


def _reject_internal(host: str) -> None:
    """Block requests aimed at the host's own network.

    ponytail: TOCTOU-imperfect. A DNS rebind between this check and yt-dlp's own
    resolve would slip through; closing that needs a custom resolver/transport.
    This stops the realistic cases (a pasted 169.254/10.x/localhost address, and
    a redirect into one, which _open_image re-checks per hop).
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(400, f"Could not resolve {host}.")
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        # is_global covers loopback, private, link-local, reserved, multicast and
        # the CGNAT range 100.64.0.0/10, which the individual predicates miss.
        if not ip.is_global:
            raise HTTPException(400, "That address is on an internal network.")


def _safe_name(name: str, fallback: str = "download") -> str:
    name = re.sub(r"[^\w.\- ]", "_", urllib.parse.unquote(name)).strip(" .")
    return name[:80] or fallback


def _looks_like_image(u: urllib.parse.ParseResult) -> bool:
    return Path(u.path).suffix.lower() in IMAGE_EXTS


def _friendly_error(exc: Exception) -> str:
    """Turn a yt-dlp or ffmpeg failure into something a person can act on.

    Raw extractor text is written for someone debugging yt-dlp: it carries an
    "ERROR: [extractor] id:" prefix, sometimes local paths, and internals like
    "Failed to fetch macos OAuth token" that tell an end user nothing. Match the
    cases that actually recur and explain the next step instead.
    """
    raw = str(exc).strip()
    low = raw.lower()
    known = [
        (("ip address is blocked", "blocked from accessing", "http error 403"),
         "That site refused this server's connection. Sites often block datacenter and VPN addresses."),
        (("sign in to confirm", "not a bot", "cookies"),
         "That site wants a signed-in session for this item, which this tool does not have."),
        (("no video could be found", "unsupported url", "no media found"),
         "No downloadable media was found there. Check the link points at a single video, track, or image."),
        (("video unavailable", "is not available", "has been removed", "private video"),
         "That item is unavailable, private, or removed."),
        (("age-restricted", "age restricted"),
         "That item is age restricted, so it cannot be fetched without an account."),
        (("oauth", "unable to download json metadata", "http error 401"),
         "That site rejected the request. Its extractor may be broken right now, or the item needs an account."),
        (("http error 404", "not found"),
         "That link returned Not Found. Check the URL is complete and still live."),
        (("timed out", "timeout", "connection reset", "temporary failure"),
         "The connection to that site timed out. Try again."),
        (("larger than", "max_filesize"),
         "That file is larger than the configured size limit."),
        (("not available in your country", "geo restrict", "geo-restrict"),
         "That item is blocked in this server's region."),
    ]
    for needles, message in known:
        if any(n in low for n in needles):
            return message
    # Fall back to the extractor's own words, minus the debugging prefix and any
    # local path, which would disclose the server's filesystem layout.
    cleaned = re.sub(r"^ERROR:\s*", "", raw)
    cleaned = re.sub(r"^\[[^\]]+\]\s*[^:]{0,60}:\s*", "", cleaned)
    cleaned = re.sub(r"[A-Za-z]:[\\/][^\s\"']+|/(?:home|data|tmp|srv)/[^\s\"']+", "<path>", cleaned)
    cleaned = re.sub(r"\s*\(caused by .*", "", cleaned, flags=re.S).strip()
    return cleaned[:220] or exc.__class__.__name__


# --------------------------------------------------------------------------- #
# yt-dlp
# --------------------------------------------------------------------------- #
def _hooks(jid: str) -> dict[str, Any]:
    def progress(d: dict[str, Any]) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes") or 0
        JOBS[jid] |= {
            "status": "downloading" if d.get("status") == "downloading" else JOBS[jid]["status"],
            "downloaded": done,
            "total": total,
            "percent": round(done / total * 100, 1) if total else None,
            "speed": d.get("speed"),
            "eta": d.get("eta"),
        }

    def postprocess(d: dict[str, Any]) -> None:
        # Without this the UI sits at 100% through a multi-minute merge.
        if d.get("status") in ("started", "processing"):
            JOBS[jid] |= {"status": "processing", "step": d.get("postprocessor")}

    return {"progress_hooks": [progress], "postprocessor_hooks": [postprocess]}


def _ydl_opts(
    job_dir: Path, mode: str, format_id: str | None, codec: str, quality: int,
    height: int | None = None, compat: bool = False,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "paths": {"home": str(job_dir)},
        "outtmpl": "%(title).80B.%(ext)s",
        # The template is ours; only the substituted values come from remote
        # metadata. These three pin filenames to a safe charset and length.
        "windowsfilenames": True,
        "restrictfilenames": True,
        "trim_file_name": 100,
        "ffmpeg_location": FFMPEG,  # never hardcode: WinGet shims are .exe
        "noplaylist": True,
        "playlist_items": "1",
        "max_filesize": MAX_FILESIZE,
        "file_access_retries": 3,
        "progress_delta": 0.5,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
    }
    if mode == "audio":
        opts["format"] = f"{format_id}/bestaudio/best" if format_id else "bestaudio/best"
        pp: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        # A bitrate is meaningless for flac/alac/wav, and for alac it is actively
        # harmful: yt-dlp's _quality_args replaces the whole more_opts list, which
        # is where its "-acodec alac" lives, so the encode silently falls back to
        # AAC. Re-assert the codec through postprocessor_args instead.
        if codec not in LOSSLESS:
            pp["preferredquality"] = str(quality)
        elif codec == "alac":
            opts["postprocessor_args"] = {"extractaudio+ffmpeg": ["-acodec", "alac"]}
        opts["postprocessors"] = [pp]
        if codec == "opus":
            # YouTube's own audio is already Opus, so ExtractAudio stream-copies
            # it and preferredquality never reaches an encoder: the output is
            # byte-identical at 32 and at 320. Force a real re-encode so the
            # requested bitrate means something.
            opts["postprocessor_args"] = {
                "extractaudio+ffmpeg": ["-c:a", "libopus", "-b:a", f"{quality}k"]
            }
    else:
        cap = f"[height<={height}]" if height else ""
        if format_id:
            # Pair a picked video stream with m4a audio first. mp4 carrying Opus
            # is legal but QuickTime and iOS will not play it, and bestaudio on
            # YouTube is Opus, so an unqualified pick yields a file that opens
            # nowhere on Apple devices.
            opts["format"] = (
                f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio[acodec^=mp4a]/"
                f"{format_id}+bestaudio/{format_id}"
            )
        elif compat:
            # Photos on iOS plays H.264 + AAC. YouTube's "best" at a given height
            # is often AV1 or VP9 with Opus, which imports as a black frame or
            # fails outright, so prefer avc1/mp4a first and only then fall back.
            # Every branch keeps the height cap: a bare trailing "best" would let
            # a 144p request come back as 4K over cellular.
            opts["format"] = (
                f"bestvideo{cap}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                f"bestvideo{cap}[ext=mp4]+bestaudio[ext=m4a]/"
                f"best{cap}[ext=mp4]/bestvideo{cap}+bestaudio/best{cap}"
            )
        elif height:
            opts["format"] = f"bestvideo{cap}+bestaudio/best{cap}"
        else:
            opts["format"] = "bestvideo+bestaudio/best"
        opts["merge_output_format"] = "mp4"
        opts["postprocessor_args"] = {"merger+ffmpeg": ["-movflags", "+faststart"]}
    return opts


def _project_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for f in info.get("formats") or []:
        if f.get("format_id") in (None, "") or not _valid_format_id(str(f["format_id"])):
            continue
        vcodec, acodec = f.get("vcodec", "none"), f.get("acodec", "none")
        if vcodec == "none" and acodec == "none":
            continue
        kind = "audio" if vcodec == "none" else "video"
        height = f.get("height")
        key = (kind, height, f.get("ext"), round((f.get("abr") or 0) / 16))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "format_id": str(f["format_id"]),
            "kind": kind,
            "ext": f.get("ext"),
            "height": height,
            "fps": f.get("fps"),
            "abr": f.get("abr"),
            "vcodec": None if vcodec == "none" else vcodec,
            "acodec": None if acodec == "none" else acodec,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "label": f.get("format_note") or (f"{height}p" if height else "audio"),
        })
    out.sort(key=lambda f: (f["kind"] == "audio", -(f["height"] or 0), -(f["abr"] or 0)))
    return out


# --------------------------------------------------------------------------- #
# workers
# --------------------------------------------------------------------------- #
def _download_media(
    url: str, job_dir: Path, mode: str, format_id: str | None, codec: str, jid: str,
    quality: int = 192, height: int | None = None, compat: bool = False,
) -> Path:
    opts = _ydl_opts(job_dir, mode, format_id, codec, quality, height, compat) | _hooks(jid)
    with YoutubeDL(opts) as ydl:
        # Resolve metadata first so a playlist is refused before we spend
        # bandwidth on it, and so the UI has a title while bytes are moving.
        meta = ydl.extract_info(url, download=False, process=False)
        if meta and (meta.get("_type") == "playlist" or meta.get("entries")):
            raise RuntimeError("Playlists are not supported. Use a single item URL.")
        if meta and meta.get("title"):
            JOBS[jid] |= {"title": meta["title"]}
        info = ydl.extract_info(url, download=True)
    if info.get("_type") == "playlist" or info.get("entries"):
        raise RuntimeError("Playlists are not supported. Use a single item URL.")
    if info.get("title"):
        JOBS[jid] |= {"title": info["title"]}
    # requested_downloads carries the authoritative post-processing path; the
    # progress hook's filename is the pre-merge per-format file.
    reqs = info.get("requested_downloads") or []
    if not reqs or not reqs[0].get("filepath"):
        raise RuntimeError("yt-dlp produced no output file.")
    return Path(reqs[0]["filepath"])


def _open_no_redirect(url: str):
    """Fetch, validating every hop rather than letting urllib follow blindly.

    The default opener installs HTTPRedirectHandler, so a 302 to
    http://169.254.169.254/... lands inside the host's own network with the
    up-front _validate_url check already behind us. Redirects are the easy SSRF
    vector here: no DNS control and no timing needed, just a Location header.
    """
    seen = url
    for _ in range(5):
        _validate_url(seen)
        req = urllib.request.Request(seen, headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=30)  # noqa: S310 - scheme validated per hop
        except urllib.error.HTTPError as exc:
            # Returning None from redirect_request makes urllib surface the 3xx
            # as an HTTPError rather than following it. That is the hook: take
            # the Location, validate it as a fresh URL, and loop.
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            location = exc.headers.get("Location")
            exc.close()
            if not location:
                raise RuntimeError("That URL redirected without a destination.")
            seen = urllib.parse.urljoin(seen, location)
            continue
        return resp
    raise RuntimeError("That URL redirected too many times.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None  # hand the 3xx back so the caller can validate the target


def _download_image(url: str, job_dir: Path, jid: str) -> Path:
    """Plain streaming fetch. yt-dlp is not an image downloader: writethumbnail
    needs an extractor-produced thumbnails list, which a bare .jpg URL has not.
    """
    with _open_no_redirect(url) as resp:
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            raise RuntimeError(f"That URL returned {ctype or 'no content type'}, not an image.")
        declared = int(resp.headers.get("Content-Length") or 0)
        if declared > MAX_IMAGE:
            raise RuntimeError("That image is larger than the 64 MB limit.")
        stem = _safe_name(Path(urllib.parse.urlparse(url).path).stem, "image")
        JOBS[jid] |= {"title": JOBS[jid].get("title") or stem}
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if ext not in IMAGE_EXTS:
            ext = mimetypes.guess_extension(ctype) or ".jpg"
        path = job_dir / f"{stem}{ext}"
        read = 0
        with path.open("wb") as fh:
            while chunk := resp.read(262144):
                read += len(chunk)
                if read > MAX_IMAGE:
                    fh.close()
                    path.unlink(missing_ok=True)
                    raise RuntimeError("That image exceeded the 64 MB limit while downloading.")
                fh.write(chunk)
                JOBS[jid] |= {
                    "status": "downloading",
                    "downloaded": read,
                    "total": declared or None,
                    "percent": round(read / declared * 100, 1) if declared else None,
                }
        return path


def _run_job(
    jid: str, url: str, mode: str, format_id: str | None, codec: str, quality: int,
    height: int | None = None, compat: bool = False,
) -> None:
    job_dir = ROOT / jid
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        JOBS[jid] |= {"status": "downloading"}
        if mode == "image":
            path = _download_image(url, job_dir, jid)
        else:
            path = _download_media(
                url, job_dir, mode, format_id, codec, jid, quality, height, compat
            )
        size = path.stat().st_size
        JOBS[jid] |= {
            "status": "done",
            "path": str(path),
            "filename": path.name,
            "size": size,
            "percent": 100.0,
            "step": None,
        }
        # meta.json is the durable record, colocated with the file it describes.
        (job_dir / "meta.json").write_text(
            json.dumps({
                "id": jid, "url": url, "mode": mode, "filename": path.name,
                "size": size, "title": JOBS[jid].get("title"), "created": JOBS[jid]["created"],
            }),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client verbatim
        JOBS[jid] |= {"status": "error", "error": _friendly_error(exc)}
        for junk in job_dir.glob("*.part"):
            junk.unlink(missing_ok=True)
        for junk in job_dir.glob("*.ytdl"):
            junk.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# app
# --------------------------------------------------------------------------- #
def _sweep() -> None:
    """Rebuild history from disk and clear interrupted jobs. The filesystem is
    the database: completed files survive a restart, in-flight ones do not.
    """
    ROOT.mkdir(parents=True, exist_ok=True)
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        meta = d / "meta.json"
        if not meta.is_file():
            shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            JOBS[m["id"]] = {
                "id": m["id"], "url": m["url"], "mode": m.get("mode", "video"),
                "title": m.get("title"), "filename": m["filename"], "size": m["size"],
                "path": str(d / m["filename"]), "status": "done", "percent": 100.0,
                "created": m.get("created", 0), "downloaded": m["size"], "total": m["size"],
                "speed": None, "eta": None, "step": None, "error": None,
            }
        except (OSError, ValueError, KeyError):
            shutil.rmtree(d, ignore_errors=True)


app = FastAPI(title="Pullbyte")
_sweep()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGIN],  # exact origin, never "*": this service has no auth
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Requested-By"],
)


@app.middleware("http")
async def _csrf(request, call_next):
    """No-auth localhost services are drive-able by any page the user visits.
    Requiring a non-simple header forces a preflight that CORS then blocks.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-requested-by") != CSRF_HEADER:
            return JSONResponse({"detail": "Missing X-Requested-By header."}, status_code=403)
    return await call_next(request)


class ProbeIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    mode: Literal["video", "audio", "image"] = "video"
    format_id: str | None = None
    audio_codec: Literal["mp3", "m4a", "aac", "opus", "vorbis", "flac", "alac", "wav"] = "mp3"
    audio_quality: int = Field(default=192, ge=32, le=320)


def _public(job: dict[str, Any]) -> dict[str, Any]:
    # list(...) first: a worker thread finishing a download adds a "path" key to
    # this same dict, and iterating it directly while that happens raises
    # "dictionary changed size during iteration". The window is exactly when the
    # UI polls fastest, so it would surface as an occasional 500 on completion.
    return {k: v for k, v in list(job.items()) if k != "path"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    import yt_dlp

    free = shutil.disk_usage(ROOT).free
    return {
        "ok": True, "ffmpeg": FFMPEG, "yt_dlp": yt_dlp.version.__version__,
        "download_dir": str(ROOT), "free_disk": free, "jobs": len(JOBS),
        "audio_codecs": list(AUDIO_CODECS), "lossless": sorted(LOSSLESS),
    }


@app.post("/api/probe")
def probe(body: ProbeIn) -> dict[str, Any]:
    u = _validate_url(body.url)
    if _looks_like_image(u):
        return {"kind": "image", "url": body.url, "title": Path(u.path).name, "formats": []}
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True, "playlist_items": "1",
        "skip_download": True, "ffmpeg_location": FFMPEG,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(body.url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, _friendly_error(exc))
    if info is None:
        raise HTTPException(422, "Nothing to download at that URL.")
    if info.get("_type") == "playlist" or info.get("entries"):
        raise HTTPException(400, "Playlists are not supported. Use a single item URL.")
    # The full info_dict is routinely 500KB+; send only what the picker needs.
    return {
        "kind": "media",
        "url": body.url,
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "extractor": info.get("extractor_key"),
        "formats": _project_formats(info),
    }


@app.post("/api/jobs", status_code=201)
def create_job(body: JobIn) -> dict[str, Any]:
    _validate_url(body.url)
    if body.format_id is not None and not _valid_format_id(body.format_id):
        # format_id lands in yt-dlp's selector language where +, /, [] are operators.
        raise HTTPException(400, "Invalid format id.")
    if shutil.disk_usage(ROOT).free < MIN_FREE_DISK:
        raise HTTPException(507, "Not enough free disk space.")
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {
        "id": jid, "url": body.url, "mode": body.mode, "title": None,
        "status": "queued", "percent": None, "downloaded": 0, "total": None,
        "speed": None, "eta": None, "step": None, "error": None,
        "filename": None, "size": None, "created": time.time(),
    }
    EXECUTOR.submit(
        _run_job, jid, body.url, body.mode, body.format_id, body.audio_codec, body.audio_quality
    )
    return _public(JOBS[jid])


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    # Snapshot the values before sorting: _discard pops and grab inserts from
    # other threads, which would otherwise change the dict mid-iteration.
    return [_public(j) for j in sorted(list(JOBS.values()), key=lambda j: j["created"], reverse=True)]


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict[str, Any]:
    if jid not in JOBS:
        raise HTTPException(404, "No such job.")
    return _public(JOBS[jid])


@app.get("/api/jobs/{jid}/file")
def get_file(jid: str) -> FileResponse:
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "No such job.")
    if job["status"] != "done":
        # Windows throws a sharing violation if ffmpeg still holds the handle.
        raise HTTPException(409, "That download is not finished yet.")
    path = Path(job["path"]).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise HTTPException(404, "File is gone.")
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    quoted = urllib.parse.quote(path.name)
    return FileResponse(
        path,
        media_type=ctype,
        headers={
            # Without nosniff a remote file named to sniff as HTML/SVG becomes
            # stored XSS on this origin.
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        },
    )


@app.delete("/api/jobs/{jid}", status_code=204)
def delete_job(jid: str) -> None:
    if jid not in JOBS:
        raise HTTPException(404, "No such job.")
    if JOBS[jid]["status"] in ("queued", "downloading", "processing"):
        raise HTTPException(409, "That download is still running.")
    shutil.rmtree(ROOT / jid, ignore_errors=True)
    JOBS.pop(jid, None)


# --------------------------------------------------------------------------- #
# one-shot endpoint for iPhone Shortcuts and other simple clients
# --------------------------------------------------------------------------- #
@app.get("/api/grab")
def grab(
    request: Request,
    url: str,
    mode: Literal["video", "audio", "image"] = "video",
    quality: str = "best",
    codec: Literal["mp3", "m4a", "aac", "opus", "vorbis", "flac", "alac", "wav"] = "mp3",
    bitrate: int = Query(default=192, ge=32, le=320),
    token: str | None = None,
    keep: bool = False,
    compat: bool = True,
) -> FileResponse:
    """Download and return the file in a single blocking request.

    The web UI's probe/create/poll/fetch dance needs four round trips and a
    JSON parser. Shortcuts has neither, so this does the whole thing in one GET
    whose response body is the file: "Get Contents of URL" then "Save File".

        /api/grab?url=<link>&mode=audio&codec=mp3&token=<token>

    quality is a height cap ("1080") or "best". compat defaults on so video
    comes back as H.264/AAC that iOS Photos can actually play; pass compat=0
    to take the highest quality regardless of codec.

    This is a GET with side effects, which the CSRF middleware cannot guard
    (a Shortcut cannot send a custom header), so API_TOKEN is the only thing
    in front of it. Set it before the port is reachable from anywhere.
    """
    if API_TOKEN:
        # Constant-time, but compare_digest raises TypeError on non-ASCII, so
        # encode first: a junk token must be a clean 401, not a 500 traceback.
        supplied = (token or "").encode("utf-8", "surrogatepass")
        if not secrets.compare_digest(supplied, API_TOKEN.encode("utf-8")):
            raise HTTPException(401, "Bad or missing token.")
    elif request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
        # Without a token this endpoint is an open downloader for anyone who can
        # route to the port. Refuse non-local callers rather than serve them.
        raise HTTPException(
            403, "Set API_TOKEN on the server to use /api/grab from another host."
        )

    _validate_url(url)
    if shutil.disk_usage(ROOT).free < MIN_FREE_DISK:
        raise HTTPException(507, "Not enough free disk space.")

    height: int | None = None
    if mode == "video" and quality != "best":
        if not quality.isdigit() or not (144 <= int(quality) <= 4320):
            raise HTTPException(400, "quality must be 'best' or a height between 144 and 4320.")
        height = int(quality)

    # A ranged or HEAD request cannot be served from a file we delete on the way
    # out: the client would get one chunk and then a 404 for the rest, which
    # lands as a silently truncated video. Ask for the whole body instead.
    ranged = "range" in request.headers
    if ranged and not keep:
        raise HTTPException(
            416, "Range requests are not supported here. Request the whole file, or pass keep=1."
        )

    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {
        "id": jid, "url": url, "mode": mode, "title": None, "status": "queued",
        "percent": None, "downloaded": 0, "total": None, "speed": None, "eta": None,
        "step": None, "error": None, "filename": None, "size": None, "created": time.time(),
    }
    future = EXECUTOR.submit(_run_job, jid, url, mode, None, codec, bitrate, height, compat)
    try:
        future.result(timeout=GRAB_TIMEOUT)
    except FuturesTimeout:
        # The worker keeps running and would otherwise leave the job and its
        # directory behind forever. Reap both once it lands.
        EXECUTOR.submit(_reap_after, future, jid)
        raise HTTPException(504, f"Download exceeded {GRAB_TIMEOUT}s. Use the web UI for large files.")

    job = JOBS.get(jid) or {}
    if job.get("status") != "done":
        if not keep:
            _discard(jid)
        raise HTTPException(422, job.get("error") or "Download failed.")

    path = Path(job["path"]).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise HTTPException(500, "Output file went missing.")

    quoted = urllib.parse.quote(path.name)
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        # Default is transfer-and-forget: the phone keeps the file, the server
        # does not accumulate copies. Runs after the body is sent.
        background=None if keep else BackgroundTask(_discard, jid),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        },
    )


def _reap_after(future: Any, jid: str) -> None:
    """Wait out a timed-out grab, then drop its job and files."""
    try:
        future.result(timeout=GRAB_TIMEOUT * 2)
    except Exception:  # noqa: BLE001 - the outcome does not change the cleanup
        pass
    _discard(jid)


def _discard(jid: str) -> None:
    shutil.rmtree(ROOT / jid, ignore_errors=True)
    JOBS.pop(jid, None)


# Static build, when present, is served last so /api wins every route.
WEB = Path(__file__).parent / "web"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
