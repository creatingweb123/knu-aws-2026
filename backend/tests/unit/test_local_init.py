"""local/init/01_haru.py 단계 로직 (가짜 boto3 클라이언트, Docker 없이).

Validates: Requirements 13.2, 13.3, 13.11
"""

import importlib.util
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


def test_fresh_run_creates_everything(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()
    values = init.main(ddb, idp)

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
    }
    out = capsys.readouterr().out
    for k, v in values.items():
        assert f"{k}={v}" in out
    assert "WARNING" not in out
    assert init.DONE_MARKER.exists()


def test_second_run_skips_existing(init):
    ddb, idp = FakeDdb(), FakeIdp()
    init.main(ddb, idp)
    ddb.created.clear()
    init.main(ddb, idp)
    assert ddb.created == []
    assert len(idp.pools) == 1 and len(idp.clients) == 1 and len(idp.users) == 3


def test_failed_step_exits_with_step_name(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp()

    def boom(**kw):
        raise err("InvalidParameterException")

    idp.create_user_pool_client = boom
    with pytest.raises(SystemExit) as exc:
        init.main(ddb, idp)
    assert exc.value.code == 1
    assert "FAILED step=ensure_user_pool_client" in capsys.readouterr().out
    assert not init.DONE_MARKER.exists()


def test_override_not_honored_warns_and_reuses_pool(init, capsys):
    ddb, idp = FakeDdb(), FakeIdp(honor_override=False)
    first = init.main(ddb, idp)
    assert first["LOCAL_USER_POOL_ID"] == "ap-northeast-2_random123"
    assert "WARNING" in capsys.readouterr().out
    init.main(ddb, idp)  # 다음 실행은 이름으로 기존 풀을 찾아 새로 만들지 않는다
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
