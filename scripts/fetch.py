"""README에 필요한 데이터를 받아 data/ 폴더에 저장한다. (그리기는 render.py가 한다)

    data/avatar.png     프로필 사진
    data/github.json    잔디·통계·언어 비율·최근 저장소·최근 커밋
    data/spotify.json   가장 최근 들은 곡 + 앨범 커버  (SPOTIFY_* 세 개가 있을 때만)
    data/icons/*.svg    기술 스택 카테고리별 아이콘 줄 (skillicons.dev)

환경 변수
    GITHUB_TOKEN            필수. Actions에선 자동으로 들어오고, 로컬에선 `gh auth token` 값.
    SPOTIFY_CLIENT_ID       선택. Spotify 개발자 앱
    SPOTIFY_CLIENT_SECRET   선택.
    SPOTIFY_REFRESH_TOKEN   선택. user-read-recently-played 권한으로 받은 refresh token

실행: python scripts/fetch.py
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


# ---------------------------------------------------------------- HTTP
def request(url, *, token=None, auth=None, data=None, headers=None):
    h = {"User-Agent": "profile-readme-bot", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if auth:
        h["Authorization"] = f"Basic {auth}"
    body = None
    if data is not None:
        if isinstance(data, dict) and h.get("Content-Type") == "application/json":
            body = json.dumps(data).encode()
        else:
            body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
    return json.loads(raw) if raw[:1] in (b"{", b"[") else raw


def write_json(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote data/{name}")


# ---------------------------------------------------------------- GitHub
GRAPHQL = """
query($login: String!) {
  user(login: $login) {
    login
    createdAt
    avatarUrl(size: 460)
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount } }
      }
    }
  }
}"""


def contributions_from_page(login):
    """github.com/users/<login>/contributions 의 날짜 칸과 툴팁을 이어 하루 기여 수를 읽는다."""
    html = request(f"https://github.com/users/{login}/contributions").decode("utf-8")
    dates = {}
    for tag in re.findall(r"<td\b[^>]*>", html):
        d, i = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag), re.search(r'\bid="([^"]+)"', tag)
        if d and i:
            dates[i.group(1)] = d.group(1)
    counts = {}
    for tid, n in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>\s*(No|\d+) contributions?', html):
        if tid in dates:
            counts[dates[tid]] = 0 if n == "No" else int(n)
    if len(counts) < 300:
        raise ValueError(f"날짜 {len(counts)}개만 읽힘")
    daily = [counts[k] for k in sorted(counts)]
    weeks = [sum(daily[max(0, i - 7):i]) for i in range(len(daily), 0, -7)][:52][::-1]
    return weeks, sum(daily)


def fetch_github(login, token, exclude):
    api = "https://api.github.com"
    gh = lambda path: request(api + path, token=token, headers={"Accept": "application/vnd.github+json"})

    user = request(api + "/graphql", token=token, headers={"Content-Type": "application/json"},
                   data={"query": GRAPHQL, "variables": {"login": login}})["data"]["user"]
    # 잔디: 프로필 페이지와 같은 숫자(비공개 저장소 기여 포함)를 쓰려고 페이지에서 직접 읽고,
    # 실패하면 API 값(공개 기여만)으로 대신한다
    try:
        weeks, contribs_1y = contributions_from_page(login)
    except Exception as e:  # 페이지 구조가 바뀌었거나 접속 실패
        print(f"  잔디 페이지 읽기 실패({e}) → API 값 사용")
        cal = user["contributionsCollection"]["contributionCalendar"]
        weeks = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cal["weeks"]][-52:]
        contribs_1y = cal["totalContributions"]

    # 작성한 공개 커밋 수 (검색 API)
    commits = gh(f"/search/commits?q=author:{login}&per_page=1")["total_count"]

    # 내 공개 저장소 (포크·프로필 저장소 자신 제외): 언어 바이트 합계 + 최근 푸시 순 목록
    # 프로필 저장소(아이디와 같은 이름)는 이 스크립트들 때문에 Python 비율이 생기고 매일 '방금 푸시'로 잡혀서 뺀다
    repos = [r for r in gh(f"/users/{login}/repos?per_page=100&sort=pushed")
             if not r["fork"] and r["name"].lower() != login.lower()]
    langs = Counter()
    for r in repos:
        langs.update(gh(f"/repos/{login}/{r['name']}/languages"))
    total = sum(langs.values()) or 1
    top = [[k, round(v / total * 100)] for k, v in langs.most_common(4)]
    top.append(["Others", 100 - sum(p for _, p in top)])

    recent = [{"id": r["id"], "name": r["name"], "pushed_at": r["pushed_at"]}
              for r in repos if r["name"] not in exclude][:5]

    # 최근 공개 커밋 5개 (프로필 저장소 제외) — git log 카드용
    found = gh(f"/search/commits?q=author:{login}+-repo:{login}/{login}&sort=author-date&order=desc&per_page=5")
    recent_commits = [{"sha": c["sha"][:7], "msg": c["commit"]["message"].split("\n")[0],
                       "repo": c["repository"]["name"], "date": c["commit"]["author"]["date"]}
                      for c in found.get("items", [])]

    # 프사
    urllib.request.urlretrieve(user["avatarUrl"], DATA / "avatar.png")
    print("  wrote data/avatar.png")

    write_json("github.json", {
        "login": user["login"],
        "created_at": user["createdAt"],
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "commits": commits,
        "contribs_1y": contribs_1y,
        "weeks": weeks,
        "languages": top,
        "recent_repos": recent,
        "recent_commits": recent_commits,
    })


# ---------------------------------------------------------------- 기술 스택 아이콘
# profile.yml 의 이름 → skillicons.dev 아이콘 아이디. 여기 없는 이름은 아이콘 없이 글자만 나온다.
ICON_IDS = {
    "java": "java", "kotlin": "kotlin", "typescript": "ts", "javascript": "js", "python": "py", "go": "go",
    "c": "c", "c++": "cpp", "rust": "rust", "html": "html", "css": "css",
    "spring": "spring", "spring boot": "spring", "gradle": "gradle", "maven": "maven", "hibernate": "hibernate",
    "nodejs": "nodejs", "node.js": "nodejs", "express": "express", "nestjs": "nestjs", "django": "django",
    "flask": "flask", "fastapi": "fastapi", "graphql": "graphql", "react": "react", "vue": "vue",
    "next.js": "nextjs", "astro": "astro", "tailwind": "tailwind",
    "mysql": "mysql", "postgresql": "postgres", "mongodb": "mongodb", "redis": "redis",
    "elasticsearch": "elasticsearch", "kafka": "kafka", "rabbitmq": "rabbitmq", "sqlite": "sqlite",
    "docker": "docker", "kubernetes": "kubernetes", "aws": "aws", "gcp": "gcp", "azure": "azure",
    "github actions": "githubactions", "jenkins": "jenkins", "nginx": "nginx", "linux": "linux",
    "terraform": "terraform", "prometheus": "prometheus", "grafana": "grafana", "git": "git", "github": "github", "intellij idea": "idea", "intellij": "idea",
    "vscode": "vscode", "postman": "postman", "figma": "figma", "notion": "notion",
}


def fetch_stack_icons(stack):
    """카테고리마다 아이콘 줄 SVG 를 다크·라이트 두 벌 받아 data/icons/ 에 저장한다."""
    out = DATA / "icons"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    for cat, items in stack.items():
        ids = [ICON_IDS[n.lower()] for n in items if n.lower() in ICON_IDS]
        if not ids:
            continue
        for theme in ("dark", "light"):
            url = f"https://skillicons.dev/icons?i={'%2C'.join(ids)}&theme={theme}"
            (out / f"{cat}-{theme}.svg").write_bytes(request(url))
        print(f"  icons: {cat} ({', '.join(ids)})")


# ---------------------------------------------------------------- Spotify
def cover_data_uri(url, px=144):
    """앨범 커버를 작게 줄여 SVG 안에 넣을 data URI 로. (README 의 SVG 는 외부 이미지를 불러오지 못한다)"""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(request(url))).convert("RGB").resize((px, px), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def fetch_spotify(client_id, client_secret, refresh_token):
    """가장 최근에 들은 곡 1개 + 앨범 커버."""
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    access = request("https://accounts.spotify.com/api/token", auth=auth,
                     data={"grant_type": "refresh_token", "refresh_token": refresh_token})["access_token"]
    items = request("https://api.spotify.com/v1/me/player/recently-played?limit=1", token=access).get("items", [])
    tracks = []
    for i in items:
        tr = i["track"]
        images = sorted(tr["album"].get("images", []), key=lambda im: im.get("width") or 0)
        pick = next((im for im in images if (im.get("width") or 0) >= 144), images[-1] if images else None)
        tracks.append({"title": tr["name"],
                       "artist": ", ".join(a["name"] for a in tr["artists"]),
                       "played_at": i["played_at"],
                       "duration": "{}:{:02d}".format(*divmod(round(tr.get("duration_ms", 0) / 1000), 60)),
                       "cover": cover_data_uri(pick["url"]) if pick else None})
    write_json("spotify.json", {"tracks": tracks})


# ---------------------------------------------------------------- main
def optional(name, fn, *args):
    """Spotify·아이콘은 실패해도 전체를 멈추지 않는다. 경고만 남기고 해당 카드는 '기록 없음'으로 그린다."""
    try:
        fn(*args)
    except urllib.error.HTTPError as e:
        hint = {401: "키가 틀렸거나 만료됐어요", 403: "권한이 없어요. 토큰 권한(scope)을 확인하세요"}
        body = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")  # 서버가 알려 주는 이유 (키는 들어 있지 않음)
        print(f"::warning::{name} 요청 실패 HTTP {e.code} — {hint.get(e.code, '잠시 뒤 다시 시도됩니다')} | 응답: {body}")
    except Exception as e:  # 네트워크 오류 등
        print(f"::warning::{name} 요청 실패 — {type(e).__name__}: {e}")


def main():
    cfg = yaml.safe_load((ROOT / "profile.yml").read_text(encoding="utf-8"))
    DATA.mkdir(exist_ok=True)
    env = lambda k: (os.environ.get(k) or "").strip()  # Secrets 값 앞뒤 공백·줄바꿈 제거

    token = env("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN 이 필요해요. 로컬에선: GITHUB_TOKEN=$(gh auth token) python scripts/fetch.py")
    print("GitHub")
    fetch_github(cfg["github"], token, set(cfg.get("btop_exclude", [])))

    print("Stack icons")
    optional("Stack icons", fetch_stack_icons, cfg.get("stack") or {})

    print("Spotify")
    spotify = [env("SPOTIFY_CLIENT_ID"), env("SPOTIFY_CLIENT_SECRET"), env("SPOTIFY_REFRESH_TOKEN")]
    if all(spotify):
        optional("Spotify", fetch_spotify, *spotify)
    else:
        print("  SPOTIFY_* 없음 → 건너뜀")


if __name__ == "__main__":
    main()
