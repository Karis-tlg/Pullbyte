from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

PORT = int(os.environ.get("PULLBYTE_HELPER_PORT", "8765"))
OFFICIAL_ORIGIN = "https://karis-tlg.github.io"
DEV_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

os.environ.setdefault("PULLBYTE_HELPER", "1")
os.environ.setdefault("ALLOWED_ORIGINS", f"{OFFICIAL_ORIGIN},{DEV_ORIGINS}")
os.environ.setdefault("DOWNLOAD_DIR", str(Path.home() / "Downloads" / "Pullbyte"))


def main() -> None:
    import uvicorn

    print(f"Pullbyte Helper: http://127.0.0.1:{PORT}")
    print(f"Downloads: {os.environ['DOWNLOAD_DIR']}")
    print("Keep this window open while using Pullbyte in your browser.")
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
