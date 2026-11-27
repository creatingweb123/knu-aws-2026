"""최대 크기(40MP) 이미지 처리의 최대 상주 메모리와 시간 (Requirement 7.3, BE-Q56, BE-Q71).

별도 프로세스에서 process_image만 실행해 최대 상주 메모리를 잰다. ru_maxrss는 fork한 부모(pytest)의 값이 exec 뒤에도
남아 정확하지 않으므로, 측정 직전에 /proc/self/clear_refs에 5를 써 최고치를 초기화하고 /proc/self/status의 VmHWM을 읽는다
(Linux 전용). 입력 이미지는 부모 프로세스에서 만들어 파일로 넘긴다. 기준: PhotoProcessorFunction 1024MB의 70%(717MB).
입력은 업로드 한도(10MB) 안에 드는 40MP 이미지다. 잡음이 많은 PNG는 10MB를 넘어 TOO_LARGE로 거부되므로(실제 경로),
PNG는 한도 안에 드는 내용으로 만든다.
기본 실행에서 빠진다(마커 slow). Checkpoint에서 `pytest -m slow`로 반드시 실행한다.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.slow

SRC = Path(__file__).parents[2] / "src"
LIMIT_MB = 1024 * 0.7
CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from domain.photo_image import process_image
def hwm():
    for line in open("/proc/self/status"):
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
data = open(sys.argv[2], "rb").read()
open("/proc/self/clear_refs", "w").write("5")  # 최고 상주 메모리 초기화
base = hwm()
t = time.monotonic()
out = process_image(data)
print(json.dumps({"ms": round((time.monotonic() - t) * 1000), "peak_mb": round(hwm(), 1), "base_mb": round(base, 1), "size": [out.width, out.height]}))
"""


def _measure(tmp_path, im, fmt):
    buf = io.BytesIO()
    im.save(buf, fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    assert len(buf.getvalue()) <= 10_485_760, f"입력 {len(buf.getvalue())}바이트가 업로드 한도를 넘는다"
    f = tmp_path / f"in.{fmt.lower()}"
    f.write_bytes(buf.getvalue())
    r = subprocess.run([sys.executable, "-c", CHILD, str(SRC), str(f)], capture_output=True, text=True, timeout=300, check=True)
    result = json.loads(r.stdout.strip().splitlines()[-1])
    result["input_mb"] = round(len(buf.getvalue()) / 1e6, 2)
    print(f"photo_memory fmt={fmt} {result}")
    return result


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_40mp_peak_memory_under_70_percent(tmp_path, fmt):
    w, h = 8000, 5000  # 정확히 40,000,000픽셀(허용 최대)
    if fmt == "JPEG":
        im = Image.effect_noise((w // 8, h // 8), 40).convert("RGB").resize((w, h))  # 압축이 덜 되는 내용
    else:
        im = Image.linear_gradient("L").resize((w, h)).convert("RGB")  # 10MB 안에 드는 40MP PNG
    r = _measure(tmp_path, im, fmt)
    assert r["size"] == [1600, 1000]
    assert r["peak_mb"] <= LIMIT_MB, r
