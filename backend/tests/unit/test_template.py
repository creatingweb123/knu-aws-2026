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


def _statements(props):
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
    claims_ddb, claims_s3 = _statements(fns["ClaimsFunction"])  # 3단계 DynamoDB 문장 그대로 + 5단계 S3 문장
    assert set(claims_ddb["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"}
    assert claims_ddb["Resource"] == {"!GetAtt": "HaruTable.Arn"}
    assert claims_s3["Action"] == ["s3:PutObject"] and claims_s3["Resource"] == _photo_arn("photos/original/")
    me = _only_statement(fns["MeFunction"])
    assert set(me["Action"]) == {"dynamodb:GetItem", "dynamodb:Query"}
    assert me["Resource"] == WITH_INDEX
    inbox, inbox_s3 = _statements(fns["InboxFunction"])  # spec backend-stage4-record-inbox Requirement 9.2
    assert set(inbox["Action"]) == {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"}
    assert inbox["Resource"] == {"!GetAtt": "HaruTable.Arn"}  # index/* 없음
    assert "Condition" not in inbox
    assert inbox_s3["Action"] == ["s3:GetObject"] and inbox_s3["Resource"] == _photo_arn("photos/processed/")
    # 5단계 사진 처리 Lambda (spec backend-stage5-photo-pipeline Requirement 11.3)
    ph_ddb, ph_orig, ph_proc, ph_sqs = _statements(fns["PhotoProcessorFunction"])
    assert set(ph_ddb["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"} and ph_ddb["Resource"] == {"!GetAtt": "HaruTable.Arn"}
    assert ph_orig["Action"] == ["s3:GetObject"] and ph_orig["Resource"] == _photo_arn("photos/original/")
    assert set(ph_proc["Action"]) == {"s3:PutObject", "s3:DeleteObject"} and ph_proc["Resource"] == _photo_arn("photos/processed/")
    assert set(ph_sqs["Action"]) == {"sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"} and ph_sqs["Resource"] == {"!GetAtt": "PhotoQueue.Arn"}
    assert "Events" not in fns["PhotoProcessorFunction"]  # SAM SQS 이벤트(관리형 정책 Resource *)를 쓰지 않는다
    for name in ("MeFunction", "PlansFunction"):
        assert not any(a.startswith(("s3:", "sqs:")) for st in _statements(fns[name]) for a in st["Action"])
    for props in fns.values():
        for stmt in (s for p in props.get("Policies", []) for s in p["Statement"]):
            assert not any(a.endswith("*") or a in ("dynamodb:DeleteItem", "dynamodb:Scan") for a in stmt["Action"])


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
    types = [r["Type"] for r in template["Resources"].values()]
    assert "AWS::CloudFront::Distribution" not in types  # 웹 버킷·CloudFront는 7단계
    buckets = [k for k, r in template["Resources"].items() if r["Type"] == "AWS::S3::Bucket"]
    assert buckets == ["PhotoBucket"]  # 5단계 사진 버킷만
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
    assert cors["AllowedOrigins"] == {"!Ref": "AllowedOrigins"} and cors["AllowedMethods"] == ["PUT", "GET"]
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
