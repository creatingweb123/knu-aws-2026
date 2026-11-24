"""API 경로 목록. template.yaml의 이벤트 경로와 로컬 어댑터가 이 목록 하나를 기준으로 맞춘다(요구사항 13.9).

키는 HTTP API routeKey(`METHOD /path`), 값은 Lambda 핸들러(`모듈.함수`, CodeUri=src 기준)다.
이번 범위(1·2단계)의 경로만 둔다. 클레임·AI·수신함 경로는 넣지 않는다(요구사항 12.8).
"""

ROUTES: dict[str, str] = {
    "GET /me": "handlers.me.handler",
    "POST /plans": "handlers.plans.handler",
    "GET /plans": "handlers.plans.handler",
    "GET /plans/{planId}": "handlers.plans.handler",
}
