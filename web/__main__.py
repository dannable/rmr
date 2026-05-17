"""`python -m web` — runs uvicorn for both dev and prod.

In dev, omits proxy-header trust and enables --reload. In prod (i.e. when
RELOAD is unset/false), trusts X-Forwarded-* from FORWARDED_ALLOW_IPS so the
session cookie's secure flag matches the original https scheme that ravenloft
terminated.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    # Comma-separated IPs/hostnames whose X-Forwarded-* headers we trust.
    # 127.0.0.1 covers a local reverse proxy; in our setup we want ravenloft's
    # source IP here so the proxy-terminated https scheme is honored.
    forwarded = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

    uvicorn.run(
        "web.main:app",
        host=host,
        port=port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=forwarded,
    )


if __name__ == "__main__":
    main()
