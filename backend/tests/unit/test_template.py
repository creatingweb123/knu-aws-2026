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


def test_cors(template):
    cors = template["Resources"]["HttpApi"]["Properties"]["CorsConfiguration"]
    assert cors["AllowOrigins"] == {"!Ref": "AllowedOrigins"}
    assert cors["AllowHeaders"] == ["Authorization", "Content-Type", "Idempotency-Key"]
    assert cors["AllowMethods"] == ["GET", "POST", "PUT", "OPTIONS"]
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


WITH_INDEX = [{"!GetAtt": "HaruTable.Arn"}, {"!Sub": "${HaruTable.Arn}/index/*"}]


def test_iam_least_privilege(template):
    """spec backend-stage3-claim 요구사항 7.2."""
    fns = functions(template)
    assert "Policies" not in fns["PreSignUpFunction"]
    plans = _only_statement(fns["PlansFunction"])
    assert set(plans["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"}
    assert plans["Resource"] == WITH_INDEX
    claims = _only_statement(fns["ClaimsFunction"])
    assert set(claims["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"}
    assert claims["Resource"] == {"!GetAtt": "HaruTable.Arn"}
    me = _only_statement(fns["MeFunction"])
    assert set(me["Action"]) == {"dynamodb:GetItem", "dynamodb:Query"}
    assert me["Resource"] == WITH_INDEX
    for props in fns.values():
        for stmt in (s for p in props.get("Policies", []) for s in _statements(p)):
            actions = stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]]
            assert not any(a.endswith(("*", "DeleteItem", "Scan")) for a in actions)


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
    assert set(template["Outputs"]) == {"ApiUrl", "UserPoolId", "UserPoolClientId"}
    types = {r["Type"] for r in template["Resources"].values()}
    assert "AWS::CloudFront::Distribution" not in types and "AWS::S3::Bucket" not in types
    assert "HaruAgentCheckpoints" not in template["Resources"]  # 6b 작업(BE-Q84)
    assert "AWS::DynamoDB::Table" in types and [k for k, r in template["Resources"].items() if r["Type"] == "AWS::DynamoDB::Table"] == ["HaruTable"]


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
OLD_FUNCTIONS = {"MeFunction", "PlansFunction", "ClaimsFunction", "PreSignUpFunction"}


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
    assert env["LLM_PROVIDER"] == {"!If": ["FakeAllowed", {"!Ref": "LlmProvider"}, "openai_compat"]}
    assert env["FAKE_LLM_ALLOWED"] == {"!If": ["FakeAllowed", "true", "false"]}
    assert env["LLM_API_KEY_PARAM"] == {"!If": ["HasLlmKeyParam", {"!Ref": "LlmApiKeyParam"}, {"!Ref": "AWS::NoValue"}]}
    assert env["LLM_MAX_RETRIES"] == "0" and env["AGENT_MODE"] == {"!Ref": "AgentMode"}
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_TOOL_CHOICE", "LLM_PARALLEL_TOOL_CALLS", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
              "LLM_CONNECT_TIMEOUT_S", "LLM_READ_TIMEOUT_S", "LLM_EXTRA_BODY", "LLM_PROVIDER_LABEL", "AI_DAILY_SESSION_LIMIT"):
        assert k in env, k
    assert (env["AI_SDK_CONNECT_TIMEOUT_S"], env["AI_SDK_READ_TIMEOUT_S"], env["AI_SDK_MAX_ATTEMPTS"]) == ("1", "2", "2")
    text = (BACKEND / "template.yaml").read_text(encoding="utf-8")
    for forbidden in ("LLM_API_KEY:", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "OPENAI_API_KEY", "OPENAI_LOG", "FAKE_LLM_SCENARIO"):
        assert forbidden not in text, forbidden
    g = template["Globals"]["Function"]["Environment"]["Variables"]
    assert g["LANGSMITH_TRACING"] == "false" and g["LANGCHAIN_TRACING_V2"] == "false"


def test_ai_parameters(template):
    p = template["Parameters"]
    assert p["Stage"] == {"Type": "String", "AllowedValues": ["dev", "demo"], "Default": "demo", "Description": p["Stage"]["Description"]}
    assert p["LlmProvider"]["AllowedValues"] == ["openai_compat", "fake"] and p["LlmProvider"]["Default"] == "openai_compat"
    assert p["AgentMode"]["AllowedValues"] == ["pipeline"] and p["AgentMode"]["Default"] == "pipeline"
    for k in ("LlmBaseUrl", "LlmModel", "LlmApiKeyParam", "LlmProviderLabel", "LlmExtraBody"):
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
    assert len(policies) == 2
    (ddb_stmt,) = policies[0]["Statement"]
    assert ddb_stmt["Effect"] == "Allow" and set(ddb_stmt["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"}
    assert ddb_stmt["Resource"] == {"!GetAtt": "HaruTable.Arn"}  # index/* 없음
    assert ddb_stmt["Condition"] == {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["AISESSION#*", "AIQUOTA#*"]}}
    cond, doc, none = policies[1]["!If"]
    assert cond == "HasLlmKeyParam" and none == {"!Ref": "AWS::NoValue"}
    (ssm_stmt,) = doc["Statement"]
    assert ssm_stmt["Action"] == "ssm:GetParameter"
    assert ssm_stmt["Resource"] == {"!Sub": "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter${LlmApiKeyParam}"}
    text = (BACKEND / "template.yaml").read_text(encoding="utf-8")
    for forbidden in ("dynamodb:Query", "dynamodb:Scan", "TransactWriteItems", "GetParameters", "kms:"):
        ai_block = text[text.index("  AiCardFunction:"): text.index("  PreSignUpFunction:")]
        assert forbidden not in ai_block, forbidden


def test_other_functions_have_no_ai_settings(template):
    fns = functions(template)
    assert set(fns) == OLD_FUNCTIONS | {"AiCardFunction"}
    for name in OLD_FUNCTIONS:
        props = fns[name]
        assert "Environment" not in props and "Timeout" not in props and "MemorySize" not in props and "CodeUri" not in props, name
        assert "Metadata" not in template["Resources"][name]
        for policy in props.get("Policies", []):
            assert "!If" not in policy
            for stmt in policy["Statement"]:
                assert not any(str(a).startswith(("ssm:", "kms:")) for a in stmt["Action"]), name


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
    ("dev", "fake", "haru-dev-copy", True, False, False),   # 스택 이름이 다르면 함수에는 openai_compat
    ("dev", "openai_compat", "haru-dev", True, True, False),
    ("demo", "fake", "haru-demo", False, False, False),     # Rules가 배포를 거부
    ("demo", "fake", "haru-dev", False, False, False),
    ("demo", "openai_compat", "haru-demo", True, False, False),
    ("demo", "openai_compat", "haru-dev", True, False, False),
])
def test_fake_guard(template, stage, provider, stack, accepted, allowed, fake_on):
    params = {"Stage": stage, "LlmProvider": provider, "AWS::StackName": stack, "LlmApiKeyParam": ""}
    conds = template["Conditions"]
    rules_ok = all(_eval(a["Assert"], params, conds) for r in template["Rules"].values() for a in r["Assertions"])
    assert rules_ok is accepted
    if accepted:
        assert _eval({"!Condition": "FakeAllowed"}, params, conds) is allowed
        env = template["Resources"]["AiCardFunction"]["Properties"]["Environment"]["Variables"]
        cond, then, other = env["LLM_PROVIDER"]["!If"]
        effective = params[then["!Ref"]] if _eval({"!Condition": cond}, params, conds) else other
        assert (effective == "fake") is fake_on
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
