"""Spotify 연결 도우미. 처음 설정할 때 로컬에서 한 번만 실행한다.

준비
  1. https://developer.spotify.com/dashboard 에서 앱을 만든다.
  2. 앱 설정의 Redirect URIs 에 정확히 다음 주소를 추가한다:  http://127.0.0.1:8888/callback
  3. 앱의 Client ID, Client Secret 을 확인한다.

실행 (별도 터미널에서)
  .venv/bin/python scripts/spotify_auth.py

  - Client ID · Client Secret 은 화면에 보이지 않게 입력받는다.
  - 브라우저에서 Spotify 로그인 → 동의하면 refresh token 을 받는다.
  - 받은 값 3개를 화면에 출력하지 않고 `gh secret set` 으로 GitHub Secrets 에 바로 등록한다.
    (gh 가 저장소 주인 계정으로 로그인돼 있어야 한다. 등록을 건너뛰면 그때만 토큰을 출력한다.)
"""
import base64
import getpass
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

REPO = "Artiffect/Artiffect"
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-recently-played"


def ask(name, env_key):
    """환경 변수가 있으면 쓰고, 없으면 화면에 보이지 않게 입력받는다."""
    value = (os.environ.get(env_key) or "").strip()
    while not value:
        value = getpass.getpass(f"{name} (입력해도 화면에 안 보여요): ").strip()
    return value


def authorize(cid):
    """브라우저로 Spotify 동의 화면을 열고, 127.0.0.1:8888 로 돌아오는 code 를 받는다."""
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
            self.wfile.write("완료됐어요. 이 창을 닫고 터미널로 돌아가세요.".encode())

        def log_message(self, *args):
            pass

    print("\n브라우저에서 Spotify 로그인 후 '동의'를 눌러 주세요...")
    print("브라우저가 안 열리면 이 주소를 직접 여세요:\n" + url + "\n")
    webbrowser.open(url)
    server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
    while "code" not in got and "error" not in got:
        server.handle_request()
    if got.get("error") or got.get("state") != state:
        sys.exit(f"인증 실패: {got.get('error', 'state 불일치')}")
    return got["code"]


def exchange(cid, secret, code):
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT}).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())["refresh_token"]


def save_to_github(values):
    """gh secret set 으로 등록한다. 값은 표준 입력으로만 넘겨서 화면·명령줄에 남지 않는다."""
    for name, value in values.items():
        r = subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value, text=True, capture_output=True)
        if r.returncode != 0:
            print(f"  ✗ {name} 등록 실패: {r.stderr.strip()}")
            return False
        print(f"  ✓ {name} 등록")
    return True


def main():
    cid = ask("Client ID", "SPOTIFY_CLIENT_ID")
    secret = ask("Client Secret", "SPOTIFY_CLIENT_SECRET")
    refresh = exchange(cid, secret, authorize(cid))
    print("Spotify 인증 성공.\n")

    # 한글 입력 상태 등으로 터미널이 깨진 글자를 보내도 멈추지 않게, 바이트로 읽고 못 읽는 글자는 버린다
    print(f"GitHub 저장소 {REPO} 의 Secrets 에 바로 등록할까요? [Y/n] ", end="", flush=True)
    answer = sys.stdin.buffer.readline().decode("utf-8", errors="ignore").strip().lower()
    if answer not in ("n", "no", "ㅜ"):
        if save_to_github({"SPOTIFY_CLIENT_ID": cid, "SPOTIFY_CLIENT_SECRET": secret, "SPOTIFY_REFRESH_TOKEN": refresh}):
            print("\n끝! GitHub Actions → profile → Run workflow 를 누르면 바로 반영돼요.")
            return
        print("\n자동 등록에 실패해서, 직접 등록할 수 있게 토큰을 보여 드릴게요.")
    print("\nSPOTIFY_REFRESH_TOKEN =\n" + refresh)
    print("\n이 값과 Client ID · Secret 을 GitHub Secrets 에 직접 등록하고, 이 터미널 창은 닫아 주세요.")


if __name__ == "__main__":
    main()
