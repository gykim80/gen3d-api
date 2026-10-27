#!/bin/bash
# 게이트웨이 로컬 스모크 테스트 — 가짜 러너로 인증 · 잡 큐 · 워커 프로토콜 · 파일 다운로드를 확인한다(GPU 불필요)
set -e
T=$(mktemp -d)
mkdir -p $T/app/runners $T/logs $T/ready $T/venvs/triposplat/bin
cd "$(dirname "$0")/.."
sed "s#W = \"/workspace\"#W = \"$T\"#" gateway.py > $T/app/gateway.py
cp runners/common.py $T/app/runners/
cat > $T/app/runners/triposplat.py <<'PY'
from common import serve
def run(s, inputs, out, p):
    print("noise from library")  # stdout 오염 테스트
    f = out + "/splat.ply"; open(f, "w").write(open(inputs[0]).read()[:5]); return [f], {"n": p.get("num_gaussians")}
serve(lambda: None, run)
PY
ln -s "$(command -v python3)" $T/venvs/triposplat/bin/python
touch $T/ready/triposplat
cd $T/app
GEN3D_TOKEN=t python3 -m uvicorn gateway:app --port 8765 > $T/gw.log 2>&1 &
GW=$!
trap 'kill $GW' EXIT
sleep 3
echo hello-mesh > $T/x.png
A="Authorization: Bearer t"
curl -s localhost:8765/v1/models -H "$A"; echo
curl -s -o /dev/null -w "noauth %{http_code}\n" localhost:8765/v1/models
curl -s -X POST localhost:8765/v1/jobs/hunyuan3d-2.1 -H "$A" -F files=@$T/x.png; echo
R=$(curl -s -X POST localhost:8765/v1/jobs/triposplat -H "$A" -F files=@$T/x.png -F 'params={"num_gaussians":65536}')
echo "$R"
J=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['id'])" "$R")
sleep 2
curl -s localhost:8765/v1/jobs/$J -H "$A"; echo
echo "file: $(curl -s localhost:8765/v1/jobs/$J/files/splat.ply -H "$A")"
