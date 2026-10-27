#!/bin/bash
# gen3d-api 실행 스크립트 — 배포 · API 키 발급 · 테스트 · 갤러리를 한 곳에서
#   ./run.sh help 로 전체 명령을 본다
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

usage() {
  cat <<'EOF'
gen3d-api — 이미지·영상 → 3D 생성 API (RunPod GPU pod)

배포·운영
  ./run.sh deploy                  새 GPU pod 생성(부팅 시 저장소 clone → 게이트웨이 → 모델 설치)
  ./run.sh push                    코드 변경을 git push 하고 pod 게이트웨이 재시작
  ./run.sh status                  설치 상태 · GPU · 로그 꼬리
  ./run.sh url                     외부 접속 주소(API 기본 URL)
  ./run.sh pod info|start|stop     pod 상태 · 시작 · 정지(정지 중에는 GPU 과금 없음)
  ./run.sh sh "<명령>"             pod 에서 셸 명령 실행

API 키(외부 호출자용)
  ./run.sh key create <이름> [동시잡]  키 발급 — 원문은 이때 한 번만 표시
  ./run.sh key list                발급된 키 목록(활성/폐기 · 마지막 사용)
  ./run.sh key revoke <key_id>     키 폐기(즉시 401)

테스트·확인
  ./run.sh smoke                   로컬 스모크 테스트(GPU 불필요 · 키/인증/분리 검증)
  ./run.sh test [모델 ...]         실제 pod 에서 모델별 E2E(결과 → ~/Desktop/ondo/output/gen3d)
  ./run.sh spec                    연동 명세서의 Python 예시를 live API 로 실행(GEN3D_API_KEY 필요)
  ./run.sh gallery [포트]          결과 갤러리 http://127.0.0.1:8787

문서: docs/api-integration-spec.md (연동 명세서) · docs/gen3d-api.md (운영)
EOF
}

case "${1:-help}" in
  deploy) $PY deploy.py create ;;
  push) $PY deploy.py push ;;
  status) $PY deploy.py status ;;
  url) $PY deploy.py url ;;
  pod) shift; $PY deploy.py pod "${1:-info}" ;;
  sh) shift; $PY deploy.py sh "$*" ;;
  key) shift; $PY deploy.py key "$@" ;;
  test) shift; $PY tests/e2e-remote.py "$@" ;;
  smoke)
    V=${TMPDIR:-/tmp}/gen3d-smoke-venv
    [ -x $V/bin/uvicorn ] || { $PY -m venv $V && $V/bin/pip install -q fastapi uvicorn python-multipart; }
    PATH=$V/bin:$PATH bash tests/smoke-local.sh ;;
  spec)
    V=${TMPDIR:-/tmp}/gen3d-smoke-venv
    [ -x $V/bin/python ] || $PY -m venv $V
    $V/bin/pip install -q requests truststore
    $V/bin/python tests/check-spec-example.py ;;
  gallery) shift; $PY gallery/serve.py "${1:-8787}" ;;
  help|-h|--help) usage ;;
  *) echo "알 수 없는 명령: $1"; echo; usage; exit 1 ;;
esac
