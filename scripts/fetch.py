"""README에 필요한 데이터를 받아 data/ 폴더에 저장한다. (그리기는 render.py가 한다)

    data/avatar.png     프로필 사진
    data/github.json    잔디·통계·언어 비율·최근 저장소
    data/wakatime.json  지난 7일 언어별 코딩 시간   (WAKATIME_API_KEY 가 있을 때만)
    data/spotify.json   최근 들은 곡               (SPOTIFY_* 세 개가 있을 때만)

환경 변수
    GITHUB_TOKEN            필수. Actions에선 자동으로 들어오고, 로컬에선 `gh auth token` 값.
    WAKATIME_API_KEY        선택. wakatime.com/settings/api-key
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
    })


# ---------------------------------------------------------------- WakaTime
def fetch_wakatime(key):
    auth = base64.b64encode(key.encode()).decode()
    res = request("https://wakatime.com/api/v1/users/current/stats/last_7_days", auth=auth)["data"]
    write_json("wakatime.json", {
        "total": res.get("human_readable_total", ""),
        "languages": [{"name": l["name"], "text": l["text"], "percent": l["percent"]}
                      for l in res.get("languages", [])[:5]],
    })


# ---------------------------------------------------------------- Spotify
def fetch_spotify(client_id, client_secret, refresh_token, count):
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    access = request("https://accounts.spotify.com/api/token", auth=auth,
                     data={"grant_type": "refresh_token", "refresh_token": refresh_token})["access_token"]
    res = request(f"https://api.spotify.com/v1/me/player/recently-played?limit={count}", token=access)
    write_json("spotify.json", {
        "tracks": [{"title": i["track"]["name"],
                    "artist": ", ".join(a["name"] for a in i["track"]["artists"]),
                    "played_at": i["played_at"]} for i in res.get("items", [])],
    })


# ---------------------------------------------------------------- main
def optional(name, fn, *args):
    """WakaTime·Spotify 는 실패해도 전체를 멈추지 않는다. 경고만 남기고 해당 카드는 '기록 없음'으로 그린다."""
    try:
        fn(*args)
    except urllib.error.HTTPError as e:
        hint = {401: "키가 틀렸거나 만료됐어요", 403: "키 값이 정확한지 확인하세요 (앞뒤 공백, 'api_key =' 같은 앞부분 포함 여부)"}
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

    print("WakaTime")
    if env("WAKATIME_API_KEY"):
        optional("WakaTime", fetch_wakatime, env("WAKATIME_API_KEY"))
    else:
        print("  WAKATIME_API_KEY 없음 → 건너뜀")

    print("Spotify")
    spotify = [env("SPOTIFY_CLIENT_ID"), env("SPOTIFY_CLIENT_SECRET"), env("SPOTIFY_REFRESH_TOKEN")]
    if all(spotify):
        optional("Spotify", fetch_spotify, *spotify, cfg.get("spotify_count", 5))
    else:
        print("  SPOTIFY_* 없음 → 건너뜀")


if __name__ == "__main__":
    main()
