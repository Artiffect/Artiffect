"""프로필 사진 → 색이 들어간 ASCII 아트.

흑백 선화는 밀도 글자( .:-=+*#%@)로, 분홍·라벤더 붓질은 붓질 색 정보와 함께,
붓질 위에 그려진 검은 '>_' 기호는 "SYMBOL"로 표시한다.

    cells(path, cols, rows) -> [[(글자, 종류), ...], ...]
      종류: None = 잉크(테마 글자색) / "#rrggbb" = 붓질 색 / "SYMBOL" = 붓질 위 기호

미리 보기: python scripts/ascii_art.py data/avatar.png
"""
import colorsys
import sys

from PIL import Image

RAMP = " .:-=+*#%@"
SUB = 4  # 한 글자 칸을 SUB x SUB 픽셀로 보고 평균을 낸다

# 프사 붓질에서 뽑은 색. 칸의 평균색을 이 중 가장 가까운 색으로 맞춘다.
BRUSH_PALETTE = ["#fcb4d4", "#fc84c8", "#e43c9c", "#cc2484", "#a97be6", "#c9a3f2"]


def _nearest(rgb):
    def dist(hx):
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        return (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
    return min(BRUSH_PALETTE, key=dist)


def _cell(px, cx, cy):
    """한 글자 칸(SUB x SUB 픽셀)을 글자 하나로 바꾼다."""
    ink, brush = [], []
    for y in range(cy * SUB, cy * SUB + SUB):
        for x in range(cx * SUB, cx * SUB + SUB):
            r, g, b = px[x, y]
            _, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if sat > .35 and .25 < light < .93:
                brush.append((r, g, b))
            else:
                ink.append(1 - (0.299 * r + 0.587 * g + 0.114 * b) / 255)

    # 붓질 칸: 원래 색을 기억하고, 진할수록 빽빽한 글자
    if len(brush) >= SUB * SUB * .4:
        avg = tuple(sum(c[i] for c in brush) // len(brush) for i in range(3))
        light = colorsys.rgb_to_hls(*(v / 255 for v in avg))[1]
        return RAMP[min(len(RAMP) - 1, 5 + round((1 - light) * 6))], _nearest(avg)

    # 선화 칸: 평균 진하기 + 가장 진한 점을 조금 더해 얇은 선도 살린다
    d = sum(ink) / len(ink) if ink else 0
    peak = max(ink) if ink else 0
    v = min(1.0, d * 1.25 + peak * .1)
    if v < .14:
        return " ", None
    return RAMP[min(len(RAMP) - 1, 1 + int(v * (len(RAMP) - 1)))], None


def _mark_symbol(line, reach=10):
    """붓질 사이에 낀 진한 글자 = 붓질 위에 그려진 검은 '>_' 기호."""
    brush_idx = [i for i, (_, c) in enumerate(line) if c and c != "SYMBOL"]
    for i, (ch, c) in enumerate(line):
        if c is None and ch in "#%@*" \
                and any(0 < i - j <= reach for j in brush_idx) \
                and any(0 < j - i <= reach for j in brush_idx):
            line[i] = (ch, "SYMBOL")


def cells(path, cols=68, rows=38):
    img = Image.open(path).convert("RGB").resize((cols * SUB, rows * SUB), Image.LANCZOS)
    px = img.load()
    out = []
    for cy in range(rows):
        line = [_cell(px, cx, cy) for cx in range(cols)]
        _mark_symbol(line)
        out.append(line)
    return out


if __name__ == "__main__":
    for line in cells(sys.argv[1]):
        print("".join(ch for ch, _ in line))
