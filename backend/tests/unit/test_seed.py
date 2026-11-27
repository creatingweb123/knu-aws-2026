"""scripts/seed.py: moto 대상 멱등성·정리 범위·대상 안전장치."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("moto")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import seed as sd  # noqa: E402

from common import ddb  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

NOW = datetime(2026, 11, 27, 3, 0, tzinfo=timezone.utc)
USERS = sd.fixed_users()


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def scan(t):
    items, kw = [], {}
    while True:
        r = t.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            return items
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def kinds(items):
    out = {}
    for i in items:
        k = i["PK"].split("#")[0] + "/" + i["SK"].split("#")[0]
        out[k] = out.get(k, 0) + 1
    return out


def test_seed_creates_scenario(table):
    r = sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    assert r["plans"] == 9 and r["claims"] == 4 and r["records"] == 4 and r["inbox"] == 2
    k = kinds(scan(table))
    assert k["PLAN/META"] == 9 and k["PLAN/CLAIM"] == 4 and k["PLAN/RECORD"] == 4 and k["USER/INBOX"] == 2 and k["CLAIM/META"] == 4
    statuses = sorted(i["status"] for i in scan(table) if i["SK"] == "META" and i["PK"].startswith("PLAN#"))
    assert statuses == ["CLAIMED", "CLAIMED", "COMPLETED", "COMPLETED", "OPEN", "OPEN", "OPEN", "OPEN", "OPEN"]
    assert all(i.get("seed") == "demo-v1" for i in scan(table) if i["PK"].startswith("PLAN#") and i["SK"] == "META")
    assert sd.get_manifest(table)["status"] == "complete"


def test_seed_shapes_match_api_flow(table):
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    inbox = [i for i in scan(table) if i["SK"].startswith("INBOX#")]
    assert {i["ownerId"] for i in inbox} == {"dev-jiyeon"} and sum(1 for i in inbox if i.get("read")) == 1
    replied = [i for i in inbox if "reply" in i]
    assert len(replied) == 1 and replied[0]["read"] is True
    records = [i for i in scan(table) if i["SK"].startswith("RECORD#")]
    assert sum(1 for r in records if r.get("deliveredAt")) == 2 and sum(1 for r in records if not r.get("deliveredAt")) == 2


def test_seed_is_idempotent(table):
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    before = sorted(map(str, scan(table)))
    r = sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    assert r["skipped"] is True and sorted(map(str, scan(table))) == before


def test_clean_removes_only_seed_data_and_keeps_others(table):
    other = {"PK": "PLAN#realplan", "SK": "META", "planId": "realplan", "ownerId": "real-user", "status": "OPEN"}
    table.put_item(Item=other)
    table.put_item(Item={"PK": "USER#real-user", "SK": "INBOX#real", "ownerId": "real-user"})
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    res = sd.clean(table, {s for s, _ in USERS.values()}, out=lambda *_: None)
    assert res["plans"] == 9 and res["skipped"] == 0
    left = scan(table)
    assert {(i["PK"], i["SK"]) for i in left} == {("PLAN#realplan", "META"), ("USER#real-user", "INBOX#real")}  # 매니페스트도 사라진다


def test_clean_protects_plan_claimed_by_real_user(table):
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    open_plan = next(i for i in scan(table) if i["SK"] == "META" and i.get("status") == "OPEN" and i["PK"].startswith("PLAN#"))
    from common.auth import User
    from domain import claim_service as cs

    cs.claim_plan(open_plan["planId"], User("real-stranger", "낯선이"), NOW)
    res = sd.clean(table, {s for s, _ in USERS.values()}, out=lambda *_: None)
    assert res["skipped"] == 1 and res["plans"] == 8
    assert table.get_item(Key={"PK": open_plan["PK"], "SK": "META"}).get("Item") is not None
    assert sd.get_manifest(table)["planIds"] == [open_plan["planId"]]
    forced = sd.clean(table, {s for s, _ in USERS.values()}, force_foreign=True, out=lambda *_: None)
    assert forced["plans"] == 1 and scan(table) == []


def test_reset_recreates_with_new_ids(table):
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    first = set(sd.get_manifest(table)["planIds"])
    sd.clean(table, {s for s, _ in USERS.values()}, out=lambda *_: None)
    sd.seed(table, USERS, now=NOW, out=lambda *_: None)
    second = set(sd.get_manifest(table)["planIds"])
    assert len(second) == 9 and first.isdisjoint(second)
    assert kinds(scan(table))["PLAN/META"] == 9


def test_clean_without_manifest_does_nothing(table):
    table.put_item(Item={"PK": "PLAN#x", "SK": "META", "planId": "x"})
    res = sd.clean(table, set(), out=lambda *_: None)
    assert res == {"plans": 0, "items": 0, "skipped": 0} and len(scan(table)) == 1


def test_local_endpoint_guard():
    assert sd.check_local_endpoint("http://localhost:4566") and sd.check_local_endpoint("http://aws:4566")
    for bad in ("https://dynamodb.ap-northeast-2.amazonaws.com", "http://10.0.0.5:4566", ""):
        with pytest.raises(sd.SeedError):
            sd.check_local_endpoint(bad)


def test_stack_apply_requires_confirmation_and_no_endpoint_env(monkeypatch, capsys):
    assert sd.main(["--stack", "haru-demo", "--apply"]) == 2
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    assert sd.main(["--stack", "haru-demo"]) == 1
    assert "AWS_ENDPOINT_URL" in capsys.readouterr().err


def test_target_is_required():
    with pytest.raises(SystemExit):
        sd.main([])


def test_reset_and_clean_exclusive():
    assert sd.main(["--local", "--reset", "--clean"]) == 2


class FakeIdp:
    def __init__(self, existing):
        self.users, self.created = dict(existing), []

    def admin_get_user(self, UserPoolId, Username):
        if Username not in self.users:
            err = type("E", (Exception,), {"response": {"Error": {"Code": "UserNotFoundException"}}})
            raise err()
        return {"UserAttributes": [{"Name": "sub", "Value": self.users[Username]}]}

    def admin_create_user(self, **kw):
        self.users[kw["Username"]] = "sub-" + kw["Username"].split("@")[0]
        self.created.append(kw["Username"])

    def admin_set_user_password(self, **kw):
        assert kw["Password"] and kw["Permanent"] is True


def test_users_lookup_and_create_rules(monkeypatch):
    idp = FakeIdp({"jiyeon@example.com": "s1", "suhyun@example.com": "s2", "minjun@example.com": "s3"})
    assert sd.users_by_key(idp, "pool", create=False, password=None)["jiyeon"] == ("s1", "지연")
    missing = FakeIdp({})
    with pytest.raises(sd.SeedError):
        sd.users_by_key(missing, "pool", create=False, password=None)
    with pytest.raises(sd.SeedError, match="SEED_PASSWORD"):
        sd.users_by_key(missing, "pool", create=True, password=None)
    assert len(sd.users_by_key(missing, "pool", create=True, password="x")) == 3 and len(missing.created) == 3


def test_no_real_addresses_or_secrets_in_script():
    import re

    text = Path(sd.__file__).read_text(encoding="utf-8")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    assert emails <= {"jiyeon@example.com", "suhyun@example.com", "minjun@example.com"}


def test_fixed_users_match_frontend_dev_jwt_ids():
    """로컬 프론트 dev-jwt 모드의 시드 인물(frontend/src/auth/devUsers.ts)과 같은 ID여야 시드 데이터가 로그인한 사용자에게 보인다."""
    import re

    ts = (Path(sd.__file__).resolve().parents[2] / "frontend" / "src" / "auth" / "devUsers.ts").read_text(encoding="utf-8")
    front = dict(re.findall(r"userId: '([^']+)', nickname: '([^']+)'", ts))
    assert {sub: nick for sub, nick in sd.fixed_users().values()} == front


def test_scenario_covers_non_walk_activities():
    """시드가 산책 한 가지가 아니라 전시회(장소 1곳)·서점·카페·공원 사진 등 여러 활동을 담는다."""
    keys = {s.key for s in sd.SCENARIO}
    assert {"open-1", "open-4", "active-2", "open-5", "done-2"} <= keys
    assert any(len(s.places) == 1 for s in sd.SCENARIO if s.key == "open-4")
    assert {s.state for s in sd.SCENARIO} >= {"OPEN", "ACTIVE", "DONE", "DONE_REPLIED"}
