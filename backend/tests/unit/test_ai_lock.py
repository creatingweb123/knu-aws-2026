"""AiCardFunction 의존성 잠금 파일 규칙 (Requirement 16.1, 16.2, 16.5)."""

import re
from pathlib import Path

SRC = Path(__file__).parents[2] / "src"
AI_PACKAGES = ("langgraph", "langchain", "langsmith", "openai", "tiktoken", "httpx", "httpcore", "ormsgpack", "xxhash", "zstandard", "jiter", "orjson")


def _reqs(path: Path) -> dict[str, str]:
    """{패키지(소문자): 버전 지정}. 주석·해시 줄·이어 쓰기는 건너뛴다."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().rstrip("\\").strip()
        if not line or line.startswith("--"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*(.*)$", line)
        out[m.group(1).lower().split("[")[0]] = m.group(2).strip()
    return out


def test_every_locked_package_is_pinned_with_hashes():
    text = (SRC / "ai-requirements.lock").read_text(encoding="utf-8")
    pkgs = _reqs(SRC / "ai-requirements.lock")
    assert pkgs and all(spec.startswith("==") for spec in pkgs.values()), {k: v for k, v in pkgs.items() if not v.startswith("==")}
    blocks = re.split(r"\n(?=[a-z0-9])", text.split("\n", 3)[-1])
    for block in blocks:
        if re.match(r"^[a-z0-9]", block):
            assert "--hash=sha256:" in block, block.splitlines()[0]


def test_direct_dependencies_are_in_lock():
    locked = _reqs(SRC / "ai-requirements.lock")
    for name, spec in _reqs(SRC / "ai-requirements.in").items():
        assert name in locked, name
        if spec.startswith("=="):
            assert locked[name] == spec, (name, locked[name], spec)


def test_shared_versions_match_src_requirements():
    common = _reqs(SRC / "requirements.txt")
    locked = _reqs(SRC / "ai-requirements.lock")
    for name in ("pydantic", "python-ulid"):
        assert locked[name] == common[name], name


def test_other_functions_requirements_have_no_ai_packages():
    common = _reqs(SRC / "requirements.txt")
    assert not [n for n in common if n.startswith(AI_PACKAGES)]
