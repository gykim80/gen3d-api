# gen3d 게이트웨이(:8000) — 외부 호출용 비동기 잡 API · 모델별 상주 워커(venv 분리)를 하나의 GPU 큐로 돌린다
#   인증: 발급 API 키(호출자별 · 자기 잡만 조회) 또는 관리자 토큰(GEN3D_TOKEN · 키 관리 + 전체 조회)
import glob, ipaddress, json, os, queue, shutil, socket, subprocess, threading, time, urllib.parse, urllib.request, uuid
from typing import List, Optional

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import keys

W = "/workspace"
JOBS_DIR = f"{W}/jobs"
TOKEN = os.environ.get("GEN3D_TOKEN", "")
MAX_FILES = 64
MAX_INPUT_BYTES = 500 * 1024 * 1024
os.makedirs(JOBS_DIR, exist_ok=True)

# 모델별 실행 파이썬 · 러너 — setup.sh 가 venv 를 만들고 ready 마커를 남긴다
MODELS = {
    "hunyuan3d-2.1": {"py": f"{W}/venvs/hy3d/bin/python", "runner": "hy3d.py", "input": "image",
                      "desc": "image → textured PBR mesh (.glb)"},
    "triposplat": {"py": f"{W}/venvs/triposplat/bin/python", "runner": "triposplat.py", "input": "image",
                   "desc": "image → 3D Gaussian splat (.ply/.splat)"},
    "worldmirror-2.0": {"py": f"{W}/venvs/hyworld/bin/python", "runner": "worldmirror.py", "input": "images|video",
                        "desc": "multi-view images/video → points.ply + gaussians.ply + depth/normal/camera"},
    "partllm": {"py": f"{W}/venvs/partllm/bin/python", "runner": "partllm.py", "input": "mesh",
                "desc": "mesh → part segmentation (colored mesh + per-part ply)"},
}

jobs: dict = {}
q: "queue.Queue[str]" = queue.Queue()
app = FastAPI(title="gen3d-api", version="1.1")


def err(code, error, message):
    raise HTTPException(code, {"error": error, "message": message})


@app.exception_handler(HTTPException)
def http_error(_, e: HTTPException):
    # 오류 본문을 {"error": 코드, "message": 설명} 한 모양으로 맞춘다
    body = e.detail if isinstance(e.detail, dict) else {"error": "http_error", "message": str(e.detail)}
    return JSONResponse(body, status_code=e.status_code, headers=getattr(e, "headers", None))


