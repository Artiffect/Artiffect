"""data/ 와 profile.yml 을 읽어 assets/ 에 터미널 스타일 SVG를 그린다.

    assets/hero-{dark,light}.svg      상단 터미널 (Last login + 파워라인 프롬프트 + neofetch + 프사 ASCII)
    assets/btop-{dark,light}.svg      btop (잔디 그래프 · 언어 비율 · 최근 저장소)
    assets/h01-{dark,light}.svg ...   섹션 제목 (파워라인 칸)
    assets/stack-{dark,light}.svg     기술 스택 (카테고리별 아이콘 줄)
    assets/gitlog-{dark,light}.svg    최근 공개 커밋 (git log)
    assets/spotify-{dark,light}.svg   마지막으로 들은 곡 (플레이어)
    assets/footer-{dark,light}.svg    마무리 (exit)

규칙: 터미널 글자는 전부 같은 고정폭 글꼴 · 14px · 같은 줄 간격. 분홍은 프롬프트와 포인트에만.
실행: python scripts/render.py
"""
import datetime as dt
import itertools
import json
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from ascii_art import cells

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "assets"
KST = ZoneInfo("Asia/Seoul")

MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace'
FS, CW = 14, 8.4                     # 터미널 글자 크기, 글자 폭(고정폭 0.6em)
W = 900                              # 모든 SVG 너비
ART_COLS, ART_ROWS = 68, 38          # 프사 ASCII 칸 수
ART_FS, ART_LH, ART_CW = 7, 7.4, 4.2 # ASCII 글자 크기, 줄 간격, 글자 폭

THEMES = {
    "dark": dict(
        bg="#161616", bar="#262626", barline="#0a0a0a", title="#9a9a9a", line="#333333", track="#2e2e2e", hl="#262626",
        fg="#e6e6e6", dim="#7a7a7a", pink="#f08ac0", lav="#c3a6e6",
        seg1="#f08ac0", seg2="#c3a6e6", seg3="#3a3a3a", segfg="#161616", seg3fg="#e6e6e6",
        heat=("#8a6fc4", "#d39ad8", "#f08ac0"), panels=("#f08ac0", "#c3a6e6", "#7a7a7a"),
        langs=("#f08ac0", "#c3a6e6", "#f7c1dc", "#9a7fd0", "#cfcfcf"),
        art="#cfcfcf", symbol="#161616", brush=("#fc9ccc", "#e43c9c", "#a97be6"),
    ),
    "light": dict(
        bg="#ffffff", bar="#ececec", barline="#d0d0d0", title="#6a6a6a", line="#d0d0d0", track="#e3e3e3", hl="#f0f0f0",
        fg="#1f1f1f", dim="#8a8a8a", pink="#c8458a", lav="#7b5fb5",
        seg1="#f08ac0", seg2="#c3a6e6", seg3="#e3e3e3", segfg="#1f1f1f", seg3fg="#1f1f1f",
        heat=("#b9a3e0", "#d978b0", "#c8458a"), panels=("#c8458a", "#7b5fb5", "#9a9a9a"),
        langs=("#c8458a", "#7b5fb5", "#e58fbb", "#5e4a8f", "#4a4a4a"),
        art="#2a2a2a", symbol="#1f1f1f", brush=("#f08ac0", "#d1508f", "#9b6fd6"),  # 흰 바탕용으로 붓질을 진하게
    ),
}
ANSI = ("#3a3a3a", "#e06c75", "#98c379", "#e5c07b", "#61afef", "#f08ac0", "#56b6c2", "#dcdcdc")  # neofetch 색 블록
ART_STEP = {"#fcb4d4": 0, "#c9a3f2": 0, "#fc84c8": 1, "#a97be6": 1, "#e43c9c": 2, "#cc2484": 2}  # 붓질 6색 → 3단

_uid = itertools.count()


