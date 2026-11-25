"""domain/photo_image.py: 형식·크기·픽셀 수 검사, 방향 보정, 축소, 메타데이터 제거.

테스트 이미지는 테스트 안에서 Pillow로 만든다(바이너리 픽스처를 늘리지 않는다).

Validates: spec backend-stage5-photo-pipeline Requirements 7.1–7.6, 14.1 (T8, T11의 순수 함수 부분)
"""

import io
import warnings

import pytest
from PIL import Image, ImageCms

from domain import photo_image as pi

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def encode(im, fmt="JPEG", **kw):
    out = io.BytesIO()
    im.save(out, fmt, **kw)
    return out.getvalue()


def gps_exif(orientation=None):
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = (37.0, 33.0, 59.0)
    gps[3] = "E"
    gps[4] = (126.0, 58.0, 41.0)
    if orientation:
        exif[ORIENTATION] = orientation
    return exif


def jpeg_segments(data):
    """JPEG 마커 목록(SOS 전까지)."""
    i, markers = 2, []
    while i < len(data) - 4 and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # SOS
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        markers.append(marker)
        i += 2 + length
    return markers


def assert_clean(data):
    im = Image.open(io.BytesIO(data))
    assert im.format == "JPEG"
    assert len(im.getexif()) == 0
    for k in ("exif", "icc_profile", "xmp", "comment", "photoshop"):
        assert k not in im.info, k
    segs = jpeg_segments(data)
    assert 0xE1 not in segs and 0xE2 not in segs and 0xED not in segs and 0xFE not in segs, [hex(s) for s in segs]


# ------------------------------------------------------------------ 정상 처리


@pytest.mark.parametrize("mode", ["RGB", "L", "CMYK"])
def test_jpeg_modes(mode):
    out = pi.process_image(encode(Image.new(mode, (800, 600))))
    assert (out.width, out.height, out.source_format) == (800, 600, "JPEG")
    assert_clean(out.data)


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "LA", "P", "I;16"])
def test_png_modes(mode):
    im = Image.new(mode, (300, 200))
    out = pi.process_image(encode(im, "PNG"))
    assert (out.width, out.height, out.source_format) == (300, 200, "PNG")
    assert_clean(out.data)


def test_transparent_png_composited_on_white():
    im = Image.new("RGBA", (10, 10), (255, 0, 0, 0))  # 완전 투명한 빨강
    out = Image.open(io.BytesIO(pi.process_image(encode(im, "PNG")).data))
    r, g, b = out.getpixel((5, 5))
    assert min(r, g, b) > 240  # 흰 배경


def test_palette_with_transparency():
    im = Image.new("P", (10, 10), 0)
    im.putpalette([0, 0, 0] * 256)
    data = encode(im, "PNG", transparency=0)
    assert min(Image.open(io.BytesIO(pi.process_image(data).data)).getpixel((1, 1))) > 240


@pytest.mark.parametrize("size,expected", [((4000, 3000), (1600, 1200)), ((1200, 5000), (384, 1600)), ((1600, 900), (1600, 900)), ((1601, 10), (1600, 10)), ((100, 50), (100, 50))])
def test_resize_long_edge(size, expected):
    out = pi.process_image(encode(Image.new("RGB", size)))
    assert abs(out.width - expected[0]) <= 1 and abs(out.height - expected[1]) <= 1
    assert max(out.width, out.height) <= 1600


# 방향 1–8: 원본 왼쪽 위 모서리에 빨간 점을 찍고, 보정 뒤 빨간 점이 있어야 할 모서리
CORNER = {1: "tl", 2: "tr", 3: "br", 4: "bl", 5: "tl", 6: "tr", 7: "br", 8: "bl"}


