"""Property 25–28 (spec backend-stage5-photo-pipeline). 최소 100회.

- P25·P26: 이미지 순수 함수.
- P27: 처리 Lambda와 3단계 완료 트랜잭션의 전달 불변식(moto 상태 기계).
- P28: 업로드 URL 발급·교체(moto).
"""

import io
import warnings

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from PIL import Image

from domain import photo_image as pi

PBT = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow, HealthCheck.data_too_large])


# ------------------------------------------------------------------ P25


@st.composite
def source_images(draw):
    w = draw(st.integers(1, 4000))
    h = draw(st.integers(1, 4000))
    if w * h > 6_000_000:  # 테스트 시간을 위해 큰 이미지는 한 변을 줄인다(1600 경계는 그대로 넘는다)
        h = max(1, 6_000_000 // w)
    mode = draw(st.sampled_from(["RGB", "RGBA", "L", "P"]))
    fmt = "PNG" if mode in ("RGBA", "P") else draw(st.sampled_from(["JPEG", "PNG"]))
    orientation = draw(st.integers(1, 8))
    with_gps = draw(st.booleans())
    im = Image.new(mode, (w, h), draw(st.integers(0, 255)) if mode in ("L", "P") else tuple(draw(st.integers(0, 255)) for _ in mode))
    exif = Image.Exif()
    exif[0x0112] = orientation
    if with_gps:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = "N", (37.0, 33.0, 59.0)
    buf = io.BytesIO()
    im.save(buf, fmt, exif=exif)
    return buf.getvalue(), (w, h), orientation


@PBT
@given(src=source_images())
def test_property25_processed_image_rules(src):
    """Feature: backend-stage5-photo-pipeline, Property 25: 처리본은 크기·형식 규칙을 지키고 메타데이터가 없다.

    Validates: Requirements 7.4, 7.5, 7.6
    """
    data, (w, h), orientation = src
    out = pi.process_image(data)
    im = Image.open(io.BytesIO(out.data))
    assert im.format == "JPEG" and im.mode == "RGB"
    assert max(im.size) <= 1600 and im.size == (out.width, out.height)
    ew, eh = (h, w) if orientation in (5, 6, 7, 8) else (w, h)  # JPEG·PNG 모두 EXIF 방향을 반영한다
    if max(ew, eh) <= 1600:
        assert im.size == (ew, eh)
    else:
        scale = 1600 / max(ew, eh)
        assert abs(im.size[0] - ew * scale) <= 1 and abs(im.size[1] - eh * scale) <= 1
    assert len(im.getexif()) == 0
    for k in ("exif", "icc_profile", "xmp", "comment"):
        assert k not in im.info


# ------------------------------------------------------------------ P26


def _valid(fmt):
    buf = io.BytesIO()
    Image.effect_noise((64, 48), 30).convert("RGB").save(buf, fmt)
    return buf.getvalue()


corrupt_inputs = st.one_of(
    st.binary(max_size=2048),
    st.tuples(st.sampled_from(["JPEG", "PNG"]), st.floats(0, 0.99)).map(lambda t: _valid(t[0])[: int(len(_valid(t[0])) * t[1])]),
    st.tuples(st.sampled_from(["JPEG", "PNG"]), st.binary(min_size=1, max_size=8)).map(lambda t: t[1] + _valid(t[0])[len(t[1]) :]),
    st.tuples(st.sampled_from([b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"]), st.binary(max_size=512)).map(lambda t: t[0] + t[1]),
    st.tuples(st.integers(1, 20_000), st.integers(1, 20_000)).filter(lambda t: t[0] * t[1] > pi.MAX_PIXELS).map(
        lambda t: _bomb_header(*t)
    ),
)


def _bomb_header(w, h):
    """IHDR만 큰 PNG 헤더(픽셀 데이터 없음)."""
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", zlib.crc32(chunk))


@PBT
@given(data=corrupt_inputs)
def test_property26_rejections_are_typed(data):
    """Feature: backend-stage5-photo-pipeline, Property 26: 거부 사유는 입력 결함과 일치하고 예외가 새지 않는다.

    Validates: Requirements 7.1, 7.2, 7.3
    """
    old_max = Image.MAX_IMAGE_PIXELS
    filters_before = list(warnings.filters)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            out = pi.process_image(data)
            assert isinstance(out, pi.ProcessedImage)
        except pi.PhotoRejected as e:
            assert e.code in ("UNSUPPORTED_FORMAT", "TOO_LARGE", "TOO_MANY_PIXELS", "CORRUPT_IMAGE")
            if data[:8] != b"\x89PNG\r\n\x1a\n" and data[:3] != b"\xff\xd8\xff":
                assert e.code == "UNSUPPORTED_FORMAT"
    assert caught == [], [str(w.message) for w in caught]
    assert Image.MAX_IMAGE_PIXELS == old_max and warnings.filters == filters_before
