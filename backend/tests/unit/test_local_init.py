"""local/init/01_haru.py 단계 로직 (가짜 boto3 클라이언트, Docker 없이).

Validates: Requirements 13.2, 13.3, 13.11
"""

import importlib.util
import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

INIT = Path(__file__).parents[2] / "local" / "init" / "01_haru.py"


@pytest.fixture
def init(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("haru_init", INIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DONE_MARKER", tmp_path / "done")
    return mod


def err(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "op")


class FakeDdb:
    def __init__(self):
        self.tables, self.ttl, self.created = {}, {}, []

    def describe_table(self, TableName):
        if TableName not in self.tables:
            raise err("ResourceNotFoundException")
        return {"Table": {"TableStatus": "ACTIVE", **self.tables[TableName]}}

    def create_table(self, **kw):
        self.tables[kw["TableName"]] = kw
        self.created.append(kw["TableName"])

    def describe_time_to_live(self, TableName):
        return {"TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED" if TableName in self.ttl else "DISABLED"}}

    def update_time_to_live(self, TableName, TimeToLiveSpecification):
        self.ttl[TableName] = TimeToLiveSpecification


class FakeIdp:
    def __init__(self, honor_override=True):
        self.pools, self.clients, self.users, self.passwords = {}, {}, {}, {}
        self.honor_override = honor_override

    def describe_user_pool(self, UserPoolId):
        if UserPoolId not in self.pools:
            raise err("ResourceNotFoundException")
        return {"UserPool": self.pools[UserPoolId]}

    def list_user_pools(self, MaxResults):
        return {"UserPools": [{"Id": k, "Name": v["PoolName"]} for k, v in self.pools.items()]}

    def create_user_pool(self, **kw):
        pid = kw["UserPoolTags"]["floci:override-id"] if self.honor_override else "ap-northeast-2_random123"
        self.pools[pid] = kw
        return {"UserPool": {"Id": pid}}

    def list_user_pool_clients(self, UserPoolId, MaxResults):
        return {"UserPoolClients": [{"ClientId": cid, "ClientName": c["ClientName"]} for cid, c in self.clients.items() if c["UserPoolId"] == UserPoolId]}

    def create_user_pool_client(self, **kw):
        cid = kw["ClientName"] if self.honor_override else "randomclientid"
        self.clients[cid] = kw
        return {"UserPoolClient": {"ClientId": cid}}

    def admin_get_user(self, UserPoolId, Username):
        if (UserPoolId, Username) not in self.users:
            raise err("UserNotFoundException")
        return self.users[(UserPoolId, Username)]

    def admin_create_user(self, **kw):
        self.users[(kw["UserPoolId"], kw["Username"])] = kw

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):
        self.passwords[(UserPoolId, Username)] = (Password, Permanent)


class FakeSqs:
    def __init__(self):
        self.queues, self.created = {}, []

    def _url(self, name):
        return f"http://localhost:4566/000000000000/{name}"

    def get_queue_url(self, QueueName):
        if QueueName not in self.queues:
            raise err("AWS.SimpleQueueService.NonExistentQueue")
        return {"QueueUrl": self._url(QueueName)}

    def create_queue(self, QueueName, Attributes):
        self.queues[QueueName] = dict(Attributes)
        self.created.append(QueueName)
        return {"QueueUrl": self._url(QueueName)}

    def set_queue_attributes(self, QueueUrl, Attributes):
        self.queues[QueueUrl.rsplit("/", 1)[1]].update(Attributes)

    def get_queue_attributes(self, QueueUrl, AttributeNames):
        return {"Attributes": {"QueueArn": f"arn:aws:sqs:ap-northeast-2:000000000000:{QueueUrl.rsplit('/', 1)[1]}"}}


