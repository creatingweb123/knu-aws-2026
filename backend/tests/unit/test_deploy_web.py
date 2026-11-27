"""scripts/deploy_web.py: 실제 AWS 없이 moto S3와 가짜 CloudFormation·CloudFront로 확인한다."""

import sys
from pathlib import Path

import boto3
import pytest

pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import deploy_web as dw  # noqa: E402

OUTPUTS = {"WebBucketName": "web-bucket", "DistributionId": "EDIST", "ApiUrl": "https://api.example", "UserPoolId": "pool", "UserPoolClientId": "client"}


class FakeCloudFront:
    def __init__(self):
        self.calls = []

    def create_invalidation(self, **kw):
        self.calls.append(kw)
        return {"Invalidation": {"Id": "INV1"}}


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html></html>")
    (d / "assets" / "app-abc123.js").write_text("console.log(1)")
    (d / "assets" / "app-abc123.css").write_text("a{}")
    (d / "favicon.svg").write_text("<svg/>")
    (d / "mockServiceWorker.js").write_text("// msw")
    return d


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        c = boto3.client("s3", region_name="ap-northeast-2")
        c.create_bucket(Bucket="web-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield c


def test_plan_order_assets_first_index_last(dist):
    keys = dw.plan_files(dist)
    assert keys[-1] == "index.html" and keys[:2] == ["assets/app-abc123.css", "assets/app-abc123.js"]
    assert "mockServiceWorker.js" not in keys


def test_missing_index_html_is_error(tmp_path):
    with pytest.raises(dw.DeployError):
        dw.plan_files(tmp_path)


def test_dry_run_writes_nothing(dist, s3):
    cf = FakeCloudFront()
    lines = []
    r = dw.deploy(dist=dist, outputs=OUTPUTS, s3=s3, cloudfront=cf, apply=False, out=lines.append)
    assert r["uploaded"] == 0 and cf.calls == [] and "Contents" not in s3.list_objects_v2(Bucket="web-bucket")
    assert any("DRY-RUN" in x for x in lines)


def test_apply_uploads_with_cache_headers_and_invalidates(dist, s3):
    cf = FakeCloudFront()
    r = dw.deploy(dist=dist, outputs=OUTPUTS, s3=s3, cloudfront=cf, apply=True, now=lambda: 1700000000, out=lambda *_: None)
    assert r["uploaded"] == 4 and r["invalidation"] == "INV1"
    js = s3.head_object(Bucket="web-bucket", Key="assets/app-abc123.js")
    assert js["CacheControl"] == dw.ASSET_CACHE and js["ContentType"] == "text/javascript"
    idx = s3.head_object(Bucket="web-bucket", Key="index.html")
    assert idx["CacheControl"] == "no-cache" and idx["ContentType"] == "text/html"
    assert s3.head_object(Bucket="web-bucket", Key="favicon.svg")["ContentType"] == "image/svg+xml"
    (call,) = cf.calls
    assert call["DistributionId"] == "EDIST" and call["InvalidationBatch"]["Paths"] == {"Quantity": 1, "Items": ["/*"]}
    assert call["InvalidationBatch"]["CallerReference"] == "deploy-web-1700000000"


def test_prune_only_deletes_stale_assets(dist, s3):
    for key in ("assets/old-1.js", "assets/app-abc123.js", "other/keep.txt", "index.html"):
        s3.put_object(Bucket="web-bucket", Key=key, Body=b"x")
    cf = FakeCloudFront()
    r = dw.deploy(dist=dist, outputs=OUTPUTS, s3=s3, cloudfront=cf, apply=True, prune=True, out=lambda *_: None)
    keys = {o["Key"] for o in s3.list_objects_v2(Bucket="web-bucket")["Contents"]}
    assert r["deleted"] == 1 and "assets/old-1.js" not in keys and "other/keep.txt" in keys  # assets/ 밖은 그대로


def test_no_prune_by_default(dist, s3):
    s3.put_object(Bucket="web-bucket", Key="assets/old-1.js", Body=b"x")
    dw.deploy(dist=dist, outputs=OUTPUTS, s3=s3, cloudfront=FakeCloudFront(), apply=True, out=lambda *_: None)
    assert "assets/old-1.js" in {o["Key"] for o in s3.list_objects_v2(Bucket="web-bucket")["Contents"]}


def test_stack_outputs_requires_web_keys():
    class Cfn:
        def describe_stacks(self, StackName):
            return {"Stacks": [{"Outputs": [{"OutputKey": "ApiUrl", "OutputValue": "x"}]}]}

    with pytest.raises(dw.DeployError, match="WebBucketName"):
        dw.stack_outputs(Cfn(), "haru-dev")


def test_vite_env_has_no_secrets():
    env = dw.vite_env(OUTPUTS, "ap-northeast-2")
    assert "VITE_USE_MOCK=false" in env and "VITE_API_BASE_URL=https://api.example" in env and "VITE_AUTH_MODE=cognito" in env
    assert not any("KEY" in e.split("=")[0] and "CLIENT" not in e.split("=")[0] for e in env)


def test_apply_requires_matching_confirmation(capsys):
    assert dw.main(["--stack", "haru-dev", "--apply"]) == 2
    assert dw.main(["--stack", "haru-dev", "--apply", "--confirm-stack", "haru-demo"]) == 2
