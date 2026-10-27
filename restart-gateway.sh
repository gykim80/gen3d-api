#!/bin/bash
# 게이트웨이 재시작 — 별도 스크립트라 pgrep 이 호출한 셸 자신을 잡지 않는다 · setsid 로 ops 세션과 분리
pgrep -f "uvicorn gateway" | xargs -r kill
pgrep -f "app/runners/" | xargs -r kill
sleep 1
cd /workspace/app
setsid nohup python3 -m uvicorn gateway:app --host 0.0.0.0 --port 8000 > /workspace/logs/gateway.log 2>&1 < /dev/null &
git log -1 --oneline
