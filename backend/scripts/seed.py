"""데모 환경 시드 (BE-OBS-05, BE-NFR-06). 지연·수현·민준과 예시 계획·Claim·Record·InboxItem을 만든다. 기본은 dry-run이다.

  python scripts/seed.py --local                                                   # 로컬(Floci) 대상 계획만 출력
  python scripts/seed.py --local --apply                                           # 로컬에 시드
  python scripts/seed.py --local --apply --reset                                   # 이 스크립트가 만든 데모 데이터만 지우고 다시 만든다
  python scripts/seed.py --stack haru-demo                                         # AWS 스택 대상 계획만(CloudFormation·Cognito를 읽기만 한다)
  python scripts/seed.py --stack haru-demo --apply --confirm-stack haru-demo       # 스택에 시드
  python scripts/seed.py --stack haru-demo --apply --clean --confirm-stack haru-demo  # 데모 데이터만 정리

대상은 `--local` 또는 `--stack` 중 **하나를 명시**해야 한다. 환경 변수만으로 대상을 고르지 않는다.
- `--local`은 엔드포인트(AWS_ENDPOINT_URL, 기본 http://localhost:4566)의 호스트가 localhost·127.0.0.1·aws(compose)·host.docker.internal일 때만 동작한다.
- `--stack`은 AWS_ENDPOINT_URL이 설정돼 있으면 거부한다(에뮬레이터와 실제 스택 혼동 방지). 테이블·유저 풀은 스택에서 읽는다.
  `--apply`에는 `--confirm-stack`이 `--stack`과 같아야 한다.

멱등성과 데이터 보호
- 시드가 만든 항목 목록은 `SEED#demo-v1 / MANIFEST` 항목 하나에 남긴다. 이미 있으면 아무것도 만들지 않는다(재실행 안전).
- `--reset`·`--clean`은 **매니페스트에 적힌 Plan만** 지운다(그 Plan 파티션, ClaimLookup, 완료로 생긴 InboxItem, 멱등 키).
  테이블 전체 스캔·삭제는 하지 않는다. 지울 Plan에 데모 사용자 3명이 아닌 사람의 Claim이 있으면 그 Plan은 지우지 않고 알린다(`--force-foreign`으로만 지운다).
- 시드 Plan에는 `seed = "demo-v1"` 속성이 붙는다. `scripts/report.py`는 기본으로 이 Plan을 성과 집계에서 뺀다. API 응답에는 나오지 않는다.
- 사진 객체는 만들지 않는다(S3에 쓰지 않는다). 사진 시연은 실제 업로드로 한다.

사용자
- 기본: Cognito에서 이메일로 `sub`를 찾는다(`admin_get_user`, 읽기만). 없으면 `--create-users`로 만든다. 새 사용자 비밀번호는 환경 변수 SEED_PASSWORD에서만
  읽고(기본값 없음, 로컬은 init과 같은 예시 값) 출력하지 않는다. 이메일은 SEED_JIYEON_EMAIL 등 환경 변수로 바꾼다(기본 example.com).
- `--users fixed`: Cognito를 쓰지 않고 프론트 dev-jwt 모드의 시드 인물 ID(dev-jiyeon·dev-suhyun·dev-minjun, frontend/src/auth/devUsers.ts)를 쓴다(로컬 전용).
  로컬 프론트가 Cognito 모드면 브라우저가 Floci(localhost:4566)의 CORS에 막히므로 dev-jwt 모드를 쓴다.

출력에는 사용자 ID·토큰·이메일·사연 원문을 남기지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SEED_TAG = "demo-v1"
MANIFEST_KEY = {"PK": f"SEED#{SEED_TAG}", "SK": "MANIFEST"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "aws", "host.docker.internal"}
LOCAL_POOL_ID = "ap-northeast-2_haruLocal"

DEMO_USERS = [  # (key, nickname, email env, default email)
    ("jiyeon", "지연", "SEED_JIYEON_EMAIL", "jiyeon@example.com"),
    ("suhyun", "수현", "SEED_SUHYUN_EMAIL", "suhyun@example.com"),
    ("minjun", "민준", "SEED_MINJUN_EMAIL", "minjun@example.com"),
]


class SeedError(Exception):
    pass


@dataclass(frozen=True)
class Step:
    """시드 시나리오 한 줄. state: OPEN | ACTIVE(글 초안까지) | DONE(완료) | DONE_READ | DONE_REPLIED."""

    key: str
    owner: str
    state: str
    title: str
    summary: str
    reason: str
    minutes: int
    places: tuple[tuple[str, str, str], ...]
    question: str
    story: str
    mode: str = "MANUAL"
    duration_ms: int = 90_000
    claimer: str | None = None
    letter: str | None = None
    reply: str | None = None
    created_days_ago: float = 0.0


SCENARIO: tuple[Step, ...] = (
    Step("open-1", "jiyeon", "OPEN", "이사 전, 마지막 동네 산책", "출근길에 늘 지나치던 빵집과 천변을 천천히 걸어 보는 하루예요.",
         "이삿짐 정리가 길어져서 이 동네를 제대로 둘러보지 못했어요.", 45,
         (("출근길 빵집", "소금빵 사기", "매일 지나치기만 했어요"), ("천변 산책로", "벤치에서 쉬기", "")),
         "어떤 소리가 들렸나요?", "이사 가기 전에 출근길 빵집에서 소금빵을 사고 천변 산책로 벤치에 앉아 보고 싶었어요.", created_days_ago=0.5),
    Step("open-2", "jiyeon", "OPEN", "퇴근길 한강 노을 보기", "퇴근하고 한강에 들러 노을을 보며 잠깐 쉬어 가요.",
         "야근이 이어져서 하늘을 본 기억이 없어요.", 60,
         (("한강공원 잔디밭", "노을 보기", "탁 트여 있어요"),), "오늘 하늘은 무슨 색이었나요?",
         "퇴근길에 한강공원 잔디밭에 앉아 노을을 보고 싶었어요.", mode="AI_EDITED", duration_ms=150_000, created_days_ago=0.4),
    Step("open-3", "suhyun", "OPEN", "합정 골목 책방 한 바퀴", "골목 책방 두 곳을 돌며 마음에 드는 책 한 권을 골라요.",
         "주말마다 가려다 늘 미뤘어요.", 90,
         (("골목 책방", "책 한 권 고르기", ""), ("근처 카페", "책 펼쳐 보기", "")), "고른 책은 무엇이었나요?",
         "합정 골목 책방에서 책을 고르고 근처 카페에서 읽어 보고 싶었어요.", created_days_ago=0.3),
    Step("active-1", "jiyeon", "ACTIVE", "비 오는 날 시장 구경", "비 오는 날의 전통시장에서 따뜻한 간식을 먹어요.",
         "비 오는 날 시장 풍경을 좋아해요.", 50,
         (("전통시장", "호떡 먹기", "비 오는 날 더 좋아요"),), "호떡 맛은 어땠나요?",
         "비 오는 날 전통시장에서 호떡을 먹고 싶었어요.", claimer="suhyun", letter="호떡을 사 먹었는데 속이 아주 뜨거웠어요. 시장 아주머니가 우산을", created_days_ago=1.0),
    Step("done-1", "jiyeon", "DONE", "새벽 공원 달리기", "해가 뜨기 전 공원을 천천히 한 바퀴 돌아요.",
         "아침형 인간이 되어 보고 싶었어요.", 40,
         (("동네 공원", "천천히 달리기", ""),), "새벽 공기는 어땠나요?",
         "새벽에 동네 공원을 천천히 달려 보고 싶었어요.", claimer="minjun", letter="새벽 공원은 생각보다 조용했고 달리는 내내 새소리가 들렸어요.", created_days_ago=5.0),
    Step("done-2", "jiyeon", "DONE_REPLIED", "골목 카페에서 책 한 권", "조용한 골목 카페에서 책을 읽으며 오후를 보내요.",
         "휴대폰 없이 한 시간을 보내고 싶었어요.", 70,
         (("골목 카페", "책 읽기", "창가 자리가 좋아요"),), "어떤 책을 읽었나요?",
         "골목 카페 창가에서 책을 읽고 싶었어요.", claimer="suhyun", letter="창가 자리에서 시집을 읽었어요. 햇빛이 책장에 오래 머물렀어요.",
         reply="덕분에 저도 그 카페에 가 보고 싶어졌어요. 고마워요!", created_days_ago=6.0),
    # 산책이 아닌 활동(장소 1곳·걷지 않는 활동 포함). 서비스는 '실현하지 못한 하루의 양도와 반환'이고 산책은 대표 사례 중 하나다.
    Step("open-4", "suhyun", "OPEN", "일정이 바뀌어 못 간 전시회", "이번 주에 끝나는 사진 전시를 대신 보고 인상 깊은 작품을 알려 주세요.",
         "갑자기 출장이 잡혀서 전시 마지막 주를 놓치게 됐어요.", 80,
         (("시립 미술관 사진 전시", "전시 둘러보기", "관람 시간이 오후 6시까지예요"),), "가장 오래 머문 작품은 무엇이었나요?",
         "보러 가려던 사진 전시가 이번 주에 끝나는데 출장 때문에 못 가게 됐어요. 대신 둘러보고 마음에 남은 작품 이야기를 듣고 싶어요.", created_days_ago=0.2),
    Step("active-2", "minjun", "ACTIVE", "추억이 담긴 서점 방문", "대학 시절 자주 가던 서점에서 지금도 있는 책장을 한 번 둘러봐 주세요.",
         "멀리 이사 와서 그 서점에 가 볼 수 없게 됐어요.", 60,
         (("대학가 오래된 서점", "문학 코너 둘러보기", "계산대 옆 고양이가 있었어요"),), "서점은 어떤 분위기였나요?",
         "대학 시절 자주 가던 서점이 아직 있는지 궁금한데 이제는 너무 멀어서 가 볼 수 없어요.", claimer="jiyeon", letter="서점은 그대로였고 문학 코너 맨 아래 칸에 오래된 시집이 아직 꽂혀 있었어요. 고양이는", created_days_ago=1.5),
    Step("open-5", "minjun", "OPEN", "공원에서 사진 찍고 쉬기", "공원 벤치에서 잠깐 쉬며 단풍 사진을 한 장 남겨 주세요.",
         "단풍이 지기 전에 사진을 남기고 싶었는데 몸살이 났어요.", 40,
         (("시민공원 단풍길", "단풍 사진 찍기", "해 질 무렵이 예뻐요"),), "공원은 어떤 모습이었나요?",
         "단풍이 한창일 때 공원에서 사진을 찍고 벤치에 앉아 쉬고 싶었는데 몸살로 못 나갔어요.", created_days_ago=0.1),
)


# ---------------------------------------------------------------------------
# 대상 해석
# ---------------------------------------------------------------------------


def check_local_endpoint(endpoint: str) -> str:
    host = urlparse(endpoint).hostname or ""
    if host not in LOCAL_HOSTS:
        raise SeedError(f"--local은 로컬 엔드포인트만 쓴다(localhost·127.0.0.1·aws). 받은 호스트: {host or '없음'}")
    return endpoint


def users_by_key(idp: Any, pool_id: str, *, create: bool, password: str | None) -> dict[str, tuple[str, str]]:
    """{key: (sub, nickname)}. 읽기만 하고, 없을 때만 --create-users로 만든다."""
    out: dict[str, tuple[str, str]] = {}
    for key, nickname, env, default in DEMO_USERS:
        email = os.environ.get(env, default)
        try:
            resp = idp.admin_get_user(UserPoolId=pool_id, Username=email)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "response", {}).get("Error", {}).get("Code") != "UserNotFoundException":
                raise
            if not create:
                raise SeedError(f"데모 사용자({key})가 유저 풀에 없다. --create-users로 만들거나 풀을 확인한다.") from None
            if not password:
                raise SeedError("사용자를 만들려면 환경 변수 SEED_PASSWORD가 필요하다(저장소에 비밀번호를 두지 않는다).") from None
            idp.admin_create_user(UserPoolId=pool_id, Username=email, MessageAction="SUPPRESS", UserAttributes=[
                {"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "nickname", "Value": nickname}])
            idp.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=password, Permanent=True)
            resp = idp.admin_get_user(UserPoolId=pool_id, Username=email)
        sub = next((a["Value"] for a in resp.get("UserAttributes", []) if a["Name"] == "sub"), None)
        if not sub:
            raise SeedError(f"{key}의 sub를 읽지 못했다.")
        out[key] = (sub, nickname)
    return out


def fixed_users() -> dict[str, tuple[str, str]]:
    return {key: (f"dev-{key}", nickname) for key, nickname, _, _ in DEMO_USERS}


# ---------------------------------------------------------------------------
# 시드·정리 (대상 테이블은 common.ddb.use_table로 이미 정해져 있다)
# ---------------------------------------------------------------------------


def get_manifest(table: Any) -> dict[str, Any] | None:
    return table.get_item(Key=MANIFEST_KEY, ConsistentRead=True).get("Item")


def _query_partition(table: Any, pk: str) -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    items: list[dict[str, Any]] = []
    start = None
    while True:
        kw: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(pk), "ConsistentRead": True}
        if start:
            kw["ExclusiveStartKey"] = start
        resp = table.query(**kw)
        items += resp.get("Items", [])
        start = resp.get("LastEvaluatedKey")
        if not start:
            return items


def clean(table: Any, user_ids: set[str], *, force_foreign: bool = False, out: Any = print) -> dict[str, int]:
    """매니페스트에 적힌 Plan만 지운다. 데모 사용자 밖의 Claim이 있는 Plan은 건너뛴다(force_foreign이면 지운다)."""
    manifest = get_manifest(table)
    result = {"plans": 0, "items": 0, "skipped": 0}
    if manifest is None:
        out("정리할 데모 데이터가 없다(매니페스트 없음).")
        return result
    remaining: list[str] = []
    for pid in manifest.get("planIds", []):
        partition = _query_partition(table, f"PLAN#{pid}")
        claims = [i for i in partition if str(i.get("SK", "")).startswith("CLAIM#")]
        if not force_foreign and any(c.get("claimerId") not in user_ids for c in claims):
            out(f"건너뜀: 데모 사용자가 아닌 사람의 Claim이 있는 Plan({pid[:8]}). --force-foreign으로만 지운다.")
            result["skipped"] += 1
            remaining.append(pid)
            continue
        keys = [{"PK": i["PK"], "SK": i["SK"]} for i in partition]
        owner = next((i.get("ownerId") for i in partition if i.get("SK") == "META"), None)
        for c in claims:
            cid = c["claimId"]
            keys.append({"PK": f"CLAIM#{cid}", "SK": "META"})  # ClaimLookup
            if owner:
                keys.append({"PK": f"USER#{owner}", "SK": f"INBOX#{cid}"})
        idem = (manifest.get("idemKeys") or {}).get(pid)
        if idem:
            keys.append({"PK": idem, "SK": "META"})
        with table.batch_writer() as bw:
            for k in keys:
                bw.delete_item(Key=k)
        result["plans"] += 1
        result["items"] += len(keys)
    if remaining:
        table.update_item(Key=MANIFEST_KEY, UpdateExpression="SET planIds = :p, #st = :s",
                          ExpressionAttributeNames={"#st": "status"}, ExpressionAttributeValues={":p": remaining, ":s": "partial"})
    else:
        table.delete_item(Key=MANIFEST_KEY)
    out(f"정리: Plan {result['plans']}건, 항목 {result['items']}개, 건너뜀 {result['skipped']}건")
    return result


def seed(table: Any, users: dict[str, tuple[str, str]], *, now: datetime | None = None, out: Any = print) -> dict[str, Any]:
    """매니페스트가 없을 때만 만든다. 서비스 계층(plan_service·claim_service·inbox_service)을 그대로 써서 실제 API와 같은 항목 모양을 만든다."""
    from common.auth import User
    from common.responses import iso_utc
    from common.validation import PlanCreate
    from domain import claim_service as cs
    from domain import inbox_service as inbox
    from domain import plan_service as ps

    existing = get_manifest(table)
    if existing is not None:
        out(f"이미 시드돼 있다(상태 {existing.get('status')}, Plan {len(existing.get('planIds', []))}건). 아무것도 만들지 않았다. 다시 만들려면 --reset.")
        return {"created": 0, "skipped": True}
    now = now or datetime.now(timezone.utc)
    U = {k: User(sub, nick) for k, (sub, nick) in users.items()}
    manifest = {**MANIFEST_KEY, "tag": SEED_TAG, "createdAt": iso_utc(now), "status": "partial", "planIds": [], "idemKeys": {}}
    table.put_item(Item=manifest, ConditionExpression="attribute_not_exists(PK)")
    counts = {"plans": 0, "claims": 0, "records": 0, "inbox": 0}
    for step in SCENARIO:
        created = now - timedelta(days=step.created_days_ago)
        body = PlanCreate.model_validate({
            "title": step.title, "summary": step.summary, "reason": step.reason, "estimatedMinutes": step.minutes,
            "places": [{"name": n, "activity": a, "whyChosen": w} for n, a, w in step.places], "question": step.question,
            "authoring": {"mode": step.mode, "durationMs": step.duration_ms, "story": step.story},
        })
        idem = f"seed-{SEED_TAG}-{step.key}"
        plan, _ = ps.create_plan(U[step.owner], idem, body, created)
        pid = plan["planId"]
        table.update_item(Key={"PK": f"PLAN#{pid}", "SK": "META"}, UpdateExpression="SET seed = :t", ExpressionAttributeValues={":t": SEED_TAG})
        manifest["planIds"].append(pid)
        manifest["idemKeys"][pid] = f"IDEM#{U[step.owner].id}#{idem}"
        table.update_item(Key=MANIFEST_KEY, UpdateExpression="SET planIds = :p, idemKeys = :k",
                          ExpressionAttributeValues={":p": manifest["planIds"], ":k": manifest["idemKeys"]})
        counts["plans"] += 1
        if step.state == "OPEN":
            continue
        claimer = U[step.claimer]
        claimed_at = created + timedelta(hours=3)
        claim, _ = cs.claim_plan(pid, claimer, claimed_at)
        counts["claims"] += 1
        cid = claim["claimId"]
        cs.put_record(cid, claimer, step.letter, claimed_at + timedelta(hours=2))
        counts["records"] += 1
        if step.state == "ACTIVE":
            continue
        done_at = claimed_at + timedelta(hours=6)
        cs.complete_claim(cid, cs.TEXT_ONLY, now=done_at)
        counts["inbox"] += 1
        if step.state == "DONE_REPLIED":
            inbox.mark_read(cid, U[step.owner])
            inbox.reply(cid, U[step.owner], step.reply, done_at + timedelta(hours=4))
    table.update_item(Key=MANIFEST_KEY, UpdateExpression="SET #st = :c", ExpressionAttributeNames={"#st": "status"}, ExpressionAttributeValues={":c": "complete"})
    out(f"시드 완료: Plan {counts['plans']}, Claim {counts['claims']}, Record {counts['records']}, InboxItem {counts['inbox']}")
    return {"created": counts["plans"], "skipped": False, **counts}


def describe_plan(out: Any = print) -> None:
    out(f"시나리오 {len(SCENARIO)}건 (태그 {SEED_TAG}):")
    for s in SCENARIO:
        who = f", 실행자 {s.claimer}" if s.claimer else ""
        out(f"  - {s.key}: 계획자 {s.owner}, 상태 {s.state}{who}, 작성 {s.mode}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="데모 데이터 시드(기본 dry-run).", formatter_class=argparse.RawDescriptionHelpFormatter)
    tgt = ap.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--local", action="store_true", help="로컬 에뮬레이터(Floci) 대상")
    tgt.add_argument("--stack", help="CloudFormation 스택 이름(예: haru-demo)")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다")
    ap.add_argument("--confirm-stack", help="--stack과 --apply를 같이 쓸 때 --stack과 같은 값")
    ap.add_argument("--reset", action="store_true", help="매니페스트에 적힌 데모 데이터만 지우고 다시 만든다")
    ap.add_argument("--clean", action="store_true", help="데모 데이터만 지운다(다시 만들지 않는다)")
    ap.add_argument("--force-foreign", action="store_true", help="데모 사용자가 아닌 사람의 Claim이 있는 시드 Plan도 지운다")
    ap.add_argument("--users", choices=("cognito", "fixed"), default="cognito")
    ap.add_argument("--create-users", action="store_true", help="유저 풀에 없는 데모 사용자를 만든다(SEED_PASSWORD 필요)")
    ap.add_argument("--region", default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.reset and args.clean:
        print("--reset과 --clean은 같이 쓸 수 없다.", file=sys.stderr)
        return 2
    if args.stack and args.apply and args.confirm_stack != args.stack:
        print("--stack으로 --apply하려면 --confirm-stack이 --stack과 같아야 한다.", file=sys.stderr)
        return 2
    import boto3

    try:
        if args.local:
            endpoint = check_local_endpoint(os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"))
            os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
            os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
            region = args.region or os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2")
            session = boto3.session.Session(region_name=region)
            kw: dict[str, Any] = {"endpoint_url": endpoint}
            table_name = os.environ.get("TABLE_NAME", "HaruTable")
            pool_id = os.environ.get("LOCAL_USER_POOL_ID", LOCAL_POOL_ID)
            target = f"local({urlparse(endpoint).hostname}) table={table_name}"
        else:
            if os.environ.get("AWS_ENDPOINT_URL"):
                raise SeedError("AWS_ENDPOINT_URL이 설정돼 있다. --stack은 실제 스택 대상이라 에뮬레이터 설정과 같이 쓰지 않는다.")
            session = boto3.session.Session(region_name=args.region)
            region, kw = session.region_name, {}
            cfn = session.client("cloudformation")
            table_name = cfn.describe_stack_resource(StackName=args.stack, LogicalResourceId="HaruTable")["StackResourceDetail"]["PhysicalResourceId"]
            stacks = cfn.describe_stacks(StackName=args.stack)["Stacks"]
            pool_id = next((o["OutputValue"] for o in stacks[0].get("Outputs", []) if o["OutputKey"] == "UserPoolId"), "")
            target = f"stack={args.stack} table={table_name} region={region}"
        print(f"{'APPLY' if args.apply else 'DRY-RUN'} 대상: {target}")
        os.environ["TABLE_NAME"] = table_name
        table = session.resource("dynamodb", **kw).Table(table_name)
        from common import ddb

        ddb.use_table(table)
        manifest = get_manifest(table)
        print(f"매니페스트: {'있음(' + str(manifest.get('status')) + ')' if manifest else '없음'}")
        if not args.apply:
            describe_plan()
            print("아무것도 쓰지 않았다. --apply로 실행한다." + ("" if manifest is None or args.reset or args.clean else " 이미 시드돼 있어 --reset 없이는 건너뛴다."))
            return 0
        if args.users == "fixed":
            if not args.local:
                raise SeedError("--users fixed는 --local에서만 쓴다.")
            users = fixed_users()
        else:
            idp = session.client("cognito-idp", **kw)
            password = os.environ.get("SEED_PASSWORD") or ("LocalOnly-Passw0rd!" if args.local else None)
            users = users_by_key(idp, pool_id, create=args.create_users, password=password)
        user_ids = {sub for sub, _ in users.values()}
        if args.reset or args.clean:
            clean(table, user_ids, force_foreign=args.force_foreign)
        if not args.clean:
            seed(table, users)
    except SeedError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
