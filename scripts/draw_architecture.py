"""이어온 하루 - AI 에이전트(P0) 포함 시스템 아키텍처 다이어그램 생성.

AI_AGENT_PROPOSAL.md 기준. architecture.png 양식(웹 사용자 박스 + AWS 클라우드 박스)을 따른다.
실행: python scripts/draw_architecture.py  ->  docs/images/architecture-ai-agent.png
필요: Pillow, Windows 맑은 고딕 폰트(C:/Windows/Fonts/malgun*.ttf)
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 2000, 1530
OUT = Path(__file__).resolve().parent.parent / "docs" / "images" / "architecture-ai-agent.png"

im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
FONT = "C:/Windows/Fonts/malgun.ttf"
FONT_B = "C:/Windows/Fonts/malgunbd.ttf"
K = (20, 20, 20)
NEW = (200, 30, 60)          # 신규(에이전트) 요소 강조색
NEW_BG = (255, 241, 244)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def text(x, y, s, size=24, bold=False, fill=K, align="center", valign="top"):
    """여러 줄 텍스트. align: center/left/right, valign: top/middle."""
    f = font(size, bold)
    lines = s.split("\n")
    lh = size + 8
    y0 = y - lh * len(lines) / 2 if valign == "middle" else y
    for i, line in enumerate(lines):
        w = d.textlength(line, font=f)
        xx = {"center": x - w / 2, "left": x, "right": x - w}[align]
        d.text((xx, y0 + i * lh), line, font=f, fill=fill)


def head(p, q, col, s=16):
    a = math.atan2(q[1] - p[1], q[0] - p[0])
    d.polygon([q,
               (q[0] - s * math.cos(a - 0.4), q[1] - s * math.sin(a - 0.4)),
               (q[0] - s * math.cos(a + 0.4), q[1] - s * math.sin(a + 0.4))], fill=col)


def seg_dashed(p, q, col, w=3, dash=12, gap=8):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    if L == 0:
        return
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    t = 0
    while t < L:
        e = min(t + dash, L)
        d.line([(p[0] + ux * t, p[1] + uy * t), (p[0] + ux * e, p[1] + uy * e)], fill=col, width=w)
        t += dash + gap


def arrow(pts, dashed=True, col=K, both=False, end=True, w=3):
    for p, q in zip(pts, pts[1:]):
        if dashed:
            seg_dashed(p, q, col, w)
        else:
            d.line([p, q], fill=col, width=w)
    if end:
        head(pts[-2], pts[-1], col)
    if both:
        head(pts[1], pts[0], col)


def icon(cx, cy, col, glyph, label, size=110, gsize=38, label_col=K):
    d.rounded_rectangle([cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2], 14, fill=col)
    text(cx, cy, glyph, gsize, True, "white", valign="middle")
    text(cx, cy + size / 2 + 8, label, 22, fill=label_col)


def dashed_box(x1, y1, x2, y2, col, w=3):
    for p, q in [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]:
        seg_dashed(p, q, col, w, dash=16, gap=10)


# ---------------------------------------------------------------- 사용자
d.ellipse([130, 140, 190, 200], outline=K, width=4)
d.arc([100, 205, 220, 320], 180, 360, fill=K, width=4)
d.line([(100, 262), (220, 262)], fill=K, width=4)
text(160, 280, "사용자", 30, True)
text(160, 322, "(계획자 · 실행자)", 20)
arrow([(250, 180), (440, 180)], dashed=False)
text(345, 140, "서비스 이용", 24)
arrow([(440, 240), (250, 240)], dashed=False)
text(345, 252, "결과 확인", 24)

# ---------------------------------------------------------------- 웹 사용자 박스
d.rectangle([450, 30, 1960, 390], outline=K, width=3)
d.rounded_rectangle([470, 48, 530, 102], 6, fill=(35, 47, 62))
d.rectangle([484, 62, 516, 84], outline="white", width=3)
d.line([(478, 90), (522, 90)], fill="white", width=3)
text(548, 56, "웹 사용자", 28, True, align="left")

cx, cy = 720, 175                      # React 로고
for ang in (0, 60, 120):
    layer = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([15, 72, 205, 148], outline=(0, 200, 240), width=5)
    layer = layer.rotate(ang, resample=Image.BICUBIC)
    im.paste(layer, (cx - 110, cy - 110), layer)
d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=(0, 200, 240))
text(cx, 290, "React 웹 애플리케이션", 30, True)

for i, s in enumerate(["돌려보기 / 하루 등록", "이어받기 / 방문 기록", "수신함 / 답장"]):
    y = 55 + i * 78
    d.rounded_rectangle([960, y, 1340, y + 58], 8, outline=K, width=2)
    text(1150, y + 29, s, 24, valign="middle")
y = 55 + 3 * 78
d.rounded_rectangle([960, y, 1340, y + 58], 8, outline=NEW, width=4, fill=NEW_BG)
text(1150, y + 29, "AI와 함께 정리하기 (화면 3-1)", 24, True, NEW, valign="middle")
arrow([(1340, y + 29), (1400, y + 29)], col=NEW)

d.rounded_rectangle([1400, 60, 1935, 370], 10, outline=NEW, width=2)
text(1420, 75, "신규: AI 하루 카드 정리 (P0)", 22, True, NEW, align="left")
text(1420, 115,
     "• 단계 칩(trace) 애니메이션\n"
     "• 질문 말풍선: 선택지 · 직접 입력 · 건너뛰기\n"
     "• '이대로 카드 받기' (finish=true)\n"
     "• 'AI가 바꾼 것' 메모 · 출처 칩 · 다시 넣기\n"
     "• WORKING → 자동 continue(최대 2회)\n"
     "• 공개는 계획자가 POST /plans 로만", 20, align="left")

# ---------------------------------------------------------------- AWS 클라우드 박스
AWS_BOTTOM = 1450
d.rectangle([220, 430, 1960, AWS_BOTTOM], outline=K, width=3)
d.rounded_rectangle([236, 446, 306, 506], 6, fill=(35, 47, 62))
text(271, 472, "aws", 28, True, "white", valign="middle")
d.arc([250, 474, 292, 500], 20, 160, fill=(255, 153, 0), width=3)
text(324, 452, "AWS 클라우드", 28, True, align="left")
text(324, 492, "ap-northeast-2 · SAM 단일 스택", 18, align="left")

PUR, GRN, PINK = (140, 79, 255), (95, 160, 30), (225, 50, 110)
ORG, BLU, RED, TEAL = (237, 113, 0), (60, 110, 200), (220, 60, 90), (1, 140, 120)

RA = 610                                     # 1행: 기존 서비스
icon(310, RA, PUR, "CF", "Amazon\nCloudFront")
icon(540, RA, GRN, "S3", "Amazon S3\n(정적 파일 / 사진)")
icon(790, RA, PINK, "</>", "Amazon\nAPI Gateway\n(HTTP API)", gsize=34)
icon(1070, RA, ORG, "λ", "AWS Lambda\n(비즈니스 로직)\nPlan · Claim · Inbox", gsize=56)
icon(1350, RA, PINK, "SQS", "Amazon SQS\n(비동기 처리)", gsize=32)
icon(1820, RA, RED, "ID", "Amazon Cognito\n(인증)")

RB = 880                                     # 2행: 저장소 · 모니터링
icon(1070, RB, BLU, "DB", "Amazon DynamoDB (HaruTable)\nPlan · Claim · Inbox\nAiSession(TTL 30일) · AiQuota")
icon(1820, RB, GRN, "CW", "Amazon CloudWatch\n(Agent* 지표 · 알람)")

# 에이전트 영역
ZX1, ZY1, ZX2, ZY2 = 860, 1050, 1945, 1435
dashed_box(ZX1, ZY1, ZX2, ZY2, NEW)
text(915, ZY1 + 6, "AI 하루 카드 정리 에이전트 (신규 · P0)", 24, True, NEW, align="left")

RC = 1170                                    # 3행: 에이전트
icon(1070, RC, ORG, "λ", "AiCardFunction\nPython 3.12 · 27s\nConverse 루프\n+ 서버 게이트", gsize=56)
icon(1650, RC, TEAL, "BR", "Amazon Bedrock\nConverse tool use\nGlobal CRIS\nClaude Haiku 4.5", gsize=36)
icon(1870, RC, TEAL, "GR", "Bedrock\nGuardrails\n(보조 · 선택)", gsize=36)

# 도구 박스 (Lambda 내부 순수 함수)
TX1, TY1, TX2, TY2 = 1230, RC + 10, 1490, RC + 180
d.rounded_rectangle([TX1, TY1, TX2, TY2], 10, outline=NEW, width=2, fill=NEW_BG)
text((TX1 + TX2) / 2, TY1 + 8, "도구 3개 (Lambda 내부)", 20, True, NEW)
for i, (name, desc) in enumerate([("check_draft", "검사 보고서"),
                                  ("ask_planner", "질문 → ASKING"),
                                  ("submit_card", "제출 → READY")]):
    yy = TY1 + 44 + i * 42
    d.rounded_rectangle([TX1 + 10, yy, TX2 - 10, yy + 34], 6, outline=K, width=1, fill="white")
    text(TX1 + 20, yy + 17, name, 18, True, align="left", valign="middle")
    text(TX2 - 18, yy + 17, desc, 16, align="right", valign="middle")

# ---------------------------------------------------------------- 연결선
arrow([(365, RA), (480, RA)])                                   # CF -> S3
arrow([(650, 390), (650, RA), (730, RA)], both=True)            # React <-> API GW
text(662, 396, "API 호출", 22, align="left")
arrow([(790, RA - 60), (790, 525), (1820, 525), (1820, RA - 60)], both=True)   # 인증
text(1300, 492, "JWT 인증", 24)
arrow([(850, RA), (1010, RA)], dashed=False)                    # API GW -> 비즈니스 Lambda
arrow([(1130, RA), (1290, RA)])                                 # Lambda -> SQS
arrow([(1070, 780), (1070, RB - 60)], both=True)                 # Lambda <-> DynamoDB

# API GW -> AiCardFunction (S3와 API GW 사이로 내려감)
arrow([(735, RA + 35), (700, RA + 35), (700, RC), (1010, RC)], dashed=False, col=NEW)
text(690, 860, "/ai/card-sessions*", 20, True, NEW, align="right")
text(690, 890, "POST · turns · GET", 18, fill=NEW, align="right")

# AiCardFunction -> DynamoDB (LeadingKeys)
arrow([(1070, RC - 60), (1070, RC - 68), (895, RC - 68), (895, RB), (1010, RB)], col=NEW)
text(885, 960, "AiSession·AiQuota만\n(IAM LeadingKeys)", 18, fill=NEW, align="right")

# AiCardFunction <-> Bedrock
arrow([(1130, RC - 25), (1590, RC - 25)], dashed=False, col=NEW, both=True)
text(1365, RC - 62, "Converse (toolChoice=any) · 세션당 호출 6회", 18, fill=NEW)
# Lambda <-> 도구
arrow([(1130, RC + 40), (TX1, RC + 40)], col=NEW, both=True)
# check_draft -> ApplyGuardrail
arrow([(1360, TY2), (1360, ZY2 - 18), (1870, ZY2 - 18), (1870, RC + 158)], col=NEW)
text(1615, ZY2 - 50, "ApplyGuardrail (참고 플래그)", 18, fill=NEW)

# 로그·지표 -> CloudWatch
arrow([(1130, RA + 30), (1230, RA + 30), (1230, RB), (1760, RB)])
arrow([(1560, ZY1), (1560, RB)], end=False)
text(1400, RB - 34, "로그 · 지표", 20)

# ---------------------------------------------------------------- 하단 메모
text(220, AWS_BOTTOM + 14,
     "• 에이전트는 Plan을 만들지 않는다. 저장은 계획자가 누르는 POST /plans(비즈니스 Lambda)에서만 일어난다(G6). 이어받기·방문 기록·완료·수신함(G1~G4)은 변경 없음.\n"
     "• 원문 충실도·개인정보 차단은 결정적 코드(find_not_in_source, scan_privacy)가 판정한다. 킬 스위치 AGENT_MODE=pipeline 으로 계약·화면 변경 없이 레벨 0 전환.",
     19, align="left")

im.save(OUT)
print(f"saved: {OUT}")
