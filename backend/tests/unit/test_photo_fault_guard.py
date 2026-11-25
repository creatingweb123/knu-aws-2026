"""dev 전용 장애·지연 주입의 세 겹 잠금 (BE-Q59).

1. 런타임 검증(fault_mode): FAULT_INJECT_ALLOWED와 실제 Lambda 함수 이름(AWS_LAMBDA_FUNCTION_NAME)·로컬 STAGE.
2·3. 템플릿 Rules(파라미터)와 FaultAllowed 조건(실제 AWS::StackName)은 template.yaml을 파싱해 평가한다(아래 두 번째 절).

Validates: Requirements 9.4, 9.5
"""

import logging

import pytest

from workers import photo_processor as pp


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for n in ("FAULT_INJECT", "FAULT_INJECT_ALLOWED", "AWS_LAMBDA_FUNCTION_NAME", "STAGE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(pp, "_fault_block_logged", False)


DEV_FN = "haru-dev-PhotoProcessorFunction-AbC123"
DEMO_FN = "haru-demo-PhotoProcessorFunction-AbC123"


@pytest.mark.parametrize("mode", ["photo", "photo-slow"])
@pytest.mark.parametrize(
    "allowed,fn,stage,expect",
    [
        ("true", DEV_FN, None, True),
        ("true", DEMO_FN, None, False),        # Rules를 우회해 demo에 들어가도 런타임이 막는다
        ("true", "haru-devx-Photo-1", None, False),
        ("true", "other-PhotoProcessor", None, False),
        ("false", DEV_FN, None, False),
        (None, DEV_FN, None, False),
        ("true", None, "local", True),         # 로컬(어댑터)
        ("true", None, None, False),
        ("true", DEMO_FN, "local", False),     # Lambda 위에서는 STAGE=local이 있어도 함수 이름이 우선
        ("false", None, "local", False),
    ],
)
def test_runtime_gate(monkeypatch, mode, allowed, fn, stage, expect):
    monkeypatch.setenv("FAULT_INJECT", mode)
    for name, value in (("FAULT_INJECT_ALLOWED", allowed), ("AWS_LAMBDA_FUNCTION_NAME", fn), ("STAGE", stage)):
        if value is not None:
            monkeypatch.setenv(name, value)
    assert pp.fault_mode() == (mode if expect else "")


def test_unknown_or_empty_value_is_off(monkeypatch):
    monkeypatch.setenv("FAULT_INJECT_ALLOWED", "true")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", DEV_FN)
    for v in ("", "PHOTO", "slow", "photo-slower"):
        monkeypatch.setenv("FAULT_INJECT", v)
        assert pp.fault_mode() == ""


def test_blocked_logs_once(monkeypatch, caplog):
    monkeypatch.setenv("FAULT_INJECT", "photo")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", DEMO_FN)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert pp.fault_mode() == ""
    assert caplog.text.count("fault_inject_blocked") == 1
