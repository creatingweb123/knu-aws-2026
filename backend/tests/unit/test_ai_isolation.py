"""AI 의존성 분리 (작업 11.4, Requirement 16.3, 15.9).

다른 함수(Me·Plans·Claims·PreSignUp)는 AI 패키지 없이 import·실행된다. 하위 프로세스에서 AI 패키지 import를 막고 확인한다.
"""

import ast
import json
import pathlib
import subprocess
import sys

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
BLOCKED = ("langgraph", "langchain", "langchain_core", "langchain_openai", "openai", "langsmith", "httpx", "tiktoken")

SCRIPT = r"""
import importlib.abc, json, sys
BLOCKED = %r

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("blocked in test: " + name)
        return None

sys.meta_path.insert(0, Block())
import handlers.plans, handlers.me, handlers.claims, handlers.pre_signup
import domain.ai_metrics, domain.ai_session_service
from domain import ai_metrics

session = {"ownerId": "u", "status": "READY", "agentMode": "PIPELINE", "answers": [], "modelCalls": 1, "privacyDetected": 0,
           "card": {"title": "t", "summary": "s", "reason": "r", "estimatedMinutes": 45, "question": "q",
                    "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": None}]},
           "flags": [], "notes": [], "firstReport": {"notInSource": [], "missing": [], "privacy": []},
           "createdAt": "2026-11-26T00:00:00.000Z", "readyAt": "2026-11-26T00:00:03.000Z"}
final = {"title": "t", "summary": "s", "reason": "r", "estimatedMinutes": 45, "question": "q",
         "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": ""}]}
m = ai_metrics.session_metrics(session, final, "빵집에서 빵 사기", "2026-11-26T00:01:00.000Z")
loaded = sorted({n.split(".")[0] for n in sys.modules} & set(BLOCKED))
print(json.dumps({"metrics": m, "loaded": loaded}, ensure_ascii=False))
""" % (BLOCKED,)


def test_other_handlers_import_and_compute_without_ai_packages():
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=SRC, capture_output=True, text=True, timeout=60,
                         env={"PYTHONPATH": str(SRC), "TABLE_NAME": "HaruTable", "AWS_DEFAULT_REGION": "ap-northeast-2", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["loaded"] == []
    assert result["metrics"]["agentMode"] == "PIPELINE" and result["metrics"]["fieldsEditedAfterHandoff"] == 0


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_non_ai_modules_do_not_import_agent():
    ai_files = {SRC / "handlers" / "ai_card.py", SRC / "handlers" / "ai_agent.py"}  # AiCardFunction 전용(6b: ai_agent 추가)
    for path in [*(SRC / "handlers").glob("*.py"), *(SRC / "domain").glob("*.py"), *(SRC / "common").glob("*.py")]:
        if path in ai_files:
            continue
        names = _imports(path)
        bad = {n for n in names if n.split(".")[0] in ("agent", *BLOCKED)}
        bad |= {n for n in names if n.startswith(("handlers.ai_card", "handlers.ai_agent"))}
        assert bad == set(), f"{path.name}: {bad}"
