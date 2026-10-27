# gen3d pod 운영 — python3 deploy.py create | push | status | sh "<명령>"
#   create: H100 pod 생성(부팅 시 git 저장소를 /workspace/app 에 clone 하고 start.sh 실행)
#   push:   git push 후 pod 에서 git pull + 게이트웨이 재시작 · status: 설치 로그 · sh: 원격 셸
#   코드는 git 으로만 옮긴다 — 사내망 외부 업로드 차단 정책 때문에 API 본문에 코드를 싣지 않는다
import json, os, secrets, subprocess, sys, time

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
    # gh 활성 계정이 다른 계정일 수 있어 저장소 소유 계정(gykim80) 토큰으로 push 한다
    tok = subprocess.run(["gh", "auth", "token", "-u", "gykim80"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-C", D, "push", "-q", f"https://gykim80:{tok}@github.com/gykim80/gen3d-api.git", "main"],
                   check=True)
    print(ops(RESTART))


def api_base():
    return f"https://{open(POD_FILE).read().strip()}-8000.proxy.runpod.net"


def admin_api(method, path, body=None):
    out = curl("-X", method, api_base() + path, "-H", "Authorization: Bearer " + TOKEN,
               "-H", "content-type: application/json", data=json.dumps(body) if body is not None else None)
    try:
        return json.loads(out)
    except ValueError:
        sys.exit(f"API 응답을 읽지 못했습니다(pod 가 꺼져 있거나 시작 중일 수 있음): {out[:200]}")


def key(a):
    if a[:1] == ["create"] and len(a) >= 2:
        k = admin_api("POST", "/v1/admin/keys", {"name": a[1], "max_queued": int(a[2]) if len(a) > 2 else 10})
        if "api_key" not in k:
            sys.exit(str(k))
        print(f"발급 완료 — 이 키는 다시 볼 수 없으니 지금 전달하세요\n  이름: {k['name']}\n  key_id: {k['key_id']}\n"
              f"  API 키: {k['api_key']}\n  주소: {api_base()}")
    elif a[:1] == ["list"]:
        for k in admin_api("GET", "/v1/admin/keys"):
            state = "폐기" if k["revoked_at"] else "활성"
            print(f"{k['key_id']}  {state}  {k['name']:<24} 큐 {k['max_queued']}  "
                  f"마지막 사용 {time.strftime('%m-%d %H:%M', time.localtime(k['last_used_at'])) if k['last_used_at'] else '-'}")
    elif a[:1] == ["revoke"] and len(a) == 2:
        print(admin_api("DELETE", f"/v1/admin/keys/{a[1]}"))
    else:
        sys.exit("usage: key create <이름> [동시 잡 수] | key list | key revoke <key_id>")


def pod(action):
    pid = open(POD_FILE).read().strip()
    q = {"stop": f'mutation {{ podStop(input:{{podId:"{pid}"}}) {{ id desiredStatus }} }}',
         "start": f'mutation {{ podResume(input:{{podId:"{pid}", gpuCount:1}}) {{ id desiredStatus costPerHr }} }}',
         "info": f'query {{ pod(input:{{podId:"{pid}"}}) {{ id name desiredStatus costPerHr machine {{ gpuDisplayName }} }} }}'}
    if action not in q:
        sys.exit("usage: pod start | stop | info")
    print(curl("https://api.runpod.io/graphql", "-H", "content-type: application/json", "-H", "Authorization: Bearer " + KEY,
               data=json.dumps({"query": q[action]})))


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "create":
        create()
    elif a[0] == "push":
        push()
    elif a[0] == "sh":
        r = json.loads(ops(a[1]))
        print(r["out"], r["err"], "exit", r["code"])
    elif a[0] == "key":
        key(a[1:])
    elif a[0] == "pod":
        pod(a[1] if len(a) > 1 else "info")
    elif a[0] == "url":
        print(api_base())
    else:
        print(ops())
