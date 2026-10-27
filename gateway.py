# gen3d 게이트웨이(:8000) — 외부 호출용 비동기 잡 API · 모델별 상주 워커(venv 분리)를 하나의 GPU 큐로 돌린다
import json, os, queue, shutil, subprocess, threading, time, urllib.request, uuid
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

W = "/workspace"
JOBS_DIR = f"{W}/jobs"
TOKEN = os.environ.get("GEN3D_TOKEN", "")
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
app = FastAPI(title="gen3d-api", version="1.0")


def auth(authorization: Optional[str] = Header(None)):
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "invalid token")


def save_job(j):
    json.dump(j, open(f"{JOBS_DIR}/{j['id']}/job.json", "w"), ensure_ascii=False)


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


@app.get("/health")
def health():
    return {"ok": True, "queue": q.qsize()}


@app.get("/v1/models", dependencies=[Depends(auth)])
def models():
    return {k: {**{x: v[x] for x in ("input", "desc")},
                "ready": os.path.exists(f"{W}/ready/{k}"), "loaded": k in workers} for k, v in MODELS.items()}


@app.post("/v1/jobs/{model}", dependencies=[Depends(auth)])
async def create_job(model: str, files: List[UploadFile] = File(None), urls: str = Form("[]"),
                     params: str = Form("{}")):
    """입력은 파일 업로드 또는 urls(JSON 배열) — 둘 다 주면 합친다"""
    if model not in MODELS:
        raise HTTPException(404, f"unknown model: {model}")
    if not os.path.exists(f"{W}/ready/{model}"):
        raise HTTPException(503, f"{model} is still installing")
    jid = uuid.uuid4().hex[:12]
    d = f"{JOBS_DIR}/{jid}/in"
    os.makedirs(d); os.makedirs(f"{JOBS_DIR}/{jid}/out")
    inputs = []
    for f in files or []:
        p = f"{d}/{os.path.basename(f.filename or 'input')}"
        with open(p, "wb") as o:
            shutil.copyfileobj(f.file, o)
        inputs.append(p)
    for i, u in enumerate(json.loads(urls)):
        p = f"{d}/{i}_{os.path.basename(u.split('?')[0]) or 'input'}"
        urllib.request.urlretrieve(u, p)
        inputs.append(p)
    if not inputs:
        raise HTTPException(400, "files or urls required")
    j = {"id": jid, "model": model, "status": "queued", "inputs": inputs, "params": json.loads(params),
         "created_at": time.time()}
    jobs[jid] = j; save_job(j); q.put(jid)
    return {"id": jid, "status": "queued", "position": q.qsize()}


@app.get("/v1/jobs/{jid}", dependencies=[Depends(auth)])
def get_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404)
    out = {k: v for k, v in j.items() if k != "inputs"}
    out["files"] = [os.path.basename(f) for f in j.get("files", [])]
    out["urls"] = [f"/v1/jobs/{jid}/files/{f}" for f in out["files"]]
    return out


@app.get("/v1/jobs/{jid}/files/{name}", dependencies=[Depends(auth)])
def get_file(jid: str, name: str):
    p = f"{JOBS_DIR}/{jid}/out/{os.path.basename(name)}"
    if not os.path.isfile(p):
        raise HTTPException(404)
    return FileResponse(p, filename=name)