# ================================================================ 기본 조각
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def width(s):
    """터미널 칸 수. 한글·한자 같은 넓은 글자는 실제 터미널처럼 2칸으로 센다."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(s))


def clip(s, cells):
    """칸 수 기준으로 자르고, 잘렸으면 끝에 … 를 붙인다."""
    s = str(s)
    if width(s) <= cells:
        return s
    out, used = "", 0
    for ch in s:
        w = width(ch)
        if used + w > cells - 1:
            break
        out, used = out + ch, used + w
    return out + "…"


def pad(s, cells):
    """칸 수 기준 왼쪽 정렬 (f-string 의 :<n 은 한글 폭을 모른다)."""
    s = clip(s, cells)
    return s + " " * (cells - width(s))


def text(x, y, parts, delay=None, anchor=None, size=None):
    """parts: [(글자, 색, 굵게?)] 를 한 줄로. delay 가 있으면 그 시각에 나타난다.
    size 를 주면 터미널 기본(14px) 대신 그 크기로 (카드의 작은 글자용)."""
    cls = "m" if size else "m t"
    if delay is not None:
        cls += " out"
    st = f' style="animation-delay: {delay:.2f}s"' if delay is not None else ""
    an = f' text-anchor="{anchor}"' if anchor else ""
    fs = f' font-size="{size}"' if size else ""
    inner = "".join(f'<tspan fill="{c}"{" font-weight=\"700\"" if b else ""}>{esc(s)}</tspan>' for s, c, b in parts)
    return f'<text class="{cls}" x="{x:.1f}" y="{y}" xml:space="preserve"{fs}{an}{st}>{inner}</text>'


def typed(t, x, y, s, delay, dur):
    """명령어 타이핑: 배경색 덮개를 한 글자씩 오른쪽으로 민다."""
    n, k = len(s), next(_uid)
    w = n * CW + 4
    return (text(x, y, [(s, t["fg"], False)]) +
            f'<rect class="cover" x="{x - 1:.1f}" y="{y - 15}" width="{w:.0f}" height="20" fill="{t["bg"]}" '
            f'style="animation: k{k} {dur}s steps({n}) {delay}s both"/>'
            f'<style>@keyframes k{k} {{ to {{ transform: translateX({w:.0f}px); }} }}</style>')


def cursor(t, x, y, delay):
    return (f'<g class="out" style="animation-delay: {delay:.2f}s">'
            f'<rect class="cursor" x="{x:.1f}" y="{y - 14}" width="{CW}" height="18" fill="{t["pink"]}"/></g>')


STYLE = f'''<style>
    .m {{ font-family: {MONO}; white-space: pre; }}
    .t {{ font-size: {FS}px; }}
    .out {{ opacity: 0; animation: show .01s linear forwards; }}
    .cursor {{ animation: blink 1.1s steps(1) infinite; }}
    @keyframes show {{ to {{ opacity: 1; }} }}
    @keyframes blink {{ 50% {{ opacity: 0; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .out, .cover, .cursor {{ animation: none !important; }}
      .out {{ opacity: 1; }}
      .cover {{ display: none; }}
    }}
  </style>'''


def window(t, H, title, body, w=W, extra="", pad=0, pad_bottom=0):
    """macOS 터미널 창: 제목 표시줄 + 신호등 점 + 본문. w 로 작은 창(카드)도 만든다.
    pad: 창 위쪽 빈 여백(px). README 에서 위 요소와 간격을 띄울 때 쓴다."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{H + pad + pad_bottom}" viewBox="0 0 {w} {H + pad + pad_bottom}">
  {STYLE}{extra}
  <g transform="translate(0 {pad})">
  <rect x="1" y="1" width="{w - 2}" height="{H - 2}" rx="10" fill="{t["bg"]}"/>
  <path d="M1 32V11A10 10 0 0 1 11 1H{w - 11}A10 10 0 0 1 {w - 1} 11V32Z" fill="{t["bar"]}"/>
  <line x1="1" y1="32.5" x2="{w - 1}" y2="32.5" stroke="{t["barline"]}"/>
  <circle cx="20" cy="17" r="6" fill="#ff5f57"/><circle cx="40" cy="17" r="6" fill="#febc2e"/><circle cx="60" cy="17" r="6" fill="#28c840"/>
  <text x="{w / 2:.0f}" y="21" text-anchor="middle" font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="12" fill="{t["title"]}">{esc(title)}</text>
  {body}
  <rect x="1" y="1" width="{w - 2}" height="{H - 2}" rx="10" fill="none" stroke="{t["line"]}"/>
  </g>
