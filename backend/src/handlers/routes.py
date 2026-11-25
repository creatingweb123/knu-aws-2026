"""API 경로 목록. template.yaml의 이벤트 경로와 로컬 어댑터가 이 목록 하나를 기준으로 맞춘다(요구사항(1·2단계) 13.9).

키는 HTTP API routeKey(`METHOD /path`), 값은 Lambda 핸들러(`모듈.함수`, CodeUri=src 기준)다.
지금까지 구현한 경로만 둔다(1–3단계와 4단계 수신함). `GET /claims/{claimId}/record`는 BE-Q46(계약 변경 승인 대기) 묶음, AI는 6단계.
"""

ROUTES: dict[str, str] = {
    "GET /me": "handlers.me.handler",
    "GET /me/claims": "handlers.me.handler",
    "POST /plans": "handlers.plans.handler",
    "GET /plans": "handlers.plans.handler",
    "GET /plans/{planId}": "handlers.plans.handler",
    "POST /plans/{planId}/claims": "handlers.plans.handler",
    "POST /claims/{claimId}/abandon": "handlers.claims.handler",
    "PUT /claims/{claimId}/record": "handlers.claims.handler",
    "POST /claims/{claimId}/complete": "handlers.claims.handler",
    "GET /inbox": "handlers.inbox.handler",
    "GET /inbox/{itemId}": "handlers.inbox.handler",
    "POST /inbox/{itemId}/read": "handlers.inbox.handler",
    "POST /inbox/{itemId}/reply": "handlers.inbox.handler",
}
