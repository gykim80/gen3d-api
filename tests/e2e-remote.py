# 원격 E2E — 실제 pod 에서 모델별 잡을 하나씩 돌리고 결과를 내려받는다
#   python3 tests/e2e-remote.py [triposplat|hunyuan3d-2.1|worldmirror-2.0|partllm ...]
#   입력은 공개 예제 이미지 URL 또는 job:// 참조라 이 PC 에서 올리는 파일이 없다
import json, os, subprocess, sys, time

API = f"https://{open(os.path.expanduser('~/.gen3d-api-pod')).read().strip()}-8000.proxy.runpod.net"
AUTH = "Authorization: Bearer " + (os.environ.get("GEN3D_API_KEY") or open(os.path.expanduser("~/.gen3d-api-token")).read().strip())
OUT = os.path.expanduser("~/Desktop/ondo/output/gen3d")
RAW = "https://raw.githubusercontent.com"
WM = f"{RAW}/Tencent-Hunyuan/HY-World-2.0/main/examples/worldrecon/realistic/Building"

CASES = {
    "triposplat": ([f"{RAW}/VAST-AI-Research/TripoSplat/main/static/example_inputs/creature_butterfly.webp"],
                   {"num_gaussians": 262144}),
    "hunyuan3d-2.1": ([f"{RAW}/Tencent-Hunyuan/Hunyuan3D-2.1/main/assets/demo.png"], {"texture": True}),
    "worldmirror-2.0": ([f"{WM}/frame_{i:04d}.png" for i in range(5)], {}),
    # partllm 은 직전 hunyuan 결과 메시를 쓴다
    # 같은 실행에 hunyuan 결과가 있으면 그 메시를, 없으면 Khronos 공개 샘플 의자를 분할한다
    "partllm": ([f"{RAW}/KhronosGroup/glTF-Sample-Assets/main/Models/SheenChair/glTF-Binary/SheenChair.glb"],
                {"mode": "full_shape", "prompt_set": "general"}),
}


def curl(*a):
    return subprocess.run(["curl", "-s", "-m", "600", *a, "-H", AUTH], capture_output=True, text=True).stdout


def run(model, urls, params):
    r = json.loads(curl("-X", "POST", f"{API}/v1/jobs/{model}", "-F", "urls=" + json.dumps(urls),
                        "-F", "params=" + json.dumps(params)))
    if "id" not in r:
        print(model, "submit failed:", r); return None
    jid, t0 = r["id"], time.time()
    while True:
        j = json.loads(curl(f"{API}/v1/jobs/{jid}"))
        if j["status"] in ("succeeded", "failed"):
            break
        time.sleep(10)
    print(f"[{model}] {j['status']} in {time.time() - t0:.0f}s  info={j.get('info')}  error={j.get('error')}")
    d = f"{OUT}/{model}-{jid}"
    os.makedirs(d, exist_ok=True)
    for name, u in zip(j.get("files", []), j.get("urls", [])):
        subprocess.run(["curl", "-s", "-o", f"{d}/{name}", "-H", AUTH, API + u])
        print(f"   {name}  {os.path.getsize(f'{d}/{name}'):,} B")
    return j


if __name__ == "__main__":
    last_mesh = None
    for m in sys.argv[1:] or list(CASES):
        urls, params = CASES[m]
        if m == "partllm" and last_mesh:
            urls = [last_mesh]
        j = run(m, urls, params)
        if m == "hunyuan3d-2.1" and j and j["status"] == "succeeded":
            last_mesh = f"job://{j['id']}/shape.glb"
