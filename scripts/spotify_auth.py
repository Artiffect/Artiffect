"""Spotify refresh token 을 한 번 받아 오는 도우미. (처음 설정할 때 로컬에서 한 번만 실행)

준비
  1. https://developer.spotify.com/dashboard 에서 앱을 만든다.
  2. 앱 설정의 Redirect URIs 에 정확히 다음 주소를 추가한다:  http://127.0.0.1:8888/callback
  3. 앱의 Client ID, Client Secret 을 확인한다.

실행
  SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python scripts/spotify_auth.py

브라우저가 열리면 Spotify 로그인 → 동의. 터미널에 refresh token 이 나오면
GitHub 저장소 Settings → Secrets and variables → Actions 에 SPOTIFY_REFRESH_TOKEN 으로 등록한다.
(토큰은 비밀번호처럼 다루고, 파일이나 커밋에 남기지 않는다.)
"""
import base64
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-recently-played"


def main():
    cid, secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and secret):
        sys.exit("SPOTIFY_CLIENT_ID 와 SPOTIFY_CLIENT_SECRET 을 환경 변수로 넣어 주세요.")

    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPE, "state": state})
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("완료됐어요. 이 창을 닫고 터미널을 확인하세요.".encode())

        def log_message(self, *args):
            pass

    print("브라우저에서 Spotify 로그인 후 동의해 주세요...")
    print("브라우저가 안 열리면 이 주소를 직접 여세요:\n" + url)
    webbrowser.open(url)
    server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
    while "code" not in got and "error" not in got:
        server.handle_request()

    if got.get("error") or got.get("state") != state:
        sys.exit(f"인증 실패: {got.get('error', 'state 불일치')}")

    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({"grant_type": "authorization_code", "code": got["code"],
                                     "redirect_uri": REDIRECT}).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as res:
        tokens = json.loads(res.read())

    print("\nSPOTIFY_REFRESH_TOKEN =")
    print(tokens["refresh_token"])
    print("\n위 값을 GitHub Secrets 에 SPOTIFY_REFRESH_TOKEN 으로 등록하세요.")


if __name__ == "__main__":
    main()
