# gen3d pod 운영 — python3 deploy.py create | push | status | sh "<명령>"
#   create: H100 pod 생성(부팅 시 git 저장소를 /workspace/app 에 clone 하고 start.sh 실행)
#   push:   git push 후 pod 에서 git pull + 게이트웨이 재시작 · status: 설치 로그 · sh: 원격 셸
#   코드는 git 으로만 옮긴다 — 사내망 외부 업로드 차단 정책 때문에 API 본문에 코드를 싣지 않는다
import json, os, secrets, subprocess, sys

D = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.expanduser("~/Desktop/ondo/ondo-live2d/.env.local")
KEY = os.environ.get("RUNPOD_API_KEY") or next(
    l.split("=", 1)[1].strip().strip('"') for l in open(ENV) if l.startswith("RUNPOD_API_KEY="))
tok_path = os.path.expanduser("~/.gen3d-api-token")  # 저장소 밖에 둔다
if not os.path.exists(tok_path):
    open(tok_path, "w").write(secrets.token_hex(24))
TOKEN = open(tok_path).read().strip()
POD_FILE = os.path.expanduser("~/.gen3d-api-pod")
REPO = "https://github.com/gykim80/gen3d-api.git"


def curl(*args, data=None):
    r = subprocess.run(["curl", "-s", "-m", "1800", *args] + (["--data-binary", "@-"] if data is not None else []),
                       input=data, capture_output=True, text=True)
    return r.stdout


def runpod(method, path, body=None):
    out = curl("-X", method, "https://rest.runpod.io/v1" + path, "-H", "Authorization: Bearer " + KEY,
               "-H", "content-type: application/json", data=json.dumps(body) if body is not None else None)
    return json.loads(out) if out.strip().startswith(("{", "[")) else out


def ops(cmd=None):
    pid = open(POD_FILE).read().strip()
    url = f"https://{pid}-8001.proxy.runpod.net/"
    if cmd is None:
        return curl(url, "-H", "x-token: " + TOKEN)
    return curl("-X", "POST", url, "-H", "x-token: " + TOKEN, data=cmd)


def create():
    boot = f"(git clone -q {REPO} /workspace/app || git -C /workspace/app pull -q) && bash /workspace/app/start.sh"
    pod = runpod("POST", "/pods", {
        "name": "seoul-hy3d-api",
        "imageName": "runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04",
        "gpuTypeIds": ["NVIDIA H100 80GB HBM3", "NVIDIA H100 PCIe", "NVIDIA H100 NVL", "NVIDIA A100-SXM4-80GB",
                       "NVIDIA A100 80GB PCIe"],
        "gpuCount": 1, "cloudType": "SECURE", "containerDiskInGb": 60, "volumeInGb": 250, "volumeMountPath": "/workspace",
        "ports": ["8000/http", "8001/http"], "env": {"GEN3D_TOKEN": TOKEN},
        "dockerEntrypoint": ["bash", "-c"], "dockerStartCmd": [boot],
    })
    if isinstance(pod, dict) and pod.get("id"):
        open(POD_FILE, "w").write(pod["id"])
        print(pod["id"], pod.get("machine", {}).get("gpuTypeId"), pod.get("costPerHr"))
        print(f"API: https://{pod['id']}-8000.proxy.runpod.net  (token: {tok_path})")
    else:
        print(str(pod)[:500])


RESTART = "cd /workspace/app && git pull -q && bash restart-gateway.sh"


def push():
    subprocess.run(["git", "-C", D, "push", "-q", "origin", "main"], check=True)
    print(ops(RESTART))


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "create":
        create()
    elif a[0] == "push":
        push()
    elif a[0] == "sh":
        r = json.loads(ops(a[1]))
        print(r["out"], r["err"], "exit", r["code"])
    else:
        print(ops())
