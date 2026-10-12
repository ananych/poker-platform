"""Production entrypoint: one Uvicorn worker on a dual-stack socket.

`uvicorn --host ::` is IPv6-only (asyncio sets IPV6_V6ONLY), which breaks IPv4
health checks; `--host 0.0.0.0` breaks IPv6-only private networks (e.g. legacy
Railway environments). This binds one socket that accepts both.

    python -m app.serve          # honours $PORT (default 8000)
"""

from __future__ import annotations

import os
import socket

import uvicorn


def dual_stack_socket(port: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        sock.bind(("::", port))
    except OSError:  # no IPv6 on this host
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    sock.set_inheritable(True)
    return sock


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(
        "app.main:app",
        workers=1,  # SDD §8: per-room serialization is in-process — never more than one
        proxy_headers=True,
        forwarded_allow_ips="*",
        ws_max_size=65536,
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )
    uvicorn.Server(config).run(sockets=[dual_stack_socket(port)])


if __name__ == "__main__":
    main()
