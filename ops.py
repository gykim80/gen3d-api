# 운영용 작은 서버(:8001) — 설치 로그 보기 · 토큰이 맞을 때만 셸 명령 실행(사내망에서 SSH 대신 쓴다)
import http.server, subprocess, os, json

TOKEN = os.environ.get("GEN3D_TOKEN", "")


class H(http.server.BaseHTTPRequestHandler):
    def _ok(self, body, ct="text/plain; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("content-type", ct)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _authed(self):
        if TOKEN and self.headers.get("x-token") == TOKEN:
            return True
        self.send_response(403); self.end_headers()
        return False

    def do_GET(self):
        if not self._authed():
            return
        cmd = ("ls /workspace/ready; nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader; df -h /workspace | tail -1; "
               "for f in /workspace/logs/*.log; do echo; echo \"=== $f\"; tail -c 1500 $f; done")
        self._ok(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout)

    def do_POST(self):
        if not self._authed():
            return
        cmd = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1800)
        self._ok(json.dumps({"code": r.returncode, "out": r.stdout[-8000:], "err": r.stderr[-8000:]}), "application/json")


http.server.ThreadingHTTPServer(("0.0.0.0", 8001), H).serve_forever()
