"""단위 테스트 전체의 외부 연결 차단 (6a Checkpoint B, Requirement 8.6·8.7).

단위 테스트는 실제 LLM 공급자·AWS에 연결하지 않는다. 소켓 연결 대상이 루프백(로컬 HTTP 스텁)이 아니면
연결을 막고 그 테스트를 실패시킨다. moto는 botocore 단계에서 가로채므로 소켓을 열지 않는다.
"""

from __future__ import annotations

import socket

import pytest

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_blocked: list[str] = []
_current = {"test": "?"}


@pytest.fixture(autouse=True)
def _which_test(request):
    _current["test"] = request.node.nodeid
    yield


@pytest.fixture(autouse=True, scope="session")
def _no_external_sockets():
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def check(address):
        if isinstance(address, tuple) and address[0] not in LOOPBACK:
            _blocked.append(f"{address[0]} ({_current['test']})")
            raise OSError(f"단위 테스트에서 외부 연결 차단: {address[0]}")

    def connect(self, address):
        check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    yield
    socket.socket.connect = real_connect
    socket.socket.connect_ex = real_connect_ex
    assert _blocked == [], f"외부 연결 시도: {sorted(set(_blocked))}"

