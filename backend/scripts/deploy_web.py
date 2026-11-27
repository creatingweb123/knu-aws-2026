"""프론트엔드 빌드 산출물을 웹 버킷에 올리고 CloudFront 캐시를 무효화한다 (BE-INFRA-02·04, 7단계). 기본은 dry-run이다.

  python scripts/deploy_web.py --stack haru-dev --dist ../frontend/dist                                   # 계획만 출력
  python scripts/deploy_web.py --stack haru-dev --dist ../frontend/dist --apply --confirm-stack haru-dev  # 올리고 무효화
  python scripts/deploy_web.py --stack haru-dev --print-env                                               # 프론트 빌드용 VITE_* 값만 출력

동작
- 스택 출력 `WebBucketName`·`DistributionId`·`ApiUrl`·`UserPoolId`·`UserPoolClientId`를 CloudFormation에서 **읽기만** 한다(dry-run도 읽는다).
- 순서: `assets/`(해시 파일명) 먼저 → 나머지 → `index.html` 마지막. 새 index.html이 아직 없는 자산을 가리키는 순간을 만들지 않는다.
- Cache-Control: `assets/*`는 `public, max-age=31536000, immutable`, 그 밖(index.html 등)은 `no-cache`.
- 버킷에는 dist에 없는 오래된 `assets/` 객체만 `--prune`으로 지운다(기본은 지우지 않는다). `assets/` 밖은 건드리지 않는다.
- `mockServiceWorker.js`(MSW 목업 워커)는 올리지 않는다. 배포 빌드는 `VITE_USE_MOCK=false`다.
- 마지막에 `/*` 무효화 1건(경로 1개)을 만든다.
- `--apply`는 `--confirm-stack`이 `--stack`과 같을 때만 쓴다. 자격 증명·계정 ID는 이 파일에 없다(실행자의 AWS 프로필을 쓴다).
- 출력에는 파일 이름·개수만 남긴다(VITE_* 값은 공개 설정이라 `--print-env`에서만 보인다).
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ASSET_CACHE = "public, max-age=31536000, immutable"
SHELL_CACHE = "no-cache"
EXCLUDE = {"mockServiceWorker.js"}
OUTPUT_KEYS = ("WebBucketName", "DistributionId", "ApiUrl", "UserPoolId", "UserPoolClientId", "DistributionDomain")
EXTRA_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json",
               ".woff2": "font/woff2", ".woff": "font/woff", ".webp": "image/webp", ".ico": "image/x-icon", ".map": "application/json",
               ".webmanifest": "application/manifest+json", ".txt": "text/plain", ".html": "text/html"}


class DeployError(Exception):
    pass


def content_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return EXTRA_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def cache_control(key: str) -> str:
    return ASSET_CACHE if key.startswith("assets/") else SHELL_CACHE


def plan_files(dist: Path) -> list[str]:
    """업로드 순서대로의 키 목록: assets/ → 나머지 → index.html."""
    if not (dist / "index.html").is_file():
        raise DeployError("dist에 index.html이 없다. 먼저 프론트엔드를 빌드한다(npm run build).")
    keys = sorted(p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file() and p.name not in EXCLUDE)
    assets = [k for k in keys if k.startswith("assets/")]
    rest = [k for k in keys if not k.startswith("assets/") and k != "index.html"]
    return assets + rest + ["index.html"]


def stack_outputs(cfn: Any, stack: str) -> dict[str, str]:
    stacks = cfn.describe_stacks(StackName=stack)["Stacks"]
    if not stacks:
        raise DeployError("스택을 찾지 못했다.")
    out = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
    missing = [k for k in ("WebBucketName", "DistributionId") if k not in out]
    if missing:
        raise DeployError(f"스택 출력에 {', '.join(missing)}이(가) 없다. 7단계 템플릿으로 배포된 스택인지 확인한다.")
    return out


def vite_env(outputs: dict[str, str], region: str) -> list[str]:
    """docs/02 §2.4.7 dev/demo 스택 열. 모두 공개 설정이다(비밀값 없음)."""
    return [
        "VITE_USE_MOCK=false",
        f"VITE_API_BASE_URL={outputs.get('ApiUrl', '')}",
        f"VITE_AWS_REGION={region}",
        f"VITE_COGNITO_USER_POOL_ID={outputs.get('UserPoolId', '')}",
        f"VITE_COGNITO_CLIENT_ID={outputs.get('UserPoolClientId', '')}",
        "VITE_COGNITO_ENDPOINT=",
        "VITE_AUTH_MODE=cognito",
    ]


def stale_asset_keys(s3: Any, bucket: str, keep: set[str]) -> list[str]:
    stale: list[str] = []
    token = None
    while True:
        kw: dict[str, Any] = {"Bucket": bucket, "Prefix": "assets/"}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        stale += [o["Key"] for o in page.get("Contents", []) if o["Key"] not in keep]
        if not page.get("IsTruncated"):
            return stale
        token = page["NextContinuationToken"]


def deploy(
    *,
    dist: Path,
    outputs: dict[str, str],
    s3: Any,
    cloudfront: Any,
    apply: bool,
    prune: bool = False,
    now: Any = time.time,
    out: Any = print,
) -> dict[str, Any]:
    keys = plan_files(dist)
    bucket, dist_id = outputs["WebBucketName"], outputs["DistributionId"]
    stale = stale_asset_keys(s3, bucket, set(keys)) if prune else []
    out(f"{'APPLY' if apply else 'DRY-RUN'}: 업로드 {len(keys)}개, 오래된 assets 삭제 {len(stale)}개{'' if prune else '(--prune 없음)'}, 무효화 /*")
    result: dict[str, Any] = {"uploaded": 0, "deleted": 0, "invalidation": None, "keys": keys, "stale": stale}
    if not apply:
        for k in keys:
            out(f"  PUT {k}  [{content_type(k)}; {cache_control(k)}]")
        for k in stale:
            out(f"  DELETE {k}")
        out("아무것도 쓰지 않았다. --apply --confirm-stack <스택>으로 실행한다.")
        return result
    for k in keys:
        s3.put_object(Bucket=bucket, Key=k, Body=(dist / k).read_bytes(), ContentType=content_type(k), CacheControl=cache_control(k))
        result["uploaded"] += 1
    for k in stale:  # 새 index.html이 올라간 뒤에 지운다
        s3.delete_object(Bucket=bucket, Key=k)
        result["deleted"] += 1
    inv = cloudfront.create_invalidation(
        DistributionId=dist_id,
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"deploy-web-{int(now())}"},
    )
    result["invalidation"] = inv["Invalidation"]["Id"]
    out(f"완료: 업로드 {result['uploaded']}, 삭제 {result['deleted']}, 무효화 {result['invalidation']}")
    return result


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="프론트엔드 산출물을 웹 버킷에 올리고 CloudFront를 무효화한다(기본 dry-run).")
    ap.add_argument("--stack", required=True, help="CloudFormation 스택 이름(예: haru-dev)")
    ap.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[2] / "frontend" / "dist")
    ap.add_argument("--apply", action="store_true", help="실제로 올린다(--confirm-stack 필요)")
    ap.add_argument("--confirm-stack", default=None)
    ap.add_argument("--prune", action="store_true", help="dist에 없는 오래된 assets/ 객체를 지운다")
    ap.add_argument("--print-env", action="store_true", help="스택 출력으로 프론트 빌드용 VITE_* 값만 출력한다")
    ap.add_argument("--region", default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.apply and args.confirm_stack != args.stack:
        print("--apply는 --confirm-stack이 --stack과 같아야 한다.", file=sys.stderr)
        return 2
    import boto3

    session = boto3.session.Session(region_name=args.region)
    try:
        outputs = stack_outputs(session.client("cloudformation"), args.stack)
        if args.print_env:
            print("\n".join(vite_env(outputs, session.region_name or "ap-northeast-2")))
            return 0
        deploy(dist=args.dist, outputs=outputs, s3=session.client("s3"), cloudfront=session.client("cloudfront"), apply=args.apply, prune=args.prune)
    except DeployError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
