"""template.yaml·samconfig.toml 정적 확인과 라우트 목록 일치.

Validates: Requirements 1.1, 1.2, 1.6, 12.1, 12.2, 12.4, 12.5, 12.6, 12.8, 12.9, 13.9
(실제 배포·authorizer 동작은 AWS 스택에서 확인한다.)
"""

import tomllib
from pathlib import Path

import pytest
import yaml

from handlers.routes import ROUTES

BACKEND = Path(__file__).parents[2]
ALLOWED_ORIGINS_WITH_WEB = {"!Split": [",", {"!Join": [",", [{"!Join": [",", {"!Ref": "AllowedOrigins"}]}, {"!Sub": "https://${WebDistribution.DomainName}"}]]}]}


class CfnLoader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {f"!{suffix}": value}


CfnLoader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def template():
    return yaml.load((BACKEND / "template.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)


def functions(template):
    return {k: v["Properties"] for k, v in template["Resources"].items() if v["Type"] == "AWS::Serverless::Function"}


def template_routes(template) -> dict[str, str]:
    routes = {}
    for props in functions(template).values():
        for ev in (props.get("Events") or {}).values():
            if ev["Type"] == "HttpApi":
                p = ev["Properties"]
                routes[f"{p['Method'].upper()} {p['Path']}"] = props["Handler"]
    return routes


def route_mismatch(a: dict[str, str], b: dict[str, str]) -> set[str]:
    """한쪽에만 있거나 핸들러가 다른 경로."""
    return {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}


def test_routes_match_routes_py(template):
    assert route_mismatch(template_routes(template), ROUTES) == set()


def test_route_mismatch_detects_one_sided_route():
    assert route_mismatch({"GET /me": "h"}, {"GET /me": "h", "GET /inbox": "x"}) == {"GET /inbox"}
    assert route_mismatch({"GET /me": "h"}, {"GET /me": "other"}) == {"GET /me"}


def test_all_routes_use_default_authorizer(template):
    auth = template["Resources"]["HttpApi"]["Properties"]["Auth"]
    assert auth["DefaultAuthorizer"] == "CognitoJwt"
    jwt = auth["Authorizers"]["CognitoJwt"]
    assert jwt["IdentitySource"] == "$request.header.Authorization"
    assert jwt["JwtConfiguration"]["audience"] == [{"!Ref": "UserPoolClient"}]
    for props in functions(template).values():
        for ev in (props.get("Events") or {}).values():
            assert "Auth" not in ev["Properties"]  # 경로별로 인증을 끄지 않는다


def http_api_cors(template) -> dict:
    """HttpApi CORS 객체. SAM은 AllowOrigins가 내장 함수이면 그 값을 x-amazon-apigateway-cors 전체로 쓰므로
    CORS 객체 전체를 늘 참인 !If [CorsAlways, 객체, NoValue]로 감싼다(template.yaml HttpApi 주석)."""
    cors = template["Resources"]["HttpApi"]["Properties"]["CorsConfiguration"]
    assert set(cors) == {"AllowOrigins"}  # AllowHeaders·AllowMethods를 밖에 두면 SAM이 버린다
    cond, obj, other = cors["AllowOrigins"]["!If"]
    assert cond == "CorsAlways" and other == {"!Ref": "AWS::NoValue"}
    assert template["Conditions"]["CorsAlways"] == {"!Not": [{"!Equals": [{"!Ref": "AWS::StackName"}, ""]}]}  # 늘 참
    return obj


def test_cors(template):
    cors = http_api_cors(template)
    # 7단계: AllowedOrigins(로컬 등) + 이 스택의 CloudFront 도메인(BE-INFRA-03)
    assert cors["allowOrigins"] == ALLOWED_ORIGINS_WITH_WEB
    assert cors["allowHeaders"] == ["Authorization", "Content-Type", "Idempotency-Key"]
    assert cors["allowMethods"] == ["GET", "POST", "PUT", "OPTIONS"]
    assert template["Parameters"]["AllowedOrigins"]["Default"] == "http://localhost:5173"


def test_globals(template):
    g = template["Globals"]["Function"]
    assert g["Runtime"] == "python3.12" and g["CodeUri"] == "src/"
    env = g["Environment"]["Variables"]
    assert env["AREA_ID"] == "default" and env["CLAIM_DURATION_DAYS"] == "3"
    assert env["LANGSMITH_TRACING"] == "false" and env["LANGCHAIN_TRACING_V2"] == "false"
    assert env["TABLE_NAME"] == {"!Ref": "HaruTable"}
    assert "AWS_ENDPOINT_URL" not in env and "AWS_EMF_ENVIRONMENT" not in env
    for props in functions(template).values():
        assert "VpcConfig" not in props and props.get("Runtime", "python3.12") == "python3.12"


def _statements(policy):
    """정책 문서의 문장. 조건부 정책(!If [cond, 문서, NoValue])이면 참일 때의 문서를 본다."""
    if "!If" in policy:
        policy = policy["!If"][1]
    return policy["Statement"]


def _only_statement(props):
    (policy,) = props["Policies"]
    (stmt,) = policy["Statement"]
    assert stmt["Effect"] == "Allow"
    return stmt


def _fn_statements(props):
    (policy,) = props["Policies"]
    assert all(st["Effect"] == "Allow" for st in policy["Statement"])
    return policy["Statement"]


def _photo_arn(prefix):
    return {"!Sub": f"arn:${{AWS::Partition}}:s3:::${{AWS::StackName}}-photos-${{AWS::AccountId}}/{prefix}*"}


WITH_INDEX = [{"!GetAtt": "HaruTable.Arn"}, {"!Sub": "${HaruTable.Arn}/index/*"}]


def test_iam_least_privilege(template):
    """spec backend-stage3-claim 요구사항 7.2."""
    fns = functions(template)
    assert "Policies" not in fns["PreSignUpFunction"]
    plans = _only_statement(fns["PlansFunction"])
    assert set(plans["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"}
    assert plans["Resource"] == WITH_INDEX
    claims_ddb, claims_s3 = _fn_statements(fns["ClaimsFunction"])  # 3단계 DynamoDB 문장 그대로 + 5단계 S3 문장
    assert set(claims_ddb["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"}
    assert claims_ddb["Resource"] == {"!GetAtt": "HaruTable.Arn"}
    assert claims_s3["Action"] == ["s3:PutObject"] and claims_s3["Resource"] == _photo_arn("photos/original/")
    me = _only_statement(fns["MeFunction"])
    assert set(me["Action"]) == {"dynamodb:GetItem", "dynamodb:Query"}
    assert me["Resource"] == WITH_INDEX
    inbox, inbox_s3 = _fn_statements(fns["InboxFunction"])  # spec backend-stage4-record-inbox Requirement 9.2
    assert set(inbox["Action"]) == {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"}
    assert inbox["Resource"] == {"!GetAtt": "HaruTable.Arn"}  # index/* 없음
    assert "Condition" not in inbox
    assert inbox_s3["Action"] == ["s3:GetObject"] and inbox_s3["Resource"] == _photo_arn("photos/processed/")
    # 5단계 사진 처리 Lambda (spec backend-stage5-photo-pipeline Requirement 11.3)
    ph_ddb, ph_orig, ph_proc, ph_sqs = _fn_statements(fns["PhotoProcessorFunction"])
    assert set(ph_ddb["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"} and ph_ddb["Resource"] == {"!GetAtt": "HaruTable.Arn"}
    assert ph_orig["Action"] == ["s3:GetObject"] and ph_orig["Resource"] == _photo_arn("photos/original/")
    assert set(ph_proc["Action"]) == {"s3:PutObject", "s3:DeleteObject"} and ph_proc["Resource"] == _photo_arn("photos/processed/")
    assert set(ph_sqs["Action"]) == {"sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"} and ph_sqs["Resource"] == {"!GetAtt": "PhotoQueue.Arn"}
    assert "Events" not in fns["PhotoProcessorFunction"]  # SAM SQS 이벤트(관리형 정책 Resource *)를 쓰지 않는다
    for name in ("MeFunction", "PlansFunction"):
        assert not any(a.startswith(("s3:", "sqs:")) for st in _fn_statements(fns[name]) for a in st["Action"])
    for props in fns.values():
        for stmt in (s for p in props.get("Policies", []) for s in _statements(p)):
            actions = stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]]
            assert not any(a.endswith("*") or a in ("dynamodb:DeleteItem", "dynamodb:Scan") for a in actions)


def test_table(template):
    t = template["Resources"]["HaruTable"]["Properties"]
    assert t["BillingMode"] == "PAY_PER_REQUEST"
    assert t["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}
    assert {i["IndexName"] for i in t["GlobalSecondaryIndexes"]} == {"GSI1", "GSI2"}


def test_user_pool(template):
    pool = template["Resources"]["UserPool"]["Properties"]
    assert pool["UsernameAttributes"] == ["email"]
    assert {"Name": "nickname", "AttributeDataType": "String", "Mutable": True, "Required": True} in pool["Schema"]
    assert "Policies" not in pool  # 비밀번호 정책은 Cognito 기본(BE-Q27)
    assert pool["LambdaConfig"]["PreSignUp"] == {"!GetAtt": "PreSignUpFunction.Arn"}
    client = template["Resources"]["UserPoolClient"]["Properties"]
    assert client["GenerateSecret"] is False
    assert set(client["ExplicitAuthFlows"]) == {"ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"}


def test_outputs_and_scope(template):
    assert set(template["Outputs"]) == {"ApiUrl", "UserPoolId", "UserPoolClientId", "WebBucketName", "DistributionId", "DistributionDomain"}  # BE-INFRA-04
    res = template["Resources"]
    buckets = [k for k, r in res.items() if r["Type"] == "AWS::S3::Bucket"]
    assert buckets == ["PhotoBucket", "WebBucket"]  # 5단계 사진 버킷 + 7단계 웹 버킷
    assert [k for k, r in res.items() if r["Type"] == "AWS::CloudFront::Distribution"] == ["WebDistribution"]
    # 6b: 체크포인트 테이블이 생겼다(6a의 "없음" 기대값을 바꿈, design §18.1)
    assert [k for k, r in res.items() if r["Type"] == "AWS::DynamoDB::Table"] == ["HaruTable", "HaruAgentCheckpoints"]


def test_no_stage3_dependencies():
    for line in (BACKEND / "src" / "requirements.txt").read_text(encoding="utf-8").lower().splitlines():
        name = line.split("#")[0].strip()
        assert not name.startswith(("langgraph", "langchain", "pillow")), name


def test_samconfig_envs():
    cfg = tomllib.loads((BACKEND / "samconfig.toml").read_text(encoding="utf-8"))
    for env in ("dev", "demo"):
        params = cfg[env]["deploy"]["parameters"]
        assert "AllowedOrigins=" in params["parameter_overrides"]
        assert "cloudfront" not in params["parameter_overrides"].lower()
        assert f"Stage={env}" in params["parameter_overrides"].split()
        assert "Llm" not in params["parameter_overrides"]  # 공급자·모델 값은 넣지 않는다(BE-Q6)
        assert "account" not in " ".join(map(str, params.values())).lower()


# ---------------------------------------------------------------- 6a: AiCardFunction (Requirement 15, 작업 12.5)

AI_ROUTES = {"POST /ai/card-sessions", "GET /ai/card-sessions/{sessionId}", "POST /ai/card-sessions/{sessionId}/turns"}
OLD_FUNCTIONS = {"MeFunction", "PlansFunction", "ClaimsFunction", "InboxFunction", "PreSignUpFunction"}


def test_ai_function_settings(template):
    res = template["Resources"]["AiCardFunction"]
    props = res["Properties"]
    assert res["Metadata"] == {"BuildMethod": "makefile"} and "CodeUri" not in props  # Globals CodeUri src/
    assert props["Handler"] == "handlers.ai_card.handler" and props["Timeout"] == 27 and props["MemorySize"] == 1024
    assert props["Architectures"] == ["x86_64"] and "VpcConfig" not in props and "Layers" not in props
    routes = {f"{e['Properties']['Method'].upper()} {e['Properties']['Path']}" for e in props["Events"].values()}
    assert routes == AI_ROUTES


def test_ai_function_env(template):
    env = template["Resources"]["AiCardFunction"]["Properties"]["Environment"]["Variables"]
    assert env["LLM_PROVIDER"] == {"!If": ["FakeAllowed", {"!Ref": "LlmProvider"},
                                           {"!If": ["LlmIsFake", "bedrock", {"!Ref": "LlmProvider"}]}]}
    assert env["LLM_REGION"] == {"!If": ["HasLlmRegion", {"!Ref": "LlmRegion"}, {"!Ref": "AWS::NoValue"}]}
    assert env["FAKE_LLM_ALLOWED"] == {"!If": ["FakeAllowed", "true", "false"]}
    assert env["LLM_API_KEY_PARAM"] == {"!If": ["HasLlmKeyParam", {"!Ref": "LlmApiKeyParam"}, {"!Ref": "AWS::NoValue"}]}
    assert env["LLM_MAX_RETRIES"] == "0" and env["AGENT_MODE"] == {"!Ref": "AgentMode"}
    assert env["CHECKPOINT_TABLE"] == {"!Ref": "HaruAgentCheckpoints"} and "CHECKPOINT_DDB_ENDPOINT" not in env
    assert env["FAULT_INJECT"] == {"!If": ["FakeAllowed", {"!Ref": "AiFaultInject"}, ""]}
    assert env["FAULT_INJECT_ALLOWED"] == {"!If": ["FakeAllowed", "true", "false"]}
    assert not any(k.startswith("AGENT_TEST") or k == "AGENT_CRASH_AT" for k in env)  # 로컬 전용 훅은 AWS에 없다
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_TOOL_CHOICE", "LLM_PARALLEL_TOOL_CALLS", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
              "LLM_CONNECT_TIMEOUT_S", "LLM_READ_TIMEOUT_S", "LLM_EXTRA_BODY", "LLM_PROVIDER_LABEL", "AI_DAILY_SESSION_LIMIT", "AI_MASK_BEFORE_SEND"):
        assert k in env, k
    assert env["AI_MASK_BEFORE_SEND"] == {"!Ref": "AiMaskBeforeSend"} and template["Parameters"]["AiMaskBeforeSend"]["Default"] == "false"  # BE-Q10 미결: 기본 꺼짐
    assert (env["AI_SDK_CONNECT_TIMEOUT_S"], env["AI_SDK_READ_TIMEOUT_S"], env["AI_SDK_MAX_ATTEMPTS"]) == ("1", "2", "2")
    text = (BACKEND / "template.yaml").read_text(encoding="utf-8")
    for forbidden in ("LLM_API_KEY:", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "OPENAI_API_KEY", "OPENAI_LOG", "FAKE_LLM_SCENARIO"):
        assert forbidden not in text, forbidden
    g = template["Globals"]["Function"]["Environment"]["Variables"]
    assert g["LANGSMITH_TRACING"] == "false" and g["LANGCHAIN_TRACING_V2"] == "false"


def test_ai_parameters(template):
    p = template["Parameters"]
    assert p["Stage"] == {"Type": "String", "AllowedValues": ["dev", "demo"], "Default": "demo", "Description": p["Stage"]["Description"]}
    assert p["LlmProvider"]["AllowedValues"] == ["bedrock", "openai_compat", "fake"] and p["LlmProvider"]["Default"] == "bedrock"
    assert p["AgentMode"]["AllowedValues"] == ["pipeline", "agent"] and p["AgentMode"]["Default"] == "pipeline"  # 6b에서 agent를 연다
    assert p["AiFaultInject"]["AllowedValues"] == ["", "ai-slow"] and p["AiFaultInject"]["Default"] == ""
    for k in ("LlmBaseUrl", "LlmModel", "LlmRegion", "LlmApiKeyParam", "LlmProviderLabel", "LlmExtraBody"):
        assert p[k]["Default"] == "", k
    assert p["AiDailySessionLimit"]["Default"] == "10" and p["LlmMaxTokens"]["Default"] == "800"
    assert (p["LlmConnectTimeoutS"]["Default"], p["LlmReadTimeoutS"]["Default"], p["LlmTemperature"]["Default"]) == ("2", "8", "0")


@pytest.mark.parametrize(("value", "ok"), [("", True), ("/haru/dev/llm/api-key", True), ("/a", True), ("haru/dev", False),
                                           ("/haru/*", False), ("/haru/dev/", False), ("/haru dev", False)])
def test_key_param_pattern(template, value, ok):
    import re

    assert bool(re.fullmatch(template["Parameters"]["LlmApiKeyParam"]["AllowedPattern"], value)) is ok


def test_ai_iam(template):
    policies = template["Resources"]["AiCardFunction"]["Properties"]["Policies"]
    assert len(policies) == 4  # 6b: 체크포인트 테이블 문장 추가(6a 기대값 2 → 3), Bedrock 문장 추가(3 → 4)
    (ddb_stmt,) = policies[0]["Statement"]
    assert ddb_stmt["Effect"] == "Allow" and set(ddb_stmt["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"}
    assert ddb_stmt["Resource"] == {"!GetAtt": "HaruTable.Arn"}  # index/* 없음
    assert ddb_stmt["Condition"] == {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["AISESSION#*", "AIQUOTA#*"]}}
    (ck_stmt,) = policies[1]["Statement"]
    assert ck_stmt["Effect"] == "Allow" and "Condition" not in ck_stmt
    assert set(ck_stmt["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:BatchGetItem",
                                      "dynamodb:BatchWriteItem"}
    assert ck_stmt["Resource"] == {"!GetAtt": "HaruAgentCheckpoints.Arn"}  # 이 테이블만, index 없음
    cond, doc, none = policies[2]["!If"]
    assert cond == "HasLlmKeyParam" and none == {"!Ref": "AWS::NoValue"}
    (ssm_stmt,) = doc["Statement"]
    assert ssm_stmt["Action"] == "ssm:GetParameter"
    assert ssm_stmt["Resource"] == {"!Sub": "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter${LlmApiKeyParam}"}
    (br_stmt,) = policies[3]["Statement"]
    assert br_stmt["Effect"] == "Allow" and br_stmt["Action"] == "bedrock:InvokeModel" and "Condition" not in br_stmt
    assert br_stmt["Resource"] == [
        {"!Sub": "arn:${AWS::Partition}:bedrock:*::foundation-model/*"},
        {"!Sub": "arn:${AWS::Partition}:bedrock:*:${AWS::AccountId}:inference-profile/*"},
        {"!Sub": "arn:${AWS::Partition}:bedrock:*:${AWS::AccountId}:application-inference-profile/*"},
    ]  # 스트리밍(InvokeModelWithResponseStream)·관리 API 없음
    text = (BACKEND / "template.yaml").read_text(encoding="utf-8")
    ai_block = text[text.index("  AiCardFunction:"): text.index("  AgentTokensAlarm:")]
    for forbidden in ("dynamodb:Scan", "dynamodb:DeleteItem", "TransactWriteItems", "GetParameters", "kms:", "Action: bedrock:*",
                      "InvokeModelWithResponseStream"):
        assert forbidden not in ai_block, forbidden
    haru_stmts = [st for pol in policies[:2] for st in pol["Statement"] if st["Resource"] == {"!GetAtt": "HaruTable.Arn"}]
    assert all("dynamodb:Query" not in st["Action"] for st in haru_stmts)  # HaruTable에는 여전히 Query 없음


def test_other_functions_have_no_ai_settings(template):
    fns = functions(template)
    assert set(fns) == OLD_FUNCTIONS | {"AiCardFunction", "PhotoProcessorFunction"}  # 5단계 사진 처리 함수
    for name in set(fns) - {"AiCardFunction"}:
        props = fns[name]
        if name in OLD_FUNCTIONS:
            assert "Timeout" not in props and "MemorySize" not in props and "CodeUri" not in props, name
            assert "Metadata" not in template["Resources"][name]
        env = props.get("Environment", {}).get("Variables", {})  # 5단계: ClaimsFunction·사진 함수에 사진 설정이 있다
        assert not any(k.startswith(("LLM_", "AI_", "AGENT_", "CHECKPOINT")) or k == "FAKE_LLM_ALLOWED" for k in env), name
        assert template["Resources"][name].get("Metadata", {}).get("BuildMethod") != "makefile", name
        for policy in props.get("Policies", []):
            assert "!If" not in policy
            for stmt in policy["Statement"]:
                assert not any(str(a).startswith(("ssm:", "kms:")) for a in stmt["Action"]), name


def test_checkpoint_table(template):
    t = template["Resources"]["HaruAgentCheckpoints"]["Properties"]
    assert t["BillingMode"] == "PAY_PER_REQUEST" and "GlobalSecondaryIndexes" not in t
    assert t["KeySchema"] == [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}]
    assert t["TimeToLiveSpecification"] == {"AttributeName": "ttl", "Enabled": True}
    assert t["PointInTimeRecoverySpecification"] == {"PointInTimeRecoveryEnabled": True}


def test_no_other_function_touches_checkpoints(template):
    text = (BACKEND / "template.yaml").read_text(encoding="utf-8")
    for name, props in functions(template).items():
        if name == "AiCardFunction":
            continue
        for stmt in (st for pol in props.get("Policies", []) for st in _statements(pol)):
            assert "HaruAgentCheckpoints" not in str(stmt["Resource"]), name
        assert "CHECKPOINT_TABLE" not in str(props.get("Environment")), name
    assert "CHECKPOINT_TABLE" not in str(template["Globals"])
    assert text.count("HaruAgentCheckpoints.Arn") == 1


def test_agent_tokens_alarm(template):
    a = template["Resources"]["AgentTokensAlarm"]
    assert a["Type"] == "AWS::CloudWatch::Alarm"
    p = a["Properties"]
    assert (p["Namespace"], p["MetricName"], p["Statistic"], p["Period"], p["EvaluationPeriods"]) == ("Haru", "AgentTokens", "Sum", 300, 1)
    assert p["Threshold"] == 300000 and p["ComparisonOperator"] == "GreaterThanThreshold" and p["TreatMissingData"] == "notBreaching"
    assert "AlarmActions" not in p and "Dimensions" not in p  # 알림 대상 없음, EMF 차원 없음(common/metrics)


@pytest.mark.parametrize(("stage", "fault", "stack", "accepted", "env_value"), [
    ("dev", "ai-slow", "haru-dev", True, "ai-slow"),
    ("dev", "ai-slow", "haru-dev-copy", True, ""),     # 스택 이름이 다르면 함수에는 빈 값
    ("dev", "", "haru-dev", True, ""),
    ("demo", "ai-slow", "haru-demo", False, None),     # Rules가 배포를 거부
    ("demo", "ai-slow", "haru-dev", False, None),
    ("demo", "", "haru-demo", True, ""),
])
def test_ai_fault_inject_guard(template, stage, fault, stack, accepted, env_value):
    params = {"Stage": stage, "LlmProvider": "openai_compat", "AiFaultInject": fault, "AWS::StackName": stack, "LlmApiKeyParam": "", "FaultInject": ""}
    conds = template["Conditions"]
    rules_ok = all(_eval(a["Assert"], params, conds) for r in template["Rules"].values() for a in r["Assertions"])
    assert rules_ok is accepted
    if accepted:
        env = template["Resources"]["AiCardFunction"]["Properties"]["Environment"]["Variables"]
        cond, then, other = env["FAULT_INJECT"]["!If"]
        assert (params[then["!Ref"]] if _eval({"!Condition": cond}, params, conds) else other) == env_value


@pytest.mark.parametrize(("env", "on"), [
    ({"FAULT_INJECT": "ai-slow", "FAULT_INJECT_ALLOWED": "true", "AWS_LAMBDA_FUNCTION_NAME": "haru-dev-AiCardFunction-x"}, True),
    ({"FAULT_INJECT": "ai-slow", "FAULT_INJECT_ALLOWED": "true", "AWS_LAMBDA_FUNCTION_NAME": "haru-demo-AiCardFunction-x"}, False),
    ({"FAULT_INJECT": "ai-slow", "FAULT_INJECT_ALLOWED": "false", "AWS_LAMBDA_FUNCTION_NAME": "haru-dev-AiCardFunction-x"}, False),
    ({"FAULT_INJECT": "ai-slow", "FAULT_INJECT_ALLOWED": "true", "STAGE": "local"}, True),
    ({"FAULT_INJECT": "ai-slow", "FAULT_INJECT_ALLOWED": "true", "STAGE": "dev"}, False),
    ({"FAULT_INJECT": "", "FAULT_INJECT_ALLOWED": "true", "STAGE": "local"}, False),
])
def test_ai_fault_inject_runtime(env, on):
    from agent.fault import SLOW_S, slow_delay_s

    assert slow_delay_s(env) == (SLOW_S if on else 0.0)


def test_route_settings(template):
    rs = template["Resources"]["HttpApi"]["Properties"]["RouteSettings"]
    assert rs == {
        "POST /ai/card-sessions": {"ThrottlingRateLimit": 2, "ThrottlingBurstLimit": 5},
        "POST /ai/card-sessions/{sessionId}/turns": {"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10},
        "GET /ai/card-sessions/{sessionId}": {"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20},
    }
    assert set(rs) == AI_ROUTES and set(rs) <= set(ROUTES)


def _eval(expr, params, conditions):
    """Conditions·Rules 식의 작은 평가기(Equals·And·Or·Not·Condition·Ref)."""
    if isinstance(expr, str):
        return expr
    (op, arg), = expr.items()
    if op == "!Ref":
        return params[arg]
    if op == "!Equals":
        return _eval(arg[0], params, conditions) == _eval(arg[1], params, conditions)
    if op == "!And":
        return all(_eval(a, params, conditions) for a in arg)
    if op == "!Or":
        return any(_eval(a, params, conditions) for a in arg)
    if op == "!Not":
        return not _eval(arg[0], params, conditions)
    if op == "!Condition":
        return _eval(conditions[arg], params, conditions)
    raise AssertionError(op)


@pytest.mark.parametrize(("stage", "provider", "stack", "accepted", "allowed", "fake_on"), [
    ("dev", "fake", "haru-dev", True, True, True),
    ("dev", "fake", "haru-dev-copy", True, False, False),   # 스택 이름이 다르면 함수에는 bedrock
    ("dev", "openai_compat", "haru-dev", True, True, False),
    ("dev", "bedrock", "haru-dev", True, True, False),
    ("dev", "bedrock", "haru-dev-copy", True, False, False),
    ("demo", "fake", "haru-demo", False, False, False),     # Rules가 배포를 거부
    ("demo", "fake", "haru-dev", False, False, False),
    ("demo", "openai_compat", "haru-demo", True, False, False),
    ("demo", "openai_compat", "haru-dev", True, False, False),
    ("demo", "bedrock", "haru-demo", True, False, False),
])
def test_fake_guard(template, stage, provider, stack, accepted, allowed, fake_on):
    params = {"Stage": stage, "LlmProvider": provider, "AWS::StackName": stack, "LlmApiKeyParam": "", "AiFaultInject": "", "FaultInject": ""}
    conds = template["Conditions"]
    rules_ok = all(_eval(a["Assert"], params, conds) for r in template["Rules"].values() for a in r["Assertions"])
    assert rules_ok is accepted
    if accepted:
        assert _eval({"!Condition": "FakeAllowed"}, params, conds) is allowed
        env = template["Resources"]["AiCardFunction"]["Properties"]["Environment"]["Variables"]
        cond, then, other = env["LLM_PROVIDER"]["!If"]
        if _eval({"!Condition": cond}, params, conds):
            effective = params[then["!Ref"]]
        else:
            in_cond, in_then, in_else = other["!If"]
            effective = in_then if _eval({"!Condition": in_cond}, params, conds) else params[in_else["!Ref"]]
        assert (effective == "fake") is fake_on
        assert effective == (provider if allowed or provider != "fake" else "bedrock")
        fa_cond, fa_then, fa_else = env["FAKE_LLM_ALLOWED"]["!If"]
        assert (fa_then if _eval({"!Condition": fa_cond}, params, conds) else fa_else) == ("true" if allowed else "false")


@pytest.mark.parametrize(("value", "has"), [("", False), ("/haru/dev/llm/api-key", True)])
def test_key_param_condition(template, value, has):
    assert _eval({"!Condition": "HasLlmKeyParam"}, {"LlmApiKeyParam": value}, template["Conditions"]) is has


def test_makefile_build():
    mk = (BACKEND / "src" / "Makefile").read_text(encoding="utf-8")
    assert "build-AiCardFunction:" in mk
    assert "--require-hashes" in mk and "--only-binary=:all:" in mk and "--no-deps" in mk and "-r ai-requirements.lock" in mk
    assert "cp -r common domain handlers agent prompts" in mk
    for line in mk.splitlines():
        if line and not line.startswith(("#", "build-")):
            assert line.startswith("\t"), line  # 레시피 줄은 탭


def test_compose_agent_settings():
    """로컬 compose: 기본 pipeline(6a 로컬 23건 유지), 체크포인트 엔드포인트, 테스트 훅 기본 꺼짐(design §18.4)."""
    import yaml as _yaml

    api = _yaml.safe_load((BACKEND / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["api"]["environment"]
    assert api["AGENT_MODE"] == "${AGENT_MODE:-pipeline}" and api["CHECKPOINT_TABLE"] == "HaruAgentCheckpoints"
    assert api["CHECKPOINT_DDB_ENDPOINT"] == "http://aws:4566" and api["STAGE"] == "local"
    assert api["AGENT_TEST_HOOKS"] == "${AGENT_TEST_HOOKS:-false}"
# ---------------------------------------------------------------- 5단계 사진 파이프라인 리소스


def test_photo_bucket(template):
    r = template["Resources"]["PhotoBucket"]
    assert r["DependsOn"] == "PhotoQueuePolicy"  # BE-PHOTO-09
    p = r["Properties"]
    assert p["BucketName"] == {"!Sub": "${AWS::StackName}-photos-${AWS::AccountId}"}
    assert p["PublicAccessBlockConfiguration"] == {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}
    assert p["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    assert p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"] == {"SSEAlgorithm": "AES256"}
    (cors,) = p["CorsConfiguration"]["CorsRules"]
    assert cors["AllowedOrigins"] == ALLOWED_ORIGINS_WITH_WEB and cors["AllowedMethods"] == ["PUT", "GET"]
    assert cors["AllowedHeaders"] == {"!If": ["UseIfNoneMatch", ["Content-Type", "If-None-Match"], ["Content-Type"]]}
    rules = {x["Id"]: x for x in p["LifecycleConfiguration"]["Rules"]}
    assert rules["ExpireOriginals"]["Prefix"] == "photos/original/" and rules["ExpireOriginals"]["ExpirationInDays"] == 7
    assert all("photos/processed/" not in x.get("Prefix", "") or "ExpirationInDays" not in x for x in rules.values())  # 처리본 일괄 만료 없음
    (qc,) = p["NotificationConfiguration"]["QueueConfigurations"]
    assert qc["Event"] == "s3:ObjectCreated:*" and qc["Filter"]["S3Key"]["Rules"] == [{"Name": "prefix", "Value": "photos/original/"}]


def test_photo_bucket_policy(template):
    stmts = template["Resources"]["PhotoBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
    tls = stmts[0]
    assert tls["Effect"] == "Deny" and tls["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    cond_if = stmts[1]["!If"]
    assert cond_if[0] == "UseIfNoneMatch" and cond_if[1]["Effect"] == "Deny" and cond_if[1]["Action"] == "s3:PutObject"
    assert cond_if[1]["Condition"] == {"Null": {"s3:if-none-match": "true"}} and cond_if[2] == {"!Ref": "AWS::NoValue"}


def test_photo_queues_and_policy(template):
    res = template["Resources"]
    q = res["PhotoQueue"]["Properties"]
    assert q["VisibilityTimeout"] == 180 and q["RedrivePolicy"] == {"deadLetterTargetArn": {"!GetAtt": "PhotoDLQ.Arn"}, "maxReceiveCount": 3}
    assert q["SqsManagedSseEnabled"] is True and res["PhotoDLQ"]["Properties"]["SqsManagedSseEnabled"] is True
    assert res["PhotoDLQ"]["Properties"]["MessageRetentionPeriod"] == 1209600
    (st,) = res["PhotoQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"]
    assert st["Principal"] == {"Service": "s3.amazonaws.com"} and st["Action"] == "sqs:SendMessage"
    assert st["Condition"]["ArnEquals"]["aws:SourceArn"] == {"!Sub": "arn:${AWS::Partition}:s3:::${AWS::StackName}-photos-${AWS::AccountId}"}  # 문자열(순환 회피)
    assert st["Condition"]["StringEquals"]["aws:SourceAccount"] == {"!Ref": "AWS::AccountId"}
    esm = res["PhotoProcessorQueueMapping"]
    assert esm["Type"] == "AWS::Lambda::EventSourceMapping"
    assert esm["Properties"] == {"FunctionName": {"!Ref": "PhotoProcessorFunction"}, "EventSourceArn": {"!GetAtt": "PhotoQueue.Arn"}, "BatchSize": 1, "Enabled": True}


def test_photo_function_layer_and_alarm(template):
    res = template["Resources"]
    fn = res["PhotoProcessorFunction"]["Properties"]
    assert fn["Handler"] == "workers.photo_processor.handler" and fn["Timeout"] == 30 and fn["MemorySize"] == 1024
    assert fn["Architectures"] == ["x86_64"] and fn["Layers"] == [{"!Ref": "PillowLayer"}]
    env = fn["Environment"]["Variables"]
    assert env["FAULT_INJECT"] == {"!If": ["FaultAllowed", {"!Ref": "FaultInject"}, ""]}
    assert env["FAULT_INJECT_ALLOWED"] == {"!If": ["FaultAllowed", "true", "false"]}
    assert (env["PHOTO_SDK_CONNECT_TIMEOUT_S"], env["PHOTO_SDK_READ_TIMEOUT_S"], env["PHOTO_SDK_MAX_ATTEMPTS"], env["PHOTO_RESERVE_MS"]) == ("2", "5", "2", "5000")
    layer = res["PillowLayer"]
    assert layer["Properties"]["CompatibleRuntimes"] == ["python3.12"] and layer["Properties"]["CompatibleArchitectures"] == ["x86_64"]
    assert layer["Metadata"] == {"BuildMethod": "python3.12", "BuildArchitecture": "x86_64"}
    assert "Pillow==" in (BACKEND / "layers" / "pillow" / "requirements.txt").read_text(encoding="utf-8")
    alarm = res["PhotoDLQNotEmpty"]["Properties"]
    assert (alarm["Namespace"], alarm["MetricName"], alarm["Statistic"], alarm["Threshold"], alarm["ComparisonOperator"]) == (
        "AWS/SQS", "ApproximateNumberOfMessagesVisible", "Maximum", 0, "GreaterThanThreshold")
    assert alarm["TreatMissingData"] == "notBreaching" and "AlarmActions" not in alarm  # BE-Q62
    claims_env = res["ClaimsFunction"]["Properties"]["Environment"]["Variables"]
    assert claims_env["PHOTO_UPLOAD_IF_NONE_MATCH"] == {"!If": ["UseIfNoneMatch", "true", "false"]} and claims_env["PUBLIC_S3_ENDPOINT"] == ""


def test_stage5_parameters_defaults(template):
    params = template["Parameters"]
    assert params["Stage"]["Default"] == "demo" and params["Stage"]["AllowedValues"] == ["dev", "demo"]
    assert params["FaultInject"]["Default"] == "" and params["UploadIfNoneMatch"]["Default"] == "false"  # BE-Q65 기본 꺼짐
    cfg = tomllib.loads((BACKEND / "samconfig.toml").read_text(encoding="utf-8"))
    assert "Stage=dev" in cfg["dev"]["deploy"]["parameters"]["parameter_overrides"]
    assert "Stage=demo" in cfg["demo"]["deploy"]["parameters"]["parameter_overrides"]
    for env in ("dev", "demo"):
        po = cfg[env]["deploy"]["parameters"]["parameter_overrides"]
        assert "FaultInject" not in po and "UploadIfNoneMatch" not in po


def test_compose_has_no_duplicate_keys():
    """통합 병합에서 api 서비스에 FAULT_INJECT가 두 번 들어가 docker compose가 파싱에 실패한 적이 있다(2026-11-27)."""
    import pathlib

    import yaml

    class Strict(yaml.SafeLoader):
        pass

    def construct(loader, node, deep=False):
        seen = set()
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            assert key not in seen, f"중복 키: {key}"
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct)
    doc = yaml.load((pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8"), Loader=Strict)
    assert {"aws", "api"} <= set(doc["services"])
