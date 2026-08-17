# Security

Please do not publish a working exploit in a public issue. Report security
problems privately to the repository owner until a dedicated security contact
is published.

Pullbyte processes untrusted URLs and may run yt-dlp and ffmpeg against remote
media. Treat URL validation, redirects, filenames, CORS, localhost access, and
command construction as security-sensitive code.

For internet-facing deployments, configure authentication in front of the API,
use TLS, and do not expose the download directory as a general-purpose shared
folder.
