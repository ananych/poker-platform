import socket

import pytest

from app.config import Settings
from app.serve import dual_stack_socket


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        (
            "postgresql://u:p@postgres.railway.internal:5432/railway",
            "postgresql+asyncpg://u:p@postgres.railway.internal:5432/railway",
        ),
        ("postgresql://u@h/db?sslmode=require", "postgresql+asyncpg://u@h/db"),
        ("postgresql+asyncpg://x@/y?host=/tmp", "postgresql+asyncpg://x@/y?host=/tmp"),
    ],
)
def test_database_url_normalized_for_asyncpg(raw, expected):
    assert Settings(database_url=raw).database_url == expected


def test_dual_stack_socket_accepts_ipv4():
    sock = dual_stack_socket(0)
    try:
        sock.listen(1)
        port = sock.getsockname()[1]
        c = socket.create_connection(("127.0.0.1", port), timeout=2)
        c.close()
    finally:
        sock.close()