@pytest.mark.parametrize("orientation", range(1, 9))
def test_exif_orientation_applied(orientation):
    w, h = 400, 200
    im = Image.new("RGB", (w, h), (255, 255, 255))
    im.paste((255, 0, 0), (0, 0, 40, 40))
    out = Image.open(io.BytesIO(pi.process_image(encode(im, exif=gps_exif(orientation), quality=95)).data))
    swapped = orientation in (5, 6, 7, 8)
    assert out.size == ((h, w) if swapped else (w, h))
    ow, oh = out.size
    pts = {"tl": (10, 10), "tr": (ow - 11, 10), "bl": (10, oh - 11), "br": (ow - 11, oh - 11)}
    r, g, b = out.getpixel(pts[CORNER[orientation]])
    assert r > 200 and g < 80 and b < 80, (orientation, out.getpixel(pts[CORNER[orientation]]))
    assert len(out.getexif()) == 0


def test_gps_icc_xmp_comment_removed():
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    src = encode(Image.new("RGB", (640, 480), (10, 120, 200)), exif=gps_exif(), icc_profile=icc, comment=b"secret", xmp=b"<x:xmpmeta>gps</x:xmpmeta>")
    before = Image.open(io.BytesIO(src))
    assert GPS_IFD in before.getexif() and "icc_profile" in before.info  # 입력에는 있다
    out = pi.process_image(src)
    assert_clean(out.data)
    assert b"secret" not in out.data and b"xmpmeta" not in out.data


def test_png_metadata_removed():
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret")
    src = encode(Image.new("RGB", (50, 50)), "PNG", pnginfo=info, exif=gps_exif())
    out = pi.process_image(src)
    assert_clean(out.data)
    assert b"secret" not in out.data


# ------------------------------------------------------------------ 거부


def reject(data):
    with pytest.raises(pi.PhotoRejected) as e:
        pi.process_image(data)
    return e.value.code


def test_too_large():
    assert reject(b"\xff\xd8\xff" + b"\0" * (pi.MAX_BYTES - 2)) == "TOO_LARGE"
    assert len(b"\xff\xd8\xff" + b"\0" * (pi.MAX_BYTES - 3)) == pi.MAX_BYTES  # 경계는 크기 검사를 통과한다


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "WEBP", "TIFF"])
def test_unsupported_formats(fmt):
    assert reject(encode(Image.new("RGB", (10, 10)), fmt)) == "UNSUPPORTED_FORMAT"


def test_magic_bytes_mismatch():
    png = encode(Image.new("RGB", (10, 10)), "PNG")
    assert reject(b"\xff\xd8\xff" + png[3:]) == "CORRUPT_IMAGE"  # JPEG로 보이지만 내용이 다르다
    assert reject(b"") == "UNSUPPORTED_FORMAT"
    assert reject(b"GIF89a....") == "UNSUPPORTED_FORMAT"


@pytest.mark.parametrize("fmt,cut", [("JPEG", 0.5), ("JPEG", 0.9), ("PNG", 0.5), ("JPEG", 4), ("PNG", 16)])
def test_truncated(fmt, cut):
    data = encode(Image.effect_noise((400, 300), 64).convert("RGB"), fmt)
    n = int(len(data) * cut) if isinstance(cut, float) else cut
    assert reject(data[:n]) == "CORRUPT_IMAGE"


def _bomb_png(w, h):
    return encode(Image.new("1", (w, h)), "PNG", optimize=True)  # 실제 데이터는 작고 헤더만 크다


def test_pixel_limit_header_check():
    assert reject(_bomb_png(8000, 5001)) == "TOO_MANY_PIXELS"  # 40,008,000 > 40M (경고 구간)


def test_decompression_bomb_error_path():
    assert reject(_bomb_png(9000, 9000)) == "TOO_MANY_PIXELS"  # 81M > 2 × 40M → DecompressionBombError


def test_bomb_warning_does_not_leak_and_globals_restored():
    old = Image.MAX_IMAGE_PIXELS
    filters_before = list(warnings.filters)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for data in (_bomb_png(8000, 5001), _bomb_png(9000, 9000), encode(Image.new("RGB", (10, 10)), exif=b"Exif\0\0garbage")):
            try:
                pi.process_image(data)
            except pi.PhotoRejected:
                pass
    assert caught == []
    assert Image.MAX_IMAGE_PIXELS == old
    assert warnings.filters == filters_before


def test_exactly_max_pixels_is_accepted():
    out = pi.process_image(_bomb_png(8000, 5000))  # 정확히 40,000,000
    assert max(out.width, out.height) == 1600
