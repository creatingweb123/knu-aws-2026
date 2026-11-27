"""7단계 웹 호스팅 판정(AWS 담당 실행, `pytest -m integration tests/integration/test_web.py`). 배포 뒤 `scripts/deploy_web.py`로 산출물을 올린 상태가 전제다.

판정 항목(BE-INFRA-02·03·04): 출력값, HTTPS 강제, SPA 라우팅(없는 경로 → index.html 200), 직접 S3 접근 차단(OAC), API·사진 버킷 CORS에 배포 도메인.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import boto3
import pytest

from tests.integration.conftest import REGION

pytestmark = pytest.mark.integration


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, follow: bool = True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@pytest.fixture(scope="module")
def outputs(stack):
    import os

    out = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=os.environ["STACK_NAME"])["Stacks"][0].get("Outputs", [])
    got = {o["OutputKey"]: o["OutputValue"] for o in out}
    for key in ("WebBucketName", "DistributionId", "DistributionDomain"):
        assert key in got, f"스택 출력 {key} 없음"
    return got


def test_outputs_exist_and_distribution_deployed(outputs):
    cf = boto3.client("cloudfront")
    dist = cf.get_distribution(Id=outputs["DistributionId"])["Distribution"]
    assert dist["Status"] == "Deployed" and dist["DomainName"] == outputs["DistributionDomain"]


def test_https_enforced(outputs):
    status, headers, _ = _get(f"http://{outputs['DistributionDomain']}/", follow=False)
    assert status in (301, 302) and headers.get("Location", "").startswith("https://")


def test_index_and_spa_fallback(outputs):
    base = f"https://{outputs['DistributionDomain']}"
    s1, h1, b1 = _get(base + "/")
    assert s1 == 200 and b'id="root"' in b1
    for path in ("/plans/does-not-exist", "/inbox/abc", "/some/deep/link"):
        s, h, b = _get(base + path)
        assert s == 200 and b == b1, f"SPA 라우팅 실패: {path} -> {s}"  # 403/404 → /index.html(200)
    # 캐시 정책: index.html은 CachingDisabled라 매번 원본을 확인한다(원본 Cache-Control: no-cache는 deploy_web.py가 넣는다)
    assert "no-cache" in h1.get("Cache-Control", "").lower()


def test_direct_s3_is_blocked(outputs):
    status, _, _ = _get(f"https://{outputs['WebBucketName']}.s3.{REGION}.amazonaws.com/index.html")
    assert status == 403  # 공개 접근 차단 + OAC 전용


def test_api_cors_allows_distribution_origin(stack, outputs):
    origin = f"https://{outputs['DistributionDomain']}"
    status, headers, _ = _get(stack.api_url + "/me", method="OPTIONS", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert status in (200, 204) and headers.get("access-control-allow-origin") == origin


def test_photo_bucket_cors_includes_distribution_origin(outputs):
    import os

    cfn = boto3.client("cloudformation", region_name=REGION)
    bucket = cfn.describe_stack_resource(StackName=os.environ["STACK_NAME"], LogicalResourceId="PhotoBucket")["StackResourceDetail"]["PhysicalResourceId"]
    rules = boto3.client("s3", region_name=REGION).get_bucket_cors(Bucket=bucket)["CORSRules"]
    assert f"https://{outputs['DistributionDomain']}" in rules[0]["AllowedOrigins"]