class FakeS3:
    def __init__(self):
        self.buckets, self.created = {}, []

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            raise err("404")

    def create_bucket(self, Bucket, CreateBucketConfiguration):
        self.buckets[Bucket] = {"location": CreateBucketConfiguration["LocationConstraint"]}
        self.created.append(Bucket)

    def put_bucket_cors(self, Bucket, CORSConfiguration):
        self.buckets[Bucket]["cors"] = CORSConfiguration

    def put_bucket_lifecycle_configuration(self, Bucket, LifecycleConfiguration):
        self.buckets[Bucket]["lifecycle"] = LifecycleConfiguration

    def put_bucket_notification_configuration(self, Bucket, NotificationConfiguration):
        self.buckets[Bucket]["notification"] = NotificationConfiguration


def test_fresh_run_creates_everything(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()
    values = init.main(ddb, idp, sqs, s3)

    haru = ddb.tables["HaruTable"]
    assert {g["IndexName"] for g in haru["GlobalSecondaryIndexes"]} == {"GSI1", "GSI2"}
    assert ddb.ttl["HaruTable"] == {"Enabled": True, "AttributeName": "ttl"}
    assert ddb.ttl["HaruAgentCheckpoints"] == {"Enabled": True, "AttributeName": "ttl"}
    assert "GlobalSecondaryIndexes" not in ddb.tables["HaruAgentCheckpoints"]

    pool = idp.pools["ap-northeast-2_haruLocal"]
    assert pool["UsernameAttributes"] == ["email"]
    assert {"Name": "nickname", "AttributeDataType": "String", "Mutable": True, "Required": True} in pool["Schema"]
    client = idp.clients["haruLocalWebClient"]
    assert client["GenerateSecret"] is False
    assert set(client["ExplicitAuthFlows"]) == {"ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"}

    nicknames = {u["Username"]: {a["Name"]: a["Value"] for a in u["UserAttributes"]}["nickname"] for u in idp.users.values()}
    assert nicknames == {"jiyeon@example.com": "지연", "suhyun@example.com": "수현", "minjun@example.com": "민준"}
    assert all(p == ("LocalOnly-Passw0rd!", True) for p in idp.passwords.values())
    assert all(u["MessageAction"] == "SUPPRESS" for u in idp.users.values())

    assert values == {
        "LOCAL_USER_POOL_ID": "ap-northeast-2_haruLocal",
        "LOCAL_USER_POOL_CLIENT_ID": "haruLocalWebClient",
        "LOCAL_JWT_ISSUER": "http://localhost:4566/ap-northeast-2_haruLocal",
        "LOCAL_JWKS_URL": "http://aws:4566/ap-northeast-2_haruLocal/.well-known/jwks.json",
        "PHOTO_BUCKET": "haru-photos-local",
        "PHOTO_QUEUE_URL": "http://localhost:4566/000000000000/haru-photo-queue",
        "PHOTO_DLQ_URL": "http://localhost:4566/000000000000/haru-photo-dlq",
    }
    out = capsys.readouterr().out
    for k, v in values.items():
        assert f"{k}={v}" in out
    assert "WARNING" not in out
    assert init.DONE_MARKER.exists()


def test_second_run_skips_existing(init):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()
    init.main(ddb, idp, sqs, s3)
    ddb.created.clear()
    init.main(ddb, idp, sqs, s3)
    assert ddb.created == []
    assert len(idp.pools) == 1 and len(idp.clients) == 1 and len(idp.users) == 3


def test_failed_step_exits_with_step_name(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()

    def boom(**kw):
        raise err("InvalidParameterException")

    idp.create_user_pool_client = boom
    with pytest.raises(SystemExit) as exc:
        init.main(ddb, idp, sqs, s3)
    assert exc.value.code == 1
    assert "FAILED step=ensure_user_pool_client" in capsys.readouterr().out
    assert not init.DONE_MARKER.exists()


def test_override_not_honored_warns_and_reuses_pool(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp(honor_override=False)
    sqs, s3 = FakeSqs(), FakeS3()
    first = init.main(ddb, idp, sqs, s3)
    assert first["LOCAL_USER_POOL_ID"] == "ap-northeast-2_random123"
    assert "WARNING" in capsys.readouterr().out
    init.main(ddb, idp, sqs, s3)  # 다음 실행은 이름으로 기존 풀을 찾아 새로 만들지 않는다
    assert len(idp.pools) == 1


def test_env_example_matches_init_defaults(init):
    env = {}
    for line in (Path(__file__).parents[2] / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    assert env["LOCAL_USER_POOL_ID"] == init.POOL_ID
    assert env["LOCAL_USER_POOL_CLIENT_ID"] == init.CLIENT_NAME
    assert env["SEED_PASSWORD"] == init.SEED_PASSWORD
    assert [(env["SEED_JIYEON_EMAIL"], env["SEED_JIYEON_NICKNAME"])] == init.SEED_USERS[:1]
    assert env["LOCAL_JWT_ISSUER"] == f"{init.PUBLIC_BASE}/{init.POOL_ID}"


def test_photo_resources_match_template(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()
    init.main(ddb, idp, sqs, s3)

    assert sqs.queues["haru-photo-dlq"] == {"MessageRetentionPeriod": "1209600"}
    q = sqs.queues["haru-photo-queue"]
    assert q["VisibilityTimeout"] == "180"
    assert json.loads(q["RedrivePolicy"]) == {"deadLetterTargetArn": "arn:aws:sqs:ap-northeast-2:000000000000:haru-photo-dlq", "maxReceiveCount": 3}

    b = s3.buckets["haru-photos-local"]
    assert b["location"] == "ap-northeast-2"
    (rule,) = b["cors"]["CORSRules"]
    assert rule["AllowedOrigins"] == ["http://localhost:5173"]
    assert rule["AllowedMethods"] == ["PUT", "GET"]
    assert rule["AllowedHeaders"] == ["Content-Type"]
    rules = {r["ID"]: r for r in b["lifecycle"]["Rules"]}
    assert rules["ExpireOriginals"]["Filter"] == {"Prefix": "photos/original/"}
    assert rules["ExpireOriginals"]["Expiration"] == {"Days": 7}
    assert rules["AbortIncompleteUploads"]["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 1}
    (qc,) = b["notification"]["QueueConfigurations"]
    assert qc["QueueArn"].endswith(":haru-photo-queue")
    assert qc["Events"] == ["s3:ObjectCreated:*"]
    assert qc["Filter"]["Key"]["FilterRules"] == [{"Name": "prefix", "Value": "photos/original/"}]

    out = capsys.readouterr().out
    for step in ("create_photo_dlq", "create_photo_queue", "create_photo_bucket", "put_photo_notification"):
        assert f"ok step={step}" in out


def test_photo_steps_idempotent(init):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()
    init.main(ddb, idp, sqs, s3)
    sqs.queues["haru-photo-queue"]["VisibilityTimeout"] = "30"  # 이전 실행에서 다른 값으로 남은 경우
    sqs.created.clear()
    s3.created.clear()
    init.main(ddb, idp, sqs, s3)
    assert sqs.created == [] and s3.created == []
    assert sqs.queues["haru-photo-queue"]["VisibilityTimeout"] == "180"


def test_cors_allows_if_none_match_only_when_switch_on(init, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_IF_NONE_MATCH", "true")
    s3 = FakeS3()
    init.create_photo_bucket(s3)
    assert s3.buckets["haru-photos-local"]["cors"]["CORSRules"][0]["AllowedHeaders"] == ["Content-Type", "If-None-Match"]


def test_photo_step_failure_exits(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()
    sqs, s3 = FakeSqs(), FakeS3()

    def boom(**kw):
        raise err("InvalidArgument")

    s3.put_bucket_notification_configuration = boom
    with pytest.raises(SystemExit):
        init.main(ddb, idp, sqs, s3)
    assert "FAILED step=put_photo_notification" in capsys.readouterr().out
    assert not init.DONE_MARKER.exists()
