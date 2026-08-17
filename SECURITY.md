# Security

Please do not publish a working exploit in a public issue. Report security
problems privately to the repository owner until a dedicated security contact
is published.

Pullbyte processes untrusted URLs and may run yt-dlp and ffmpeg against remote
media. Treat URL validation, redirects, filenames, CORS, localhost access, and
command construction as security-sensitive code.

The local helper must stay loopback-only. Its default browser allow-list contains
only the official GitHub Pages origin and local development origins. Keep the
Origin check, `X-Requested-By` guard, and private-network CORS opt-in together
when changing browser-to-helper networking.

For internet-facing deployments, configure authentication in front of the API,
use TLS, and do not expose the download directory as a general-purpose shared
folder.
