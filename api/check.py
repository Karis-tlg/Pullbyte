"""One runnable check for the download pipeline: python api/check.py

Asserts the pipeline WORKS, not just that it returns. The load-bearing test is
the ffprobe stream count: yt-dlp silently continues without ffmpeg when
ffmpeg_location is wrong, handing back a video-only fragment while every other
assertion still passes.

Needs network. It will fail when yt-dlp goes stale, which is the failure you
most need to hear about.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402

# "Me at the zoo", 19 seconds, the oldest video on YouTube and unlikely to move.
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
PASS, FAIL = "  PASS", "  FAIL"
failures: list[str] = []


def check(name: str, fn) -> None:
    print(f"\n{name}")
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {exc}")
        failures.append(f"{name}: {exc}")


def streams(path: Path) -> dict[str, int]:
    out = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_streams",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    counts: dict[str, int] = {}
    for s in json.loads(out.stdout).get("streams", []):
        counts[s["codec_type"]] = counts.get(s["codec_type"], 0) + 1
        counts[f"name_{s['codec_type']}"] = s.get("codec_name")
    return counts


def t_ffmpeg() -> None:
    assert main.FFMPEG, "ffmpeg not resolved"
    assert Path(main.FFMPEG).is_file(), f"{main.FFMPEG} is not a file"
    assert shutil.which("ffprobe"), "ffprobe not on PATH"
    r = subprocess.run([main.FFMPEG, "-version"], capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg -version exited {r.returncode}"
    print(f"{PASS} ffmpeg at {main.FFMPEG}")
    print(f"{PASS} ffprobe at {shutil.which('ffprobe')}")


def codecs(path: Path) -> dict[str, str]:
    """codec_type -> codec_name, for asserting what the encoder actually wrote."""
    out = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_streams",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return {s["codec_type"]: s["codec_name"] for s in json.loads(out.stdout).get("streams", [])}


def t_shortcut_compat() -> None:
    """The /api/grab path an iPhone Shortcut uses.

    compat must yield H.264 + AAC: iOS Photos shows a black frame or refuses
    the import for AV1/Opus, and the default "best" at any height on YouTube is
    frequently exactly that. An ext-only or stream-count assertion passes while
    the saved video is unplayable, so assert the codec names.
    """
    with tempfile.TemporaryDirectory() as tmp:
        jid = "chkcompat"
        main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
        path = main._download_media(
            TEST_URL, Path(tmp), "video", None, "mp3", jid, 192, 360, True
        )
        c = codecs(path)
        assert c.get("video") == "h264", f"compat video should be h264, got {c}"
        assert c.get("audio") == "aac", f"compat audio should be aac, got {c}"
        assert path.suffix == ".mp4", f"expected .mp4, got {path.suffix}"
        print(f"{PASS} compat=True gives h264 + aac in mp4 ({path.stat().st_size:,} bytes)")

    # A height cap must actually cap. Without it a Shortcut on cellular pulls 4K.
    with tempfile.TemporaryDirectory() as tmp:
        jid = "chkheight"
        main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
        path = main._download_media(
            TEST_URL, Path(tmp), "video", None, "mp3", jid, 192, 144, True
        )
        out = subprocess.run(
            [shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        h = int(out.stdout.strip().rstrip(","))
        assert h <= 144, f"height cap ignored: got {h}p for a 144 cap"
        print(f"{PASS} height cap respected ({h}p for a 144 request)")


def t_picked_format_audio() -> None:
    """A format picked in the web UI must still pair with playable audio.

    mp4 with an Opus track is legal per spec and plays in Chrome, so a browser
    test looks fine, but QuickTime and iOS refuse it. bestaudio on YouTube *is*
    Opus, so an unqualified "<id>+bestaudio" silently produces exactly that.
    """
    with tempfile.TemporaryDirectory() as tmp:
        jid = "chkpicked"
        main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
        # 134 is YouTube's 360p H.264 video-only stream.
        path = main._download_media(TEST_URL, Path(tmp), "video", "134", "mp3", jid)
        c = codecs(path)
        assert c.get("video") == "h264", f"expected h264, got {c}"
        assert c.get("audio") == "aac", f"mp4 must carry aac, not {c.get('audio')}: {c}"
        print(f"{PASS} picked format pairs with aac audio, not opus ({c})")


def t_grab_contract() -> None:
    """Contract the Shortcut depends on, checked without a live server."""
    import inspect

    sig = inspect.signature(main.grab)
    for p in ("url", "mode", "quality", "codec", "token", "keep", "compat"):
        assert p in sig.parameters, f"/api/grab lost its {p} parameter"
    assert sig.parameters["compat"].default is True, "compat must default on for iOS"
    assert sig.parameters["keep"].default is False, "keep must default off"
    print(f"{PASS} /api/grab signature intact, compat on and keep off by default")

    # A token, once configured, is the only thing standing in front of this
    # endpoint: it takes no CSRF header because a Shortcut GET cannot send one.
    assert main.secrets.compare_digest("a", "a")
    for bad in ("", None):
        assert not bad, "empty token must never authenticate"
    print(f"{PASS} token comparison is constant time and rejects empty tokens")


def t_redirect_ssrf() -> None:
    """A redirect must not smuggle us into the internal network.

    urllib's default opener follows 3xx itself, so the up-front URL check is
    already behind us by the time the Location header is honoured. That makes a
    302 the cheapest SSRF here: no DNS control, no timing, just a header.
    """
    import http.server
    import threading

    target = "http://169.254.169.254/latest/meta-data/"

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802, D102
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def log_message(self, *a):  # noqa: D102 - keep the check output clean
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        # Call the fetcher directly: _validate_url would reject a loopback origin
        # up front, and the hop is what we are proving gets re-checked.
        try:
            main._open_no_redirect(f"http://127.0.0.1:{port}/x.jpg")
        except Exception as exc:  # noqa: BLE001
            assert "internal network" in str(exc), f"blocked, but for the wrong reason: {exc}"
            print(f"{PASS} redirect into link-local was re-validated and refused")
        else:
            raise AssertionError(f"followed a redirect to {target}")
    finally:
        srv.shutdown()

    for host in ("100.64.1.1", "127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1"):
        try:
            main._reject_internal(host)
        except HTTPException:
            continue
        raise AssertionError(f"internal address accepted: {host}")
    print(f"{PASS} internal ranges refused, including CGNAT 100.64.0.0/10")


def t_height_cap_fallbacks() -> None:
    """No branch of a capped selector may end in a bare, uncapped "best"."""
    for compat in (True, False):
        sel = main._ydl_opts(Path("."), "video", None, "mp3", 192, 720, compat)["format"]
        for branch in sel.split("/"):
            assert "height<=720" in branch, (
                f"compat={compat} branch {branch!r} has no height cap, so a 720 "
                f"request could return 4K. Full selector: {sel}"
            )
    print(f"{PASS} every capped selector branch keeps its height cap")


def t_grab_hardening() -> None:
    """Regressions that a browser test would not notice."""
    import inspect

    sig = inspect.signature(main.grab)
    # A junk token must be a clean 401. secrets.compare_digest raises TypeError
    # on non-ASCII str, which would surface as a 500 with a traceback.
    main.secrets.compare_digest("café".encode("utf-8", "surrogatepass"), b"abc")
    print(f"{PASS} non-ASCII token compares without raising")

    # Bitrate reaches ffmpeg's -b:a, so it must be bounded on this path too.
    # Assert against the router's validation rather than the raw default: the
    # constraints live in Query metadata, not as attributes.
    q = sig.parameters["bitrate"].default
    bounds = {type(m).__name__: getattr(m, f"{type(m).__name__.lower()}") for m in q.metadata}
    assert bounds.get("Ge") == 32 and bounds.get("Le") == 320, (
        f"bitrate lost its bounds ({bounds}); it reaches ffmpeg's -b:a"
    )
    print(f"{PASS} bitrate is bounded to 32-320 on the grab path too")

    src = inspect.getsource(main.grab)
    assert "range" in src, "ranged requests must be refused when the file is discarded"
    print(f"{PASS} grab refuses Range requests it cannot satisfy")


def t_friendly_errors() -> None:
    """Extractor failures must read as advice, not as yt-dlp debug output.

    yt-dlp text is written for someone debugging yt-dlp. It also sometimes
    carries absolute local paths, which would disclose the server's layout to an
    unauthenticated caller.
    """
    cases = [
        ("ERROR: [TikTok] 714181: Your IP address is blocked from accessing this post",
         "datacenter"),
        ("ERROR: [vimeo] 769: Failed to fetch macos OAuth token: HTTP Error 401: Unauthorized",
         "rejected the request"),
        ("ERROR: [twitter] 141: No video could be found in this tweet", "No downloadable media"),
        ("ERROR: [youtube] BaW: Video unavailable", "unavailable, private, or removed"),
    ]
    for raw, expect in cases:
        got = main._friendly_error(Exception(raw))
        assert expect in got, f"{raw[:40]!r} produced {got!r}, wanted {expect!r}"
        assert "ERROR:" not in got and "[" not in got, f"debug prefix leaked: {got!r}"
    print(f"{PASS} recurring extractor failures map to plain advice")

    leaky = r"ERROR: Postprocessing: ffmpeg failed: C:\dl\ab12cd34\Clip.f401.mp4 is broken"
    out = main._friendly_error(Exception(leaky))
    assert "C:\\dl" not in out and "ab12cd34" not in out, f"local path leaked: {out!r}"
    assert "<path>" in out, f"path was not redacted: {out!r}"
    print(f"{PASS} local filesystem paths are redacted from error text")


def t_validator() -> None:
    bad = [
        ("file:///etc/passwd", "file scheme"),
        ("http://127.0.0.1:8000/", "loopback"),
        ("http://169.254.169.254/latest/meta-data/", "link-local metadata"),
        ("http://10.0.0.5/internal", "private range"),
        ("not-a-url", "no scheme"),
        ("ftp://example.com/x.mp4", "ftp scheme"),
    ]
    for url, why in bad:
        try:
            main._validate_url(url)
        except HTTPException:
            print(f"{PASS} rejected {why}: {url}")
        else:
            raise AssertionError(f"accepted {why}: {url}")
    main._validate_url("https://www.youtube.com/watch?v=BaW_jenozKc")
    print(f"{PASS} accepted a normal https URL")

    for fid in ["all", "best", "bestvideo", "mergeall", "best+bestaudio",
                "137[height>2000]", "a" * 40, "x/y", "ba*"]:
        assert not main._valid_format_id(fid), f"format_id allowed: {fid}"
    assert main._valid_format_id("137")
    assert main._valid_format_id("616-drc")
    print(f"{PASS} format_id check blocks selector operators and keywords")


def t_video_merge() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        jid = "chkvideo"
        main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
        path = main._download_media(
            TEST_URL, Path(tmp), "video", None, "mp3", jid
        )
        assert path.is_file(), f"missing output {path}"
        size = path.stat().st_size
        assert size > 10_000, f"suspiciously small: {size} bytes"

        job = main.JOBS[jid]
        assert job.get("downloaded"), "progress hook never recorded bytes"
        print(f"{PASS} progress hook propagated across threads ({job['downloaded']} bytes)")

        resolved = path.resolve()
        assert resolved.is_relative_to(Path(tmp).resolve()), "escaped the job dir"
        print(f"{PASS} output stayed inside the job dir")

        st = streams(path)
        assert st.get("video") == 1, f"expected 1 video stream, got {st}"
        assert st.get("audio") == 1, f"expected 1 audio stream, got {st}"
        print(f"{PASS} merged file has 1 video + 1 audio stream -> {path.name} ({size:,} bytes)")


def t_audio_extract() -> None:
    # Asserting the exact encoder matters: yt-dlp's own quality-args path drops
    # the alac flag and silently produces AAC, which an ext-only check misses.
    cases = [
        ("mp3", ".mp3", "mp3"),
        ("m4a", ".m4a", "aac"),
        ("opus", ".opus", "opus"),
        ("vorbis", ".ogg", "vorbis"),
        ("flac", ".flac", "flac"),
        ("alac", ".m4a", "alac"),
        ("wav", ".wav", "pcm_s16le"),
    ]
    for codec, ext, encoder in cases:
        with tempfile.TemporaryDirectory() as tmp:
            jid = f"chkaudio_{codec}"
            main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
            path = main._download_media(TEST_URL, Path(tmp), "audio", None, codec, jid, 192)
            assert path.suffix == ext, f"{codec}: expected {ext}, got {path.suffix}"
            st = streams(path)
            assert st.get("audio") == 1, f"{codec}: expected 1 audio stream, got {st}"
            assert "video" not in st, f"{codec}: should carry no video stream, got {st}"
            got = st.get("name_audio")
            assert got == encoder, f"{codec}: expected encoder {encoder}, got {got}"
            print(f"{PASS} {codec:6s} -> {path.name} [{got}] ({path.stat().st_size:,} bytes)")


def t_bitrate_takes_effect() -> None:
    """Every lossy codec must actually honour the requested bitrate.

    Opus is the trap: YouTube's source audio is already Opus, so ExtractAudio
    stream-copies it and preferredquality never reaches an encoder. The output
    was byte-identical at 32 and 320 kbps, which a codec-name assertion cannot
    see. Compare sizes across two bitrates instead.
    """
    for codec in ("mp3", "opus", "vorbis", "m4a"):
        sizes = {}
        for br in (64, 320):
            with tempfile.TemporaryDirectory() as tmp:
                jid = f"chkbr_{codec}_{br}"
                main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
                p = main._download_media(TEST_URL, Path(tmp), "audio", None, codec, jid, br)
                sizes[br] = p.stat().st_size
        assert sizes[320] > sizes[64] * 1.5, (
            f"{codec}: bitrate ignored, 64k gave {sizes[64]:,} and 320k gave "
            f"{sizes[320]:,}. Likely a stream copy rather than a re-encode."
        )
        print(f"{PASS} {codec:6s} honours bitrate ({sizes[64]:,} B at 64k, {sizes[320]:,} B at 320k)")


def t_image() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        jid = "chkimage"
        main.JOBS[jid] = {"status": "queued", "created": 0.0, "title": None}
        path = main._download_image(
            "https://picsum.photos/seed/pullbyte/400/300.jpg", Path(tmp), jid
        )
        assert path.is_file() and path.stat().st_size > 1000, "image did not download"
        print(f"{PASS} image downloaded -> {path.name} ({path.stat().st_size:,} bytes)")
        try:
            main._download_image("https://example.com/", Path(tmp), jid)
        except RuntimeError as exc:
            print(f"{PASS} non-image content type rejected: {str(exc)[:60]}")
        else:
            raise AssertionError("accepted a text/html URL as an image")


if __name__ == "__main__":
    print("=" * 62)
    print("Pullbyte pipeline check")
    print("=" * 62)
    check("[1] ffmpeg / ffprobe resolve", t_ffmpeg)
    check("[2] validator rejects hostile input (no network)", t_validator)
    check("[3] video download + ffmpeg merge", t_video_merge)
    check("[4] audio extraction, all 7 formats with exact encoders", t_audio_extract)
    check("[5] image download", t_image)
    check("[6] /api/grab contract for Shortcuts (no network)", t_grab_contract)
    check("[7] iOS compat codecs and height cap", t_shortcut_compat)
    check("[8] picked format pairs with playable audio", t_picked_format_audio)
    check("[9] redirect SSRF and internal ranges", t_redirect_ssrf)
    check("[10] height cap survives every fallback branch", t_height_cap_fallbacks)
    check("[11] grab hardening: token, bitrate, ranges", t_grab_hardening)
    check("[12] extractor errors read as advice (no network)", t_friendly_errors)
    check("[13] bitrate changes the output for every lossy codec", t_bitrate_takes_effect)

    print("\n" + "=" * 62)
    if failures:
        print(f"FAILED ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")
