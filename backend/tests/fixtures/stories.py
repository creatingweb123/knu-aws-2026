"""합성 사연 픽스처와 자동 답 규칙 (T18–T22, 오프라인 평가 공통, design §20.4·§21).

자동 답 규칙(결과 파일에 그대로 적는다):
1. 사연 픽스처의 `answers`에 질문 `path`가 있으면 그 값(`choice`·`text`·`skipped`)을 쓴다.
   `choice`가 선택지에 없거나 `text`인데 자유 입력이 막혀 있으면 건너뛴다.
2. 없으면 건너뛴다(`skipped`). 모델이 고른 첫 선택지를 고르지 않는다(답이 결과를 이끌지 않게).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

PATH = pathlib.Path(__file__).with_name("stories.json")
AUTO_ANSWER_RULE = "픽스처 answers[path] 사용(선택지 밖 choice·자유 입력 불가 text는 skipped), 없으면 skipped"


def load_stories() -> list[dict[str, Any]]:
    return json.loads(PATH.read_text(encoding="utf-8"))["stories"]


def story(story_id: str) -> dict[str, Any]:
    return next(s for s in load_stories() if s["id"] == story_id)


def auto_answer(question: dict[str, Any], answers: dict[str, Any] | None) -> dict[str, Any]:
    """SessionView.question(또는 interrupt 페이로드)에 대한 답. questionId는 그대로 붙인다."""
    qid = question["questionId"]
    want = dict((answers or {}).get(question.get("path") or "", {}))
    if "choice" in want and want["choice"] in (question.get("options") or []):
        return {"questionId": qid, "choice": want["choice"]}
    if "text" in want and question.get("allowFreeText") and 1 <= len(want["text"]) <= 100:
        return {"questionId": qid, "text": want["text"]}
    return {"questionId": qid, "skipped": True}
