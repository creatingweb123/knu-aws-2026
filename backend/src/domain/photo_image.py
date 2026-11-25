"""사진 검증·축소·메타데이터 제거 순수 함수 (BE-PHOTO-04·05, G7, spec backend-stage5-photo-pipeline Requirement 7).

S3·DynamoDB·환경 변수를 모른다. bytes를 받아 처리본 JPEG bytes를 돌려주거나 PhotoRejected(사유 코드)를 낸다.

- 형식은 확장자·Content-Type이 아니라 매직 바이트로 판정한다(JPEG, PNG).
- 압축 폭탄: 헤더의 가로×세로가 40,000,000을 넘으면 거부한다(BE-Q56). Pillow의 DecompressionBombWarning은
  이 함수 안에서만 오류로 바꾸고, DecompressionBombError도 같은 사유로 본다. 전역 경고 필터와 MAX_IMAGE_PIXELS는
  함수가 끝나면 원래 값으로 돌아간다.
- 메타데이터: EXIF 방향을 픽셀에 반영한 뒤 픽셀만 새 이미지로 옮겨 저장한다. 결과에는 EXIF·GPS·XMP·IPTC·ICC·주석이 없다.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_BYTES = 10_485_760
MAX_PIXELS = 40_000_000
LONG_EDGE = 1600
JPEG_QUALITY = 85  # BE-Q58

UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
TOO_LARGE = "TOO_LARGE"
TOO_MANY_PIXELS = "TOO_MANY_PIXELS"
CORRUPT_IMAGE = "CORRUPT_IMAGE"
RETRY_EXHAUSTED = "RETRY_EXHAUSTED"  # 처리 Lambda가 쓰는 사유(이 함수는 내지 않는다)
REASONS = (UNSUPPORTED_FORMAT, TOO_LARGE, TOO_MANY_PIXELS, CORRUPT_IMAGE, RETRY_EXHAUSTED)  # BE-Q55

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class PhotoRejected(Exception):
    """검사 실패(영구). 재시도하지 않는다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int
    source_format: str  # "JPEG" | "PNG"


def sniff_format(head: bytes) -> str:
    if head.startswith(_JPEG_MAGIC):
        return "JPEG"
    if head.startswith(_PNG_MAGIC):
        return "PNG"
    raise PhotoRejected(UNSUPPORTED_FORMAT)


def _to_rgb(im: Image.Image) -> Image.Image:
    """투명은 흰 배경에 합성하고(BE-Q58), 그 밖의 모드는 RGB로 바꾼다."""
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if im.mode.startswith("I"):  # 16비트·32비트 정수 그레이스케일(PNG)
        return im.convert("I").point(lambda v: v * (1 / 256)).convert("L").convert("RGB")
    if im.mode == "F":
        return im.convert("L").convert("RGB")
    return im.convert("RGB")


def _decode(data: bytes, fmt: str) -> Image.Image:
    im = Image.open(io.BytesIO(data))  # 헤더만 읽는다. 여기서 압축 폭탄 검사가 돈다
    if im.format != fmt:
        raise PhotoRejected(UNSUPPORTED_FORMAT)
    width, height = im.size
    if width * height > MAX_PIXELS:
        raise PhotoRejected(TOO_MANY_PIXELS)
    if fmt == "JPEG":
        im.draft("RGB", (LONG_EDGE, LONG_EDGE))  # DCT 축소 디코딩. 긴 변이 LONG_EDGE 이상으로 남는 배율만 고른다
    im.load()
    return im


def process_image(data: bytes) -> ProcessedImage:
    if len(data) > MAX_BYTES:
        raise PhotoRejected(TOO_LARGE)
    fmt = sniff_format(data[:8])
    old_max = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # 손상 EXIF 등 Pillow 경고가 함수 밖으로 새지 않게 한다
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # 압축 폭탄 경고만 오류로
            try:
                im = _decode(data, fmt)
                im = ImageOps.exif_transpose(im)
                im = _to_rgb(im)
            except PhotoRejected:
                raise
            except (Image.DecompressionBombWarning, Image.DecompressionBombError):
                raise PhotoRejected(TOO_MANY_PIXELS) from None
            except Exception:  # noqa: BLE001  잘린 파일·손상된 데이터·이상한 EXIF 등 디코딩 단계의 모든 실패
                raise PhotoRejected(CORRUPT_IMAGE) from None
            if max(im.size) > LONG_EDGE:
                im.thumbnail((LONG_EDGE, LONG_EDGE), Image.Resampling.LANCZOS)
            clean = Image.new("RGB", im.size)  # 빈 info. 픽셀만 옮겨 모든 메타데이터를 버린다
            clean.paste(im)
            out = io.BytesIO()
            clean.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)  # exif·icc_profile·comment를 넘기지 않는다
    finally:
        Image.MAX_IMAGE_PIXELS = old_max
    return ProcessedImage(out.getvalue(), clean.width, clean.height, fmt)
