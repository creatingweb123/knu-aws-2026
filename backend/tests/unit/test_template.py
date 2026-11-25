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
    inbox = _only_statement(fns["InboxFunction"])  # spec backend-stage4-record-inbox Requirement 9.2
    assert set(inbox["Action"]) == {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"}
    assert inbox["Resource"] == {"!GetAtt": "HaruTable.Arn"}  # index/* 없음
    assert "Condition" not in inbox
    for props in fns.values():
        for stmt in (s for p in props.get("Policies", []) for s in p["Statement"]):
            assert not any(a.endswith(("*", "DeleteItem", "Scan")) for a in stmt["Action"])


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
    assert "AiCardFunction" not in template["Resources"]


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
        assert "account" not in " ".join(map(str, params.values())).lower()
