"""CLI entrypoint: python -m app.run"""

import socket
import sys

import os

import uvicorn

from app.config import PROJECT_ROOT, get_settings


def _port_available(port: int) -> bool:
    """Check if we can bind the port (another app may already use 8000)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> None:
    settings = get_settings()
    host = settings.app_host
    port = settings.app_port

    if not _port_available(port):
        fallback = 8001 if port == 8000 else port + 1
        print(
            f"\n[!] Port {port} is already in use (often another FastAPI app).\n"
            f"    RevRecover will use http://127.0.0.1:{fallback}/ instead.\n"
            f"    Stop the other process or set APP_PORT in .env.\n",
            file=sys.stderr,
        )
        port = fallback

    os.environ["REVRECOVER_LISTEN_PORT"] = str(port)

    print(f"RevRecover -> http://127.0.0.1:{port}/\n")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=settings.app_debug,
        reload_dirs=[str(PROJECT_ROOT / "app")] if settings.app_debug else None,
        reload_excludes=["*.db", "*.joblib", "data/*"] if settings.app_debug else None,
    )


if __name__ == "__main__":
    main()
