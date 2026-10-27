#!/bin/bash
# pod 부팅 시 실행 — ops · 게이트웨이를 먼저 띄우고 설치를 이어 간다(설치 중인 모델은 503 으로 응답)
W=/workspace
mkdir -p $W/logs
cd $W/app
nohup python3 ops.py > $W/logs/ops.log 2>&1 &
pip install -q fastapi "uvicorn[standard]" python-multipart
nohup python3 -m uvicorn gateway:app --host 0.0.0.0 --port 8000 > $W/logs/gateway.log 2>&1 &
bash setup.sh > $W/logs/setup.log 2>&1
sleep infinity
