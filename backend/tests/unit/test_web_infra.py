"""7단계 정적 확인: 웹 버킷·CloudFront(OAC)·CORS 연동·알람·대시보드·Budgets (BE-INFRA-02–04, BE-OBS-01–03, BE-NFR-06).

배포하지 않고 template.yaml만 읽는다. 실제 CloudFront·알람·대시보드 동작은 AWS 스택에서 확인한다(AWS 인계 문서).
"""

import json
import re
from pathlib import Path

import pytest

from tests.unit.test_template import ALLOWED_ORIGINS_WITH_WEB, BACKEND, http_api_cors, template  # noqa: F401  (template은 fixture)

SRC = BACKEND / "src"


def res(template, name):
    return template["Resources"][name]


# ------------------------------------------------------------------ 순환 참조 없음


def _refs(node):
    """노드 안의 논리 ID 참조(!Ref, !GetAtt, !Sub ${X}, !Sub ${X.Attr}, DependsOn)."""
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "!Ref" and isinstance(v, str):
                out.add(v)
            elif k == "!GetAtt":
                out.add((v if isinstance(v, str) else v[0]).split(".")[0])
            elif k == "!Sub":
                text = v if isinstance(v, str) else v[0]
                out |= {m.split(".")[0] for m in re.findall(r"\$\{([^}!]+)\}", text)}
            elif k == "DependsOn":
                out |= set([v] if isinstance(v, str) else v)
            out |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            out |= _refs(v)
    return out


def test_no_circular_dependencies(template):
    names = set(template["Resources"])
    graph = {n: {r for r in _refs(body) if r in names and r != n} for n, body in template["Resources"].items()}
    # SAM이 만드는 암묵 리소스(HttpApi 권한·스테이지 등)는 함수·HttpApi 사이에서만 생기고 아래 검사 대상 밖이다.
    state: dict[str, int] = {}

    def visit(n, path):
        if state.get(n) == 1:
            pytest.fail("순환: " + " -> ".join(path + [n]))
        if state.get(n) == 2:
            return
        state[n] = 1
        for m in sorted(graph[n]):
            visit(m, path + [n])
        state[n] = 2

    for n in graph:
        visit(n, [])


def test_web_distribution_does_not_depend_on_cors_consumers(template):
    deps = _refs(res(template, "WebDistribution"))
    assert deps <= {"WebBucket", "WebOriginAccessControl", "AWS::StackName"}  # API·사진 버킷을 참조하면 CORS와 순환한다


# ------------------------------------------------------------------ 웹 버킷·CloudFront


def test_web_bucket_private_encrypted(template):
    p = res(template, "WebBucket")["Properties"]
    assert p["PublicAccessBlockConfiguration"] == {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}
    assert p["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    assert p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"] == {"SSEAlgorithm": "AES256"}
    assert "WebsiteConfiguration" not in p  # 정적 웹사이트 호스팅(공개 엔드포인트)을 쓰지 않는다
    assert "NotificationConfiguration" not in p and "CorsConfiguration" not in p


