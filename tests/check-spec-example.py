# 연동 명세서의 Python 예시가 실제 API 와 맞는지 확인 — 문서의 generate() 를 그대로 꺼내 live pod 에 돌린다
#   GEN3D_API_KEY=<발급 키> python3 tests/check-spec-example.py
#   입력은 공개 URL 이라 이 PC 에서 올리는 파일이 없다(예시 맨 아래 업로드 호출은 건너뛴다)
import os, re, sys, tempfile

try:
    # 사내 TLS 검사 프록시 인증서는 OS 신뢰 저장소에만 있다 — 있으면 OS 저장소로 검증(검증 자체는 끄지 않는다)
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

D = os.path.dirname(os.path.abspath(__file__))
doc = open(os.path.join(D, "..", "docs", "api-integration-spec.md")).read()
code = re.search(r"```python\n(.*?)```", doc, re.S).group(1)
code = "\n".join(l for l in code.splitlines() if not l.startswith(("mesh = ", "parts = ")))
ns = {}
exec(code, ns)
ns["API"] = f"https://{open(os.path.expanduser('~/.gen3d-api-pod')).read().strip()}-8000.proxy.runpod.net"
ns["H"] = {"X-API-Key": os.environ["GEN3D_API_KEY"]}

CHAIR = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/SheenChair/glTF-Binary/SheenChair.glb"
out = tempfile.mkdtemp(prefix="gen3d-spec-")
j = ns["generate"]("partllm", urls=[CHAIR], params={"mode": "text_guided", "part_names": ["seat", "backrest", "leg"]},
                   out_dir=out)
print(j["status"], j["info"], j["files"])
missing = [f for f in j["files"] if not os.path.getsize(os.path.join(out, f))]
print("downloaded to", out, "· empty files:", missing)
sys.exit(1 if missing or j["status"] != "succeeded" else 0)
