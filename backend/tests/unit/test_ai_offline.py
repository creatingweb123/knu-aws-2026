"""단위 테스트의 외부 연결 차단 장치가 동작하는지 (conftest.py, Checkpoint B)."""

import socket

import pytest

from tests.unit import conftest


def test_guard_blocks_external():
    s = socket.socket()
    try:
        with pytest.raises(OSError, match="외부 연결 차단"):
            s.connect(("192.0.2.1", 443))  # TEST-NET-1. 차단 장치가 먼저 막는다
    finally:
        s.close()
    conftest._blocked[:] = [b for b in conftest._blocked if not b.startswith("192.0.2.1 ")]


def test_guard_allows_loopback():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.socket()
    try:
        c.connect(srv.getsockname())
    finally:
        c.close()
        srv.close()