def test_web_bucket_policy_only_cloudfront_and_tls(template):
    stmts = res(template, "WebBucketPolicy")["Properties"]["PolicyDocument"]["Statement"]
    tls = next(s for s in stmts if s["Sid"] == "DenyInsecureTransport")
    assert tls["Effect"] == "Deny" and tls["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    allow = [s for s in stmts if s["Effect"] == "Allow"]
    assert len(allow) == 1
    a = allow[0]
    assert a["Principal"] == {"Service": "cloudfront.amazonaws.com"} and a["Action"] == "s3:GetObject"
    assert a["Condition"]["StringEquals"]["AWS:SourceArn"]["!Sub"].endswith(":distribution/${WebDistribution}")
    assert a["Principal"] != "*"


def test_distribution_oac_https_spa(template):
    cfg = res(template, "WebDistribution")["Properties"]["DistributionConfig"]
    (origin,) = cfg["Origins"]
    assert origin["OriginAccessControlId"] == {"!GetAtt": "WebOriginAccessControl.Id"}
    assert origin["S3OriginConfig"] == {"OriginAccessIdentity": ""}  # OAI 아님
    assert origin["DomainName"] == {"!GetAtt": "WebBucket.RegionalDomainName"}  # 정적 웹사이트 엔드포인트 아님
    oac = res(template, "WebOriginAccessControl")["Properties"]["OriginAccessControlConfig"]
    assert (oac["OriginAccessControlOriginType"], oac["SigningBehavior"], oac["SigningProtocol"]) == ("s3", "always", "sigv4")
    assert cfg["DefaultRootObject"] == "index.html" and cfg["Enabled"] is True
    for b in [cfg["DefaultCacheBehavior"], *cfg["CacheBehaviors"]]:
        assert b["ViewerProtocolPolicy"] == "redirect-to-https"  # HTTPS 강제
        assert set(b["AllowedMethods"]) == {"GET", "HEAD"}
    errors = {e["ErrorCode"]: e for e in cfg["CustomErrorResponses"]}
    for code in (403, 404):  # SPA 라우팅(BE-INFRA-02)
        assert errors[code]["ResponseCode"] == 200 and errors[code]["ResponsePagePath"] == "/index.html" and errors[code]["ErrorCachingMinTTL"] == 0


def test_cache_policies_split_index_and_assets(template):
    cfg = res(template, "WebDistribution")["Properties"]["DistributionConfig"]
    CACHING_DISABLED, CACHING_OPTIMIZED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad", "658327ea-f89d-4fab-a63d-7e88639e58f6"
    assert cfg["DefaultCacheBehavior"]["CachePolicyId"] == CACHING_DISABLED  # index.html은 항상 새로
    (assets,) = cfg["CacheBehaviors"]
    assert assets["PathPattern"] == "/assets/*" and assets["CachePolicyId"] == CACHING_OPTIMIZED
    # Managed-SecurityHeadersPolicy. 2026-11-27 AWS 배포에서 다른 ID(…-48c1-86a6-d8d6b5fc7a49)는 404로 롤백됐다
    SECURITY_HEADERS = "67f7725c-6f97-4210-82d7-5512b31e9d03"
    assert cfg["DefaultCacheBehavior"]["ResponseHeadersPolicyId"] == SECURITY_HEADERS
    assert assets["ResponseHeadersPolicyId"] == SECURITY_HEADERS


def test_cors_uses_web_domain_in_api_and_photo_bucket(template):
    assert http_api_cors(template)["allowOrigins"] == ALLOWED_ORIGINS_WITH_WEB
    (rule,) = res(template, "PhotoBucket")["Properties"]["CorsConfiguration"]["CorsRules"]
    assert rule["AllowedOrigins"] == ALLOWED_ORIGINS_WITH_WEB
    assert template["Parameters"]["AllowedOrigins"]["Default"] == "http://localhost:5173"


def test_output_values(template):
    o = template["Outputs"]
    assert o["WebBucketName"]["Value"] == {"!Ref": "WebBucket"}
    assert o["DistributionId"]["Value"] == {"!Ref": "WebDistribution"}
    assert o["DistributionDomain"]["Value"] == {"!GetAtt": "WebDistribution.DomainName"}


# ------------------------------------------------------------------ 알람


def test_new_alarms_and_existing_not_duplicated(template):
    alarms = {k: r for k, r in template["Resources"].items() if r["Type"] == "AWS::CloudWatch::Alarm"}
    assert set(alarms) == {"PhotoDLQNotEmpty", "AgentTokensAlarm", "HttpApi5xxAlarm", "LambdaErrorsAlarm", "ApiLambdaDurationAlarm", "AiCardLambdaDurationAlarm", "PhotoLambdaDurationAlarm"}
    dlq = [k for k, a in alarms.items() if a["Properties"].get("Namespace") == "AWS/SQS"]
    tokens = [k for k, a in alarms.items() if a["Properties"].get("MetricName") == "AgentTokens"]
    assert dlq == ["PhotoDLQNotEmpty"] and tokens == ["AgentTokensAlarm"]
    assert all("AlarmActions" not in a["Properties"] for a in alarms.values())  # 알림 대상은 BE-Q62 미결


def test_alarm_thresholds_are_parameters_marked_provisional(template):
    p = template["Parameters"]
    for name in ("AlarmApi5xxThreshold", "AlarmLambdaErrorsThreshold", "AlarmApiLambdaDurationMs", "AlarmAiLambdaDurationMs", "AlarmPhotoLambdaDurationMs"):
        assert p[name]["Type"] == "Number" and "임시값" in p[name]["Description"] and "BE-Q130" in p[name]["Description"]
    a = res(template, "HttpApi5xxAlarm")["Properties"]
    assert (a["Namespace"], a["MetricName"], a["Statistic"], a["Period"]) == ("AWS/ApiGateway", "5xx", "Sum", 300)
    assert a["Dimensions"] == [{"Name": "ApiId", "Value": {"!Ref": "HttpApi"}}] and a["Threshold"] == {"!Ref": "AlarmApi5xxThreshold"}


def test_lambda_alarms_cover_all_functions(template):
    funcs = {k for k, r in template["Resources"].items() if r["Type"] == "AWS::Serverless::Function"}
    errors = res(template, "LambdaErrorsAlarm")["Properties"]["Metrics"]
    covered = {m["MetricStat"]["Metric"]["Dimensions"][0]["Value"]["!Ref"] for m in errors if "MetricStat" in m}
    assert covered == funcs and len(errors) <= 11  # 알람당 지표 10개 한도 + 식 1개
    assert errors[-1]["Expression"] == "SUM(METRICS())" and errors[-1]["ReturnData"] is True
    api = res(template, "ApiLambdaDurationAlarm")["Properties"]["Metrics"]
    assert {m["MetricStat"]["Metric"]["Dimensions"][0]["Value"]["!Ref"] for m in api if "MetricStat" in m} == {"MeFunction", "PlansFunction", "ClaimsFunction", "InboxFunction"}
    assert all(m["MetricStat"]["Stat"] == "p95" for m in api if "MetricStat" in m)
    for name, fn in (("AiCardLambdaDurationAlarm", "AiCardFunction"), ("PhotoLambdaDurationAlarm", "PhotoProcessorFunction")):
        p = res(template, name)["Properties"]
        assert p["MetricName"] == "Duration" and p["ExtendedStatistic"] == "p95" and p["Dimensions"][0]["Value"] == {"!Ref": fn}


def test_function_timeouts_match_duration_threshold_assumptions(template):
    p = template["Parameters"]
    assert template["Globals"]["Function"]["Timeout"] * 1000 > p["AlarmApiLambdaDurationMs"]["Default"]
    assert res(template, "AiCardFunction")["Properties"]["Timeout"] * 1000 > p["AlarmAiLambdaDurationMs"]["Default"]
    assert res(template, "PhotoProcessorFunction")["Properties"]["Timeout"] * 1000 > p["AlarmPhotoLambdaDurationMs"]["Default"]


# ------------------------------------------------------------------ 대시보드


def _dashboard(template):
    body = res(template, "OpsDashboard")["Properties"]["DashboardBody"]["!Sub"]
    return json.loads(body)  # !Sub 토큰(${...})은 문자열 안에만 있어 JSON으로 읽힌다


def _emitted_metric_names():
    """EMF로 내는 지표 이름: metrics.py와 ai_agent.py의 대문자 상수 중 CamelCase 문자열 값."""
    from common import metrics
    from handlers import ai_agent

    names = set()
    for mod in (metrics, ai_agent):
        for attr, value in vars(mod).items():
            if attr.isupper() and isinstance(value, str) and re.fullmatch(r"[A-Z][A-Za-z]+", value) and value != value.upper():
                names.add(value)
    return names


def test_dashboard_is_valid_and_uses_only_real_metrics(template):
    emitted = _emitted_metric_names()
    assert {"ClaimConflict", "AgentTokens", "PhotoFailed", "AiLatencyMs"} <= emitted
    widgets = _dashboard(template)["widgets"]
    used = set()
    for w in widgets:
        if w["type"] != "metric":
            continue
        for m in w["properties"]["metrics"]:
            if isinstance(m[0], dict):  # 지표 수식
                continue
            if m[0] == "Haru":
                used.add(m[1])
                assert m[1] in emitted, f"코드가 내지 않는 지표: {m[1]}"
    # BE-OBS-03·docs/02 §2.9 항목이 모두 있다
    required = {"ClaimConflict", "CompleteDuplicate", "StaleRequestRejected", "PhotoProcessingMs", "PhotoFailed", "AiLatencyMs", "AiFailure", "AiInvalidOutput",
                "AgentModelCalls", "AgentTokens", "AgentTurnMs", "AgentQuestionsAsked", "AgentGateRejected", "AgentDegraded", "AgentSelfRepairs", "AgentCheckpointBytes"}
    assert required <= used


def test_dashboard_aws_metrics_and_limitations(template):
    widgets = _dashboard(template)["widgets"]
    flat = json.dumps(widgets, ensure_ascii=False)
    for needed in ("AWS/ApiGateway", "AWS/Lambda", "AWS/SQS", "${PhotoDLQ.QueueName}", "5xx", "Invocations", "Errors", "Duration"):
        assert needed in flat
    (text,) = [w for w in widgets if w["type"] == "text"]
    assert "AI 세션 상태 분포" in text["properties"]["markdown"] and "report.py" in text["properties"]["markdown"]  # 한계를 숨기지 않는다
    for w in widgets:
        assert 0 <= w["x"] and w["x"] + w["width"] <= 24


def test_dashboard_tokens_resolve_to_resources(template):
    body = res(template, "OpsDashboard")["Properties"]["DashboardBody"]["!Sub"]
    for token in set(re.findall(r"\$\{([^}]+)\}", body)):
        base = token.split(".")[0]
        assert base in template["Resources"] or base.startswith("AWS::"), token


# ------------------------------------------------------------------ Budgets


def test_budget_is_conditional_without_hardcoded_values(template):
    b = res(template, "MonthlyCostBudget")
    assert b["Condition"] == "CreateBudget"
    cond = json.dumps(template["Conditions"]["CreateBudget"])
    assert "BudgetNotificationEmail" in cond and "BudgetMonthlyUsd" in cond
    props = b["Properties"]
    assert props["Budget"]["BudgetLimit"]["Amount"] == {"!Ref": "BudgetMonthlyUsd"}
    for n in props["NotificationsWithSubscribers"]:
        assert n["Subscribers"][0]["Address"] == {"!Ref": "BudgetNotificationEmail"}
    assert template["Parameters"]["BudgetMonthlyUsd"]["Default"] == 0 and template["Parameters"]["BudgetNotificationEmail"]["Default"] == ""
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", Path(BACKEND / "template.yaml").read_text(encoding="utf-8"))  # 실제 이메일 없음


def test_samconfig_has_no_account_values():
    text = (BACKEND / "samconfig.toml").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text) and "@" not in text
