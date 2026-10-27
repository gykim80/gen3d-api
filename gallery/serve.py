# gen3d 결과 갤러리 로컬 서버 — python3 serve.py [포트]  → http://127.0.0.1:8787
#   결과 폴더(~/Desktop/ondo/output/gen3d)를 그대로 읽는다 · 썸네일은 브라우저가 렌더해 같은 폴더에 .thumb.png 로 저장
import http.server, json, mimetypes, os, re, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("GEN3D_OUTPUT", os.path.expanduser("~/Desktop/ondo/output/gen3d"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
JOB_RE = re.compile(r"^(?P<model>.+)-(?P<id>[0-9a-f]{12})$")
VIEW_EXT = (".glb", ".ply", ".splat")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("model/gltf-binary", ".glb")


def kind(model, name):
    """3D 파일이 어떤 표시 방식인지 — splat · mesh · parts(부위 점군) · aux(보조)"""
    if name.endswith(".splat") or (model.startswith("triposplat") and name.endswith(".ply")) or "gaussians" in name:
        return "splat"
    if "__part_" in name:
        return "part"
    return "mesh"


def primary(model, files):
    """카드에 대표로 보일 파일 — 텍스처 메시 > 부위 색 메시 > 스플랫 > 아무 3D"""
    order = ["textured.glb", "pred_mesh.ply", "splat.splat", "gaussians.ply", "points.ply", "shape.glb"]
    for want in order:
        for f in files:
            if f.endswith(want):
                return f
    return next((f for f in files if f.endswith(VIEW_EXT)), None)


def items():
    res = []
    for d in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        m = JOB_RE.match(d)
        p = os.path.join(OUT, d)
        if not m or not os.path.isdir(p):
            continue
        names = sorted(f for f in os.listdir(p) if not f.startswith("."))
        views = [f for f in names if f.endswith(VIEW_EXT)]
        if not views:
            continue  # 실패한 잡(빈 폴더)은 건너뛴다
        model = m["model"]
        meta = {}
        mf = next((f for f in names if f.endswith("metadata.json")), None)
        if mf:
            try:
                meta = json.load(open(os.path.join(p, mf)))
            except ValueError:
                pass
        parts = [{"file": f, "label": re.sub(r"^.*__part_\d+_", "", f[:-4]).replace("_", " ")}
                 for f in views if kind(model, f) == "part"]
        res.append({
            # 폴더 시각은 썸네일 저장 때 바뀌므로 결과 파일 시각을 쓴다
            "job": d, "model": model, "id": m["id"], "mtime": max(os.path.getmtime(os.path.join(p, f)) for f in names),
            "primary": primary(model, views),
            "files": [{"file": f, "kind": kind(model, f), "size": os.path.getsize(os.path.join(p, f))}
                      for f in views if kind(model, f) != "part"],
            "parts": parts,
            "images": [f for f in names if f.lower().endswith(IMG_EXT)],
            "thumb": os.path.exists(os.path.join(p, ".thumb.png")),
            "prompt": meta.get("prompt_mode"),
        })
    return sorted(res, key=lambda x: -x["mtime"])


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _safe(self, rel):
        p = os.path.realpath(os.path.join(OUT, rel))
        return p if p.startswith(os.path.realpath(OUT) + os.sep) else None

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if path == "/api/items":
            return self._json(items())
        if path.startswith("/data/"):
            p = self._safe(path[6:])
            if not p or not os.path.isfile(p):
                return self.send_error(404)
            self.send_response(200)
            self.send_header("content-type", mimetypes.guess_type(p)[0] or "application/octet-stream")
            self.send_header("content-length", str(os.path.getsize(p)))
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            with open(p, "rb") as f:
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)
            return
        return super().do_GET()

    def do_POST(self):
        # 썸네일 저장 — /api/thumb/<job>
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        m = re.match(r"^/api/thumb/([\w.\-]+)$", path)
        p = self._safe(m.group(1)) if m else None
        if not p or not os.path.isdir(p):
            return self.send_error(404)
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if not body.startswith(b"\x89PNG"):
            return self.send_error(400)
        open(os.path.join(p, ".thumb.png"), "wb").write(body)
        self._json({"ok": True})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"gen3d gallery → http://127.0.0.1:{PORT}  (data: {OUT})")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