</svg>'''


def segments(t, x, y, segs):
    """파워라인 칸들: [(글자, 배경, 글자색)] → 칸 + 삼각 화살표. 끝 x 를 함께 돌려준다."""
    rects, arrows = [], []
    for s, bg, fg in segs:
        w = len(s) * CW
        rects.append(f'<rect x="{x:.1f}" y="{y - 15}" width="{w + 1:.1f}" height="21" fill="{bg}"/>' +
                     text(x, y, [(s, fg, True)]))
        arrows.append(f'<polygon points="{x + w:.1f},{y - 15} {x + w + 10:.1f},{y - 4.5} {x + w:.1f},{y + 6}" fill="{bg}"/>')
        x += w
    return "".join(rects + arrows), x


def prompt(t, cfg, y, now):
    """starship 같은 파워라인 프롬프트 + 오른쪽 시계. 명령어를 쓸 x 를 함께 돌려준다."""
    p = cfg["prompt"]
    svg, x = segments(t, 20, y, [(f" {p['user']} ", t["seg1"], t["segfg"]),
                                 (f"  {p['path']} ", t["seg2"], t["segfg"]),
                                 (f"  {p['branch']} ", t["seg3"], t["seg3fg"])])
    svg += text(x + 16, y, [("❯ ", t["pink"], True)])
    svg += text(W - 20, y, [(now.strftime("%H:%M:%S"), t["dim"], False)], anchor="end")
    return svg, x + 16 + 2 * CW


def ascii_art(t, art, x, y0, delay):
    """프사 ASCII. 줄마다 같은 색끼리 묶고, 위에서부터 한 줄씩 나타난다."""
    def color(c):
        if c is None:
            return t["art"]
        return t["symbol"] if c == "SYMBOL" else t["brush"][ART_STEP.get(c, 1)]

    rows = []
    for r, line in enumerate(art):
        spans = "".join(f'<tspan fill="{color(c)}">{esc("".join(ch for ch, _ in g))}</tspan>'
                        for c, g in itertools.groupby(line, key=lambda cell: cell[1]))
        rows.append(f'<text class="m out" x="{x}" y="{y0 + r * ART_LH:.1f}" font-size="{ART_FS}" font-weight="700" '
                    f'xml:space="preserve" textLength="{ART_COLS * ART_CW:.1f}" lengthAdjust="spacing" '
                    f'style="animation-delay: {delay + r * .02:.2f}s">{spans}</text>')
    return "\n  ".join(rows)


def uptime(created_at, now):
    c = dt.date.fromisoformat(created_at[:10])
    months = (now.year - c.year) * 12 + now.month - c.month - (now.day < c.day)
    return f"{months // 12}y {months % 12}m"


def ago(iso, now):
    """'2026-11-18T08:00:00Z' → '3h' / '2d' 처럼 지난 시간."""
    then = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    s = (now - then).total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


# ================================================================ 1. 상단 터미널
def hero(t, cfg, gh, art, now):
    values = dict(uptime=uptime(gh["created_at"], now), commits=f'{gh["commits"]:,}', repos=gh["repos"],
                  followers=gh["followers"], contribs=f'{gh["contribs_1y"]:,}')
    login = gh["login"].lower()
    rows = [[(login, t["pink"], True), ("@", t["fg"], False), ("github", t["pink"], True)],
            [("-" * (len(login) + 7), t["dim"], False)]]
    # 정보 칸 너비: x=330 부터 창 오른쪽(880)까지 약 65칸
    rows += [[(k, t["pink"], True), (": " + clip(str(v).format(**values), 63 - width(k)), t["fg"], False)]
             for k, v in cfg["neofetch"].items()]

    y_art = 118
    art_end = y_art + (ART_ROWS - 1) * ART_LH
    info_end = y_art + 6 + len(rows) * 21 + 24
    y_last = round(max(art_end, info_end) + 36)
    H = y_last + 22

    p1, cx1 = prompt(t, cfg, 88, now)
    p2, cx2 = prompt(t, cfg, y_last, now)
    body = [text(20, 60, [(f"Last login: {now.strftime('%a %b %d %H:%M:%S')} on ttys001", t["dim"], False)]),
            p1, typed(t, cx1, 88, "neofetch", .4, .7),
            ascii_art(t, art, 20, y_art, 1.2)]
    for i, parts in enumerate(rows):
        body.append(text(330, y_art + 6 + i * 21, parts, delay=1.25 + i * .04))
    yb = y_art + 6 + len(rows) * 21 + 4
    blocks = "".join(f'<rect x="{330 + i * 26}" y="{yb}" width="26" height="16" fill="{c}"/>' for i, c in enumerate(ANSI))
    body += [f'<g class="out" style="animation-delay: 1.7s">{blocks}</g>',
             f'<g class="out" style="animation-delay: 2s">{p2}</g>', cursor(t, cx2, y_last, 2)]
    return window(t, H, f"{login} — zsh — 120×32", "\n  ".join(body), pad_bottom=TOP_GAP)


# ================================================================ 2. btop
def mix(c1, c2, f):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def panel(t, x, y, w, h, num, title, color, delay):
    """btop 패널: 둥근 테두리 + 테두리 위에 '¹title'."""
    tw = (len(title) + 1) * CW + 12
    return (f'<g class="out" style="animation-delay: {delay}s">'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="none" stroke="{color}"/>'
            f'<rect x="{x + 10}" y="{y - 9}" width="{tw:.0f}" height="18" fill="{t["bg"]}"/>'
            + text(x + 16, y + 5, [(num, color, True), (title, t["fg"], True)]) + '</g>')


def btop(t, cfg, gh, now):
    H, P = 412, t["panels"]
    p, cx = prompt(t, cfg, 60, now)
    body = [p, typed(t, cx, 60, "btop", .3, .4)]

    # ¹ contributions: 작은 칸을 쌓은 막대 (터미널 블록 그래프처럼)
    body.append(panel(t, 16, 80, 868, 150, "¹", "contributions", P[0], .8))
    label = " last 52 weeks "
    lw = len(label) * CW
    body.append(f'<rect class="out" x="{600 - lw:.0f}" y="71" width="{lw:.0f}" height="18" fill="{t["bg"]}" style="animation-delay: .8s"/>')
    body.append(text(600 - lw, 85, [(label, t["dim"], False)], delay=.8))
    peak, levels, base = max(gh["weeks"]) or 1, 20, 214
    lo, mid, hi = t["heat"]
    for i, v in enumerate(gh["weeks"]):
        n = max(1, round(v / peak * levels))
        x = 32 + i * 10.8
        cells_ = "".join(
            f'<rect x="{x:.1f}" y="{base - (j + 1) * 5.5 + 1.5:.1f}" width="7.6" height="4" '
            f'fill="{mix(lo, mid, j / 9.5) if j < 10 else mix(mid, hi, (j - 10) / 9)}"/>' for j in range(n))
        body.append(f'<g class="out" style="animation-delay: {.9 + i * .015:.3f}s">{cells_}</g>')
    body.append(f'<line class="out" x1="616.5" y1="96" x2="616.5" y2="218" stroke="{t["track"]}" style="animation-delay: .8s"/>')
    login = gh["login"].lower()
    stats = [("uptime", uptime(gh["created_at"], now)), ("commits", f'{gh["commits"]:,}'),
             ("contribs 1y", f'{gh["contribs_1y"]:,}'), ("repos", gh["repos"]), ("followers", gh["followers"])]
    rows = [[(login, t["pink"], True), ("@", t["fg"], False), ("github", t["pink"], True)]]
    rows += [[(f"{k:<12}", t["dim"], False), (f"{v:>12}", t["fg"], True)] for k, v in stats]
    for j, parts in enumerate(rows):
        body.append(text(636, 112 + j * 20, parts, delay=1.0 + j * .05))

    # ² languages: ■ 20칸 미터
    body.append(panel(t, 16, 248, 428, 150, "²", "languages", P[1], 1.2))
    for j, ((name, pct), color) in enumerate(zip(gh["languages"], t["langs"])):
        full = max(1, round(pct / 5)) if pct else 0
        body.append(text(32, 280 + j * 22, [(f"{name:<11}", t["fg"], False), ("■" * full, color, False),
                                             ("■" * (20 - full), t["track"], False), (f"{pct:>5}%", t["dim"], False)],
                         delay=1.3 + j * .05))

    # ³ proc: 최근 푸시한 저장소를 프로세스처럼
    body.append(panel(t, 456, 248, 428, 150, "³", "proc", P[2], 1.4))
    body.append(text(472, 276, [("Pid  Program              Status    Updated", t["dim"], True)], delay=1.5))
    body.append(f'<rect class="out" x="464" y="283" width="412" height="20" rx="3" fill="{t["hl"]}" style="animation-delay: 1.5s"/>')
    for j, r in enumerate(gh["recent_repos"]):
        days = (now - dt.datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))).days
        status = "running" if days <= 30 else "sleeping" if days <= 90 else "idle"
        color = {"running": t["pink"], "sleeping": t["lav"], "idle": t["dim"]}[status]
        body.append(text(472, 298 + j * 20, [(f"{r['id'] % 10000:04d} ", t["dim"], False), (pad(r["name"], 21), t["fg"], j == 0),
                                             (f"{status:<10}", color, False), (f"{'today' if days == 0 else f'{days}d':>7}", t["dim"], False)],
                         delay=1.55 + j * .05))
    return window(t, H, f"{login} — btop — 120×32", "\n  ".join(body), pad=TOP_GAP)


# ================================================================ 3. 섹션 제목
# 섹션 간격(px). README 에 <br> 을 쓰지 않고 제목 이미지의 위·아래 여백으로 통일한다.
HEAD_TOP, HEAD_BOTTOM = 40, 24   # 제목 칸 위 / 아래 빈 공간
GAP = HEAD_TOP                   # 마무리 창 위 여백도 같은 값
TOP_GAP = 18                     # 상단 터미널 → 배지 → btop 사이 여백


def heading(t, num, title, path, top=None, bottom=None):
    """(위 여백) [01]▶[title]▶ ──────────── ~/path (아래 여백)"""
    top = HEAD_TOP if top is None else top
    bottom = HEAD_BOTTOM if bottom is None else bottom
    y = top + 15                 # 칸(높이 21)이 y-15 ~ y+6 에 그려진다
    H = top + 21 + bottom
    svg, x = segments(t, 0, y, [(f" {num} ", t["seg1"], t["segfg"]), (f"  {title} ", t["seg3"], t["seg3fg"])])
    pw = len(path) * CW
    svg += f'<line x1="{x + 22:.0f}" y1="{y - 4.5}" x2="{W - pw - 12:.0f}" y2="{y - 4.5}" stroke="{t["line"]}"/>'
    svg += text(W, y, [(path, t["dim"], False)], anchor="end")
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{STYLE}{svg}</svg>'


# ================================================================ 3-1. 기술 스택 (아이콘 줄, 너비 가득)
def stack(t, cfg, mode):
    """❯ ls ~/stack/*  →  languages/  [아이콘]  Java  Kotlin …"""
    import base64
    import re
    cats = cfg.get("stack") or {}
    colors = [t["pink"], t["lav"]]
    body = [text(18, 60, [("❯ ", t["pink"], True), ("ls ~/stack/*", t["fg"], False)])]
    y, ix, h = 82, 150, 36
    for i, (cat, items) in enumerate(cats.items()):
        body.append(text(18, y + 23, [(cat + "/", colors[i % 2], True)], delay=.2 + i * .05))
        nx = ix
        icon = DATA / "icons" / f"{cat}-{mode}.svg"
        if icon.exists():
            svg = icon.read_text(encoding="utf-8")
            m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
            iw = float(m.group(1)) / float(m.group(2)) * h if m else h
            uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
            body.append(f'<image class="out" href="{uri}" x="{ix}" y="{y}" width="{iw:.1f}" height="{h}" '
                        f'style="animation-delay: {.2 + i * .05:.2f}s"/>')
            nx = ix + iw + 16
        names = clip("  ".join(items), int((W - 18 - nx) / 7.8))
        body.append(text(nx, y + 23, [(names, t["dim"], False)], size=13, delay=.2 + i * .05))
        y += 46
    return window(t, y + 10, "stack", "\n  ".join(body))


# ================================================================ 4. git log (너비 가득)
def gitlog(t, cfg, gh, now):
    """❯ git log --oneline -5 : 최근 공개 커밋 (프로필 저장소 제외)"""
    commits = gh.get("recent_commits") or []
    cells = int((W - 2 * 18) / 7.8)          # 13px 글자 기준 한 줄 칸 수
    body = [text(18, 60, [("❯ ", t["pink"], True), ("git log --oneline -5", t["fg"], False)])]
    if not commits:
        body.append(text(18, 88, [("No public commits yet.", t["dim"], False)], size=13))
        return window(t, 108, "git", "\n  ".join(body))
    for i, c in enumerate(commits):
        y = 88 + i * 20
        right = f"{c['repo']} · {ago(c['date'], now)}"
        msg = clip(c["msg"], cells - 9 - width(right) - 2)
        body.append(text(18, y, [(c["sha"] + "  ", t["lav"], False), (msg, t["fg"], False)], size=13, delay=.2 + i * .05))
        body.append(text(W - 18, y, [(right, t["dim"], False)], size=13, anchor="end", delay=.2 + i * .05))
    return window(t, 88 + (len(commits) - 1) * 20 + 22, "git", "\n  ".join(body))


# ================================================================ 5. Spotify 플레이어 (작은 창 420px)
def spotify(t, cfg, sp, now):
    """큰 커버 + ♪ LAST PLAYED + 제목 + 아티스트 + 끝까지 찬 재생 막대(다 들은 곡) + 곡 길이 + 몇 시간 전"""
    w, x0, top, s = 420, 18, 50, 96
    tx = x0 + s + 18
    cells = int((w - tx - x0) / 10.2)        # 17px 제목 기준 칸 수
    tr = ((sp or {}).get("tracks") or [None])[0]
    body = [f'<defs><clipPath id="cv"><rect x="{x0}" y="{top}" width="{s}" height="{s}" rx="8"/></clipPath>'
            f'<linearGradient id="cg" x1="0" x2="1"><stop offset="0" stop-color="#fc9ccc"/><stop offset=".55" stop-color="#e43c9c"/>'
            f'<stop offset="1" stop-color="#a97be6"/></linearGradient></defs>']
    if tr and tr.get("cover"):
        body.append(f'<image href="{tr["cover"]}" x="{x0}" y="{top}" width="{s}" height="{s}" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#cv)"/>')
    else:
        body.append(f'<rect x="{x0}" y="{top}" width="{s}" height="{s}" rx="8" fill="url(#cg)"/>')
    if not tr:
        body.append(text(tx, top + 52, [("Nothing played recently.", t["dim"], False)], size=13))
        return window(t, top + s + 18, "spotify", "\n  ".join(body), w=w)

    bar = w - tx - x0
    body += [text(tx, top + 12, [("♪ LAST PLAYED", t["pink"], True)], size=12),
             text(tx, top + 36, [(clip(tr["title"], cells), t["fg"], True)], size=17),
             text(tx, top + 56, [(clip(tr["artist"], int(bar / 7.8)), t["dim"], False)], size=13),
             f'<rect x="{tx}" y="{top + 72}" width="{bar}" height="4" rx="2" fill="{t["pink"]}"/>',
             f'<circle cx="{tx + bar}" cy="{top + 74}" r="5" fill="{t["fg"]}"/>',
             text(tx, top + 94, [(tr.get("duration", ""), t["dim"], False)], size=12),
             text(w - x0, top + 94, [(ago(tr["played_at"], now) + " ago", t["dim"], False)], size=12, anchor="end")]
    return window(t, top + s + 18, "spotify", "\n  ".join(body), w=w)


# ================================================================ 6. 마무리
def footer(t, cfg, now):
    p, cx = prompt(t, cfg, 60, now)
    body = [p, typed(t, cx, 60, "exit", .3, .4),
            text(20, 88, [(cfg["footer"], t["pink"], True)], delay=1.0),
            text(20, 110, [("Saving session...completed.", t["dim"], False)], delay=1.3),
            text(20, 132, [("[Process completed]", t["dim"], False)], delay=1.6)]
    return window(t, 150, f"{cfg['prompt']['user']} — zsh — 120×32", "\n  ".join(body), pad=GAP)


# ================================================================ main
def load(name):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main():
    cfg = yaml.safe_load((ROOT / "profile.yml").read_text(encoding="utf-8"))
    gh, sp = load("github.json"), load("spotify.json")
    now = dt.datetime.now(KST)
    art = cells(DATA / "avatar.png", ART_COLS, ART_ROWS)
    OUT.mkdir(exist_ok=True)

    for mode, t in THEMES.items():
        files = {"hero": hero(t, cfg, gh, art, now), "btop": btop(t, cfg, gh, now), "stack": stack(t, cfg, mode),
                 "gitlog": gitlog(t, cfg, gh, now), "spotify": spotify(t, cfg, sp, now),
                 "footer": footer(t, cfg, now)}
        for i, s in enumerate(cfg["sections"], 1):
            files[f"h{i:02d}"] = heading(t, f"{i:02d}", s["title"], s["path"])
        for name, svg in files.items():
            (OUT / f"{name}-{mode}.svg").write_text(svg, encoding="utf-8")
        print(f"{mode}: {', '.join(files)}")


if __name__ == "__main__":
    main()
