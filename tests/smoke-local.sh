#!/bin/bash
# 게이트웨이 로컬 스모크 테스트(GPU 불필요) — 가짜 러너로 키 발급·인증·키별 잡 분리·폐기·오류 형식·SSRF 차단을 확인한다
#   PATH 에 fastapi · uvicorn · python-multipart 가 있는 파이썬이 필요하다
set -e
T=$(mktemp -d)
mkdir -p $T/app/runners $T/logs $T/ready $T/venvs/triposplat/bin
cd "$(dirname "$0")/.."
sed "s#W = \"/workspace\"#W = \"$T\"#" gateway.py > $T/app/gateway.py
cp keys.py $T/app/
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
GEN3D_TOKEN=admintok GEN3D_KEYS=$T/keys.json python3 -m uvicorn gateway:app --port 8765 > $T/gw.log 2>&1 &
GW=$!
trap 'kill $GW' EXIT
sleep 3
B=http://127.0.0.1:8765
ADM="Authorization: Bearer admintok"
echo hello-mesh > $T/x.png
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1 (got $2, want $3)"; fail=$((fail+1)); fi; }
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
js() { python3 -c "import json,sys;print(json.loads(sys.argv[1])$2)" "$1"; }

KA=$(curl -s -X POST $B/v1/admin/keys -H "$ADM" -H "content-type: application/json" -d '{"name":"partner-a"}')
KB=$(curl -s -X POST $B/v1/admin/keys -H "$ADM" -H "content-type: application/json" -d '{"name":"partner-b","max_queued":1}')
A=$(js "$KA" "['api_key']"); BK=$(js "$KB" "['api_key']"); AID=$(js "$KA" "['key_id']")
check "issued key format" "$(echo $A | grep -cE '^g3d_[0-9a-f]{8}_.{40}$')" 1
check "no key → 401" "$(code $B/v1/models)" 401
check "bad key → 401" "$(code $B/v1/models -H 'Authorization: Bearer g3d_deadbeef_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')" 401
check "key A (Bearer) → 200" "$(code $B/v1/models -H "Authorization: Bearer $A")" 200
check "key A (X-API-Key) → 200" "$(code $B/v1/models -H "X-API-Key: $A")" 200
check "key → admin api 403" "$(code $B/v1/admin/keys -H "X-API-Key: $A")" 403
check "list keys hides hash" "$(curl -s $B/v1/admin/keys -H "$ADM" | grep -c hash)" 0
check "not-ready model → 503" "$(code -X POST $B/v1/jobs/partllm -H "X-API-Key: $A" -F files=@$T/x.png)" 503
check "unknown model → 404" "$(code -X POST $B/v1/jobs/nope -H "X-API-Key: $A" -F files=@$T/x.png)" 404
check "private url → 400" "$(code -X POST $B/v1/jobs/triposplat -H "X-API-Key: $A" -F 'urls=["http://127.0.0.1:8765/health"]')" 400
check "error body shape" "$(curl -s -X POST $B/v1/jobs/nope -H "X-API-Key: $A" -F files=@$T/x.png | grep -c '"error":"unknown_model"')" 1

R=$(curl -s -X POST $B/v1/jobs/triposplat -H "X-API-Key: $A" -F files=@$T/x.png -F 'params={"num_gaussians":65536}')
J=$(js "$R" "['id']"); sleep 2
check "job succeeded" "$(js "$(curl -s $B/v1/jobs/$J -H "X-API-Key: $A")" "['status']")" succeeded
check "result file" "$(curl -s $B/v1/jobs/$J/files/splat.ply -H "X-API-Key: $A")" hello
check "owner hidden in response" "$(curl -s $B/v1/jobs/$J -H "X-API-Key: $A" | grep -c owner)" 0
check "key B cannot see A's job" "$(code $B/v1/jobs/$J -H "X-API-Key: $BK")" 404
check "key B cannot chain A's job" "$(code -X POST $B/v1/jobs/triposplat -H "X-API-Key: $BK" -F "urls=[\"job://$J/splat.ply\"]")" 404
check "key A chains own job" "$(code -X POST $B/v1/jobs/triposplat -H "X-API-Key: $A" -F "urls=[\"job://$J/splat.ply\"]")" 202
check "key A list sees own jobs" "$(js "$(curl -s $B/v1/jobs -H "X-API-Key: $A")" '.__len__()')" 2
check "key B list empty" "$(js "$(curl -s $B/v1/jobs -H "X-API-Key: $BK")" '.__len__()')" 0
check "admin sees all" "$(js "$(curl -s $B/v1/jobs -H "$ADM")" '.__len__()')" 2
check "revoke A" "$(code -X DELETE $B/v1/admin/keys/$AID -H "$ADM")" 200
check "revoked key → 401" "$(code $B/v1/models -H "X-API-Key: $A")" 401
check "keys file is 0600" "$(stat -f %Lp $T/keys.json 2>/dev/null || stat -c %a $T/keys.json)" 600
echo "pass $pass · fail $fail"
[ $fail -eq 0 ]