def auth(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Authorization: Bearer <키> 또는 X-API-Key: <키>"""
    raw = x_api_key or (authorization[7:] if authorization and authorization.startswith("Bearer ") else None)
    if TOKEN and raw == TOKEN:
        return {"key_id": "admin", "name": "admin", "admin": True, "max_queued": 1000}
    k = keys.verify(raw)
    if not k:
        err(401, "unauthorized", "missing, invalid or revoked API key")
    return {**k, "admin": False}


def admin(p=Depends(auth)):
    if not p["admin"]:
        err(403, "forbidden", "admin token required")
    return p


def save_job(j):
    json.dump(j, open(f"{JOBS_DIR}/{j['id']}/job.json", "w"), ensure_ascii=False)


def load_jobs():
    """게이트웨이 재시작 후에도 잡 조회가 되게 디스크에서 읽는다 — 끊긴 잡은 실패 처리"""
    for f in glob.glob(f"{JOBS_DIR}/*/job.json"):
        try:
            j = json.load(open(f))
        except ValueError:
            continue
        if j.get("status") in ("queued", "running"):
            j.update(status="failed", error="interrupted by server restart", finished_at=time.time())
            save_job(j)
        jobs[j["id"]] = j


load_jobs()


class Worker:
    """러너 프로세스 하나 — stdin 으로 잡 JSON 한 줄, stdout 으로 결과 JSON 한 줄"""

    def __init__(self, name):
        m = MODELS[name]
        log = open(f"{W}/logs/worker-{name}.log", "a")
        self.p = subprocess.Popen([m["py"], "-u", f"{W}/app/runners/{m['runner']}"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1, cwd=f"{W}/app/runners")

    def run(self, payload):
        self.p.stdin.write(json.dumps(payload) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("worker exited — see logs/worker log")
        return json.loads(line)

    def stop(self):
        self.p.kill()


workers: dict = {}


def gpu_loop():
    while True:
        jid = q.get()
        j = jobs[jid]
        name = j["model"]
        j.update(status="running", started_at=time.time()); save_job(j)
        try:
            # 한 번에 한 모델만 VRAM 에 상주 — 다른 모델로 바뀌면 이전 워커를 내린다
            for other in [k for k in workers if k != name]:
                workers.pop(other).stop()
            if name not in workers or workers[name].p.poll() is not None:
                workers[name] = Worker(name)
            r = workers[name].run({"job_id": jid, "inputs": j["inputs"], "out_dir": f"{JOBS_DIR}/{jid}/out",
                                   "params": j["params"]})
            if r.get("ok"):
                j.update(status="succeeded", files=r.get("files", []), info=r.get("info"))
            else:
                j.update(status="failed", error=r.get("error"))
        except Exception as e:  # noqa: BLE001
            workers.pop(name, None)
            j.update(status="failed", error=str(e))
        j["finished_at"] = time.time(); save_job(j)


threading.Thread(target=gpu_loop, daemon=True).start()


# ---- 입력 처리 ----
def fetch_url(u, dest):
    """http(s) 만 · 사설/루프백 주소 차단(SSRF) · 크기 제한"""
    pu = urllib.parse.urlparse(u)
    if pu.scheme not in ("http", "https") or not pu.hostname:
        err(400, "invalid_url", f"only http(s) or job:// urls are allowed: {u}")
    for info in socket.getaddrinfo(pu.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            err(400, "invalid_url", f"private address not allowed: {pu.hostname}")
    try:
        with urllib.request.urlopen(u, timeout=60) as r, open(dest, "wb") as o:
            n = 0
            while chunk := r.read(1 << 20):
                n += len(chunk)
                if n > MAX_INPUT_BYTES:
                    err(413, "input_too_large", f"input exceeds {MAX_INPUT_BYTES // 2**20} MB")
                o.write(chunk)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        err(400, "fetch_failed", f"could not download {u}: {e}")


def owned(jid, p):
    """호출자 소유 잡만 — 남의 잡은 존재 여부도 숨긴다(404)"""
    j = jobs.get(jid)
    if not j or (not p["admin"] and j.get("owner") != p["key_id"]):
        err(404, "job_not_found", f"no such job: {jid}")
    return j


def view(j):
    out = {k: v for k, v in j.items() if k not in ("inputs", "owner")}
    out["files"] = [os.path.basename(f) for f in j.get("files", [])]
    out["urls"] = [f"/v1/jobs/{j['id']}/files/{f}" for f in out["files"]]
    return out


# ---- API ----
@app.get("/health")
def health():
    return {"ok": True, "queue": q.qsize()}


@app.get("/v1/models")
def models(p=Depends(auth)):
    return {k: {**{x: v[x] for x in ("input", "desc")},
                "ready": os.path.exists(f"{W}/ready/{k}"), "loaded": k in workers} for k, v in MODELS.items()}


@app.post("/v1/jobs/{model}", status_code=202)
def create_job(model: str, files: List[UploadFile] = File(None), urls: str = Form("[]"),
                     params: str = Form("{}"), p=Depends(auth)):
    """입력은 파일 업로드(files) · urls(JSON 배열, http(s) 또는 job://<잡id>/<파일>) — 둘 다 주면 합친다"""
    if model not in MODELS:
        err(404, "unknown_model", f"unknown model: {model} (see GET /v1/models)")
    if not os.path.exists(f"{W}/ready/{model}"):
        err(503, "model_not_ready", f"{model} is still installing")
    try:
        url_list, prm = json.loads(urls), json.loads(params)
        assert isinstance(url_list, list) and isinstance(prm, dict)
    except (ValueError, AssertionError):
        err(400, "invalid_request", "urls must be a JSON array and params a JSON object")
    if len(files or []) + len(url_list) > MAX_FILES:
        err(400, "too_many_inputs", f"at most {MAX_FILES} inputs")
    pending = sum(1 for j in jobs.values() if j.get("owner") == p["key_id"] and j["status"] in ("queued", "running"))
    if pending >= p["max_queued"]:
        err(429, "too_many_jobs", f"{pending} jobs already queued/running for this key (limit {p['max_queued']})")

    jid = uuid.uuid4().hex[:12]
    d = f"{JOBS_DIR}/{jid}/in"
    os.makedirs(d); os.makedirs(f"{JOBS_DIR}/{jid}/out")
    inputs = []
    try:
        for f in files or []:
            dst = f"{d}/{len(inputs)}_{os.path.basename(f.filename or 'input')}"
            with open(dst, "wb") as o:
                shutil.copyfileobj(f.file, o)
            inputs.append(dst)
        for u in url_list:
            dst = f"{d}/{len(inputs)}_{os.path.basename(str(u).split('?')[0]) or 'input'}"
            if str(u).startswith("job://"):
                # 이전 잡 결과를 다음 모델 입력으로(예: job://<id>/shape.glb → partllm) — 자기 잡만
                src_id, _, name = u[6:].partition("/")
                owned(src_id, p)
                src = f"{JOBS_DIR}/{os.path.basename(src_id)}/out/{os.path.basename(name)}"
                if not os.path.isfile(src):
                    err(404, "job_output_not_found", f"no such job output: {u}")
                shutil.copy(src, dst)
            else:
                fetch_url(u, dst)
            inputs.append(dst)
        if not inputs:
            err(400, "no_input", "files or urls required")
    except HTTPException:
        shutil.rmtree(f"{JOBS_DIR}/{jid}", ignore_errors=True)
        raise
    j = {"id": jid, "model": model, "status": "queued", "inputs": inputs, "params": prm, "owner": p["key_id"],
         "created_at": time.time()}
    jobs[jid] = j; save_job(j); q.put(jid)
    return {"id": jid, "status": "queued", "position": q.qsize()}


@app.get("/v1/jobs")
def list_jobs(limit: int = 50, p=Depends(auth)):
    mine = [j for j in jobs.values() if p["admin"] or j.get("owner") == p["key_id"]]
    return [view(j) for j in sorted(mine, key=lambda j: -j["created_at"])[:max(1, min(limit, 500))]]


@app.get("/v1/jobs/{jid}")
def get_job(jid: str, p=Depends(auth)):
    return view(owned(jid, p))


@app.get("/v1/jobs/{jid}/files/{name}")
def get_file(jid: str, name: str, p=Depends(auth)):
    owned(jid, p)
    path = f"{JOBS_DIR}/{jid}/out/{os.path.basename(name)}"
    if not os.path.isfile(path):
        err(404, "file_not_found", f"no such file: {name}")
    return FileResponse(path, filename=os.path.basename(name))


# ---- 키 관리(관리자 토큰 전용) ----
@app.post("/v1/admin/keys", status_code=201)
def create_key(body: dict = Body(...), p=Depends(admin)):
    name = str(body.get("name", "")).strip()
    if not name:
        err(400, "invalid_request", "name is required")
    return keys.issue(name, int(body.get("max_queued", 10)))


@app.get("/v1/admin/keys")
def get_keys(p=Depends(admin)):
    return keys.list_keys()


@app.delete("/v1/admin/keys/{key_id}")
def delete_key(key_id: str, p=Depends(admin)):
    k = keys.revoke(key_id)
    if not k:
        err(404, "key_not_found", f"no such key: {key_id}")
    return k
