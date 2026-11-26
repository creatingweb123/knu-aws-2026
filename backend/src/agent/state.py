"""그래프 상태 (design §7.1). 6b는 messages·질문·예산 카운터 등을 더한다. 같은 이름을 다른 뜻으로 쓰지 않는다."""

from __future__ import annotations

from typing import Any, TypedDict

LLM_ERROR, INVALID_OUTPUT = "LLM_ERROR", "INVALID_OUTPUT"


class AgentState(TypedDict, total=False):
    story: str
    sources: list[str]                  # 원문 대조 근거: [사연] (6b: + 계획자 답변)
    attempts: int                       # draft 시도 수
    last_failure: str | None            # LLM_ERROR | INVALID_OUTPUT
    llm_error: str | None               # 분류 코드
    invalid_kinds: list[str]            # NOT_JSON | SCHEMA (원문 없음)
    draft_feedback: str | None          # 재시도 메시지(위반 경로·제한만, 응답 원문 없음). BE-Q129
    draft_card: dict[str, Any] | None   # 마지막으로 파싱된 초안 카드(재시도 뒤 JSON이 깨지면 이것을 쓴다)
    candidate: dict[str, Any] | None    # 첫 Candidate_Card
    first_proposal: dict[str, Any] | None  # 한 번만 쓴다
    first_report: dict[str, Any] | None    # 한 번만 쓴다
    card: dict[str, Any] | None         # 작업 카드(장소마다 _src)
    report: dict[str, Any] | None       # 가장 최근 Check_Report
    gate_ok: bool
    degraded: bool
    notes: list[dict[str, Any]]
    masked: list[dict[str, Any]]        # Fallback이 가린 필드 [{src, field}]
    allowed_nis_activities: list[int]   # KEPT_FLAGGED로 허용한 장소의 _src
    final_card: dict[str, Any] | None
    flags: list[dict[str, Any]]
    blocked: list[str]                  # Final_Check 차단 사유
    trace: list[dict[str, str]]         # {tool, summary} (step은 핸들러가 매긴다)
    model_calls: int
    token_in: int
    token_out: int
    token_estimated: bool


class AgentGraphState(AgentState, total=False):
    """6b 에이전트 상태(design §3.3). 6a 필드는 이름·뜻을 그대로 쓰고 더한다. 체크포인트에만 저장된다."""

    mode: str
    messages: list[Any]                 # LangChain 메시지 이력(시스템·사연·도구 호출·ToolMessage)
    answers: list[dict[str, Any]]       # 소비한 답변 {questionId, path, choice|text|skipped, resumeId, privacy}
    questions: list[dict[str, Any]]     # 수락된 질문
    consumed_resume_ids: list[str]      # 그래프가 소비한 resumeId(BE-Q94 표지)
    budget: dict[str, Any]              # 응답 받은 호출 수·검사 수·질문 수·게이트 거부 수·토큰
    outcome: str | None                 # ASKING | WORKING | READY | FAILED
    outcome_turn: int | None            # outcome을 쓴 턴(run_turn)
    route: str | None
    resume_to: str | None
    pause_reason: str | None
    pending_tool: dict[str, Any] | None
    question_view: dict[str, Any] | None
    failure_code: str | None
    work_ready: bool
