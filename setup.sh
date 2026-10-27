#!/bin/bash
# gen3d 모델 설치 — 모델마다 venv 를 따로 만든다(torch 버전이 서로 다르다) · 끝나면 /workspace/ready/<모델> 마커
#   재부팅 시 다시 불려도 ready 마커가 있는 모델은 건너뛴다(/workspace 는 볼륨이라 남는다)
set -x
W=/workspace
export HF_HOME=$W/hf PIP_ROOT_USER_ACTION=ignore TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" MAX_JOBS=16
mkdir -p $W/{logs,ready,repos,venvs,models,jobs}
command -v uv || pip install -q uv
SYS_PY=$(command -v python3)
# flash-attn prebuilt 휠(소스 빌드는 1시간 이상)
FA=https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post2

triposplat() {
  V=$W/venvs/triposplat
  cd $W/repos && { [ -d TripoSplat ] || git clone -q https://github.com/VAST-AI-Research/TripoSplat; } && cd TripoSplat
  # 이미지 기본 torch 2.8(cu128) 를 그대로 쓴다
  uv venv -q --clear --system-site-packages -p $SYS_PY $V
  uv pip install -q --python $V/bin/python numpy safetensors pillow tqdm "huggingface_hub[cli]"
  $V/bin/hf download VAST-AI/TripoSplat --local-dir ckpts
}

hy3d() {
  V=$W/venvs/hy3d
  cd $W/repos && { [ -d Hunyuan3D-2.1 ] || git clone -q https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1; } && cd Hunyuan3D-2.1
  # bpy==4.0 은 python 3.10 휠만 있다
  uv venv -q --clear --seed --managed-python -p 3.10 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
  grep -v -E "extra-index-url|gradio|^bpy" requirements.txt > /tmp/hy3d-req.txt
  $P -r /tmp/hy3d-req.txt
  # bpy 는 obj→glb 변환 보조용 — 휠이 없으면 건너뛴다
  $P "bpy==4.0.0" || echo "bpy skipped"
  # lightning_fabric 이 pkg_resources 를 쓴다 — setuptools 80+ 에서 빠졌다
  $P "setuptools<70" wheel ninja pybind11
  export PATH=$V/bin:$PATH
  (cd hy3dpaint/custom_rasterizer && $P --no-build-isolation -e .)
  # 공식 compile_mesh_painter.sh 는 시스템 python3-config 를 써서 확장자 접미사가 어긋난다 → venv 파이썬 기준으로 빌드
  (cd hy3dpaint/DifferentiableRenderer && SUF=$($V/bin/python -c 'import sysconfig;print(sysconfig.get_config_var("EXT_SUFFIX"))') \
    && c++ -O3 -Wall -shared -std=c++11 -fPIC $($V/bin/python -m pybind11 --includes) mesh_inpaint_processor.cpp \
       -o mesh_inpaint_processor$SUF)
  mkdir -p hy3dpaint/ckpt
  [ -f hy3dpaint/ckpt/RealESRGAN_x4plus.pth ] || wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth -P hy3dpaint/ckpt
  $V/bin/python -c "from huggingface_hub import snapshot_download as s; s('tencent/Hunyuan3D-2.1')"
}

hyworld() {
  V=$W/venvs/hyworld
  cd $W/repos && { [ -d HY-World-2.0 ] || git clone -q https://github.com/Tencent-Hunyuan/HY-World-2.0; } && cd HY-World-2.0
  uv venv -q --clear --seed --managed-python -p 3.11 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
  # cupy==13.6.0 은 소스 빌드라 수십 분 걸린다 → CUDA 12 휠로 바꾼다
  sed 's/^cupy==/cupy-cuda12x==/' requirements.txt > /tmp/hyworld-req.txt
  $P -r /tmp/hyworld-req.txt
  # WorldMirror 는 flash_attn 을 import 한다 — 소스 빌드 대신 torch 2.7(cxx11 ABI) 용 prebuilt 휠
  $P "$FA/flash_attn-2.8.3.post2+cu12torch2.7cxx11abiTRUE-cp311-cp311-linux_x86_64.whl"
  # WorldMirror 서브폴더만 받는다(HY-Pano-2.0 80B 는 단일 GPU 로 못 돌린다)
  $V/bin/python -c "from huggingface_hub import snapshot_download as s; s('tencent/HY-World-2.0', allow_patterns=['HY-WorldMirror-2.0/*'])"
}

partllm() {
  V=$W/venvs/partllm
  cd $W/repos && { [ -d PartLLM ] || git clone -q https://github.com/czvvd/PartLLM; } && cd PartLLM
  uv venv -q --clear --seed --managed-python -p 3.11 $V
  . $V/bin/activate
  bash scripts/install.sh
  pip install -q "huggingface_hub[cli]"
  hf download Czvvd/PartLLM --local-dir $W/models/partllm
  deactivate
}

unirig() {
  # 자동 리깅 — 메시 → 골격 예측 → 스키닝 예측 → 원본 메시에 병합(rigged.glb)
  V=$W/venvs/unirig
  cd $W/repos && { [ -d UniRig ] || git clone -q https://github.com/VAST-AI-Research/UniRig; } && cd UniRig
  uv venv -q --clear --seed --managed-python -p 3.11 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
  grep -v -E "^flash_attn|^bpy" requirements.txt > /tmp/unirig-req.txt
  $P -r /tmp/unirig-req.txt "bpy==4.2.0" spconv-cu124 "numpy==1.26.4"
  $P torch_scatter torch_cluster -f https://data.pyg.org/whl/torch-2.5.1+cu124.html
  $P "$FA/flash_attn-2.8.3.post2+cu12torch2.5cxx11abiFALSE-cp311-cp311-linux_x86_64.whl"
  $V/bin/python -c "from huggingface_hub import snapshot_download as s; s('VAST-AI/UniRig', allow_patterns=['skeleton/*', 'skin/*', '*.json'])"
}

unimate() {
  # 텍스트 → 임의 골격 애니메이션(리깅된 메시에 구워 animated.glb)
  V=$W/venvs/unimate
  cd $W/repos && { [ -d UniMate ] || git clone -q https://github.com/Friedrich-M/UniMate; } && cd UniMate
  uv venv -q --clear --seed --managed-python -p 3.10 $V
  # Motion 의존성의 setup.py 가 pkg_resources 를 써서 setuptools<81 + 빌드 격리 끄기가 필요하다
  $V/bin/pip install -q "setuptools<81" wheel
  $V/bin/pip install -q -r requirements.txt --no-build-isolation
  $V/bin/hf download Linzhan/UniMate --repo-type model --local-dir outputs \
    --include "unimate_uniml3d_f60_v3/*.json" --include "unimate_uniml3d_f60_v3/*.npy" \
    --include "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"
}

kimodo() {
  # 텍스트 → 사람(SOMA 77관절) 모션 · BVH 출력
  V=$W/venvs/kimodo
  cd $W/repos && { [ -d kimodo ] || git clone -q https://github.com/nv-tlabs/kimodo; } && cd kimodo
  uv venv -q --clear --seed --managed-python -p 3.10 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124
  $P -e ".[all]"
  # 텍스트 인코더(LLM2Vec)의 베이스 Llama-3-8B-Instruct 는 HF gated — Llama 3 라이선스로 재배포된 공개 미러를
  #   로컬 폴더로 두고 어댑터의 베이스 경로를 그쪽으로 돌린다(TEXT_ENCODERS_DIR)
  E=$W/models/text_encoders
  $V/bin/hf download NousResearch/Meta-Llama-3-8B-Instruct --local-dir $E/llama3-8b-instruct --exclude "original/*"
  for r in mntp mntp-supervised; do
    $V/bin/hf download McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-$r --local-dir $E/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-$r
  done
  for f in $(grep -rl "meta-llama/Meta-Llama-3-8B-Instruct" $E/McGill-NLP --include=*.json); do
    sed -i "s#meta-llama/Meta-Llama-3-8B-Instruct#$E/llama3-8b-instruct#g" $f
  done
  # 첫 생성으로 SOMA 모션 가중치까지 받아 둔다
  cd $W/repos/kimodo && TEXT_ENCODERS_DIR=$E $V/bin/kimodo_gen "A person walks forward." --model Kimodo-SOMA-RP-v1.2 \
    --duration 2.0 --num_samples 1 --seed 0 --output /tmp/kimodo-smoke --bvh --bvh_standard_tpose
}

install() {  # install <함수> <모델 이름>
  [ -f $W/ready/$2 ] && return 0
  # set -e — 중간 단계가 실패하면 바로 멈춰 첫 에러가 로그 끝에 남는다
  #   && · || 문맥 안에서는 bash 가 set -e 를 무시하므로 종료 코드를 따로 받는다
  ( set -e; $1 ) > $W/logs/install-$2.log 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then touch $W/ready/$2; else echo "INSTALL FAILED: $2 (exit $rc)" >> $W/logs/install-$2.log; fi
}

# bash setup.sh <함수> <모델 이름> — 모델 하나만 다시 설치
if [ -n "$2" ]; then
  rm -f $W/ready/$2
  install $1 $2
  exit
fi

apt-get update -qq && apt-get install -y -qq ffmpeg libgl1 libglib2.0-0 libxrender1 libxi6 libxkbcommon0 libsm6 > /dev/null
install triposplat triposplat
# 나머지는 병렬로 — PartLLM(flash-attn 컴파일)이 가장 오래 걸린다
install hy3d hunyuan3d-2.1 &
install hyworld worldmirror-2.0 &
install partllm partllm &
install unirig unirig &
install unimate unimate &
install kimodo kimodo &
wait
echo SETUP DONE
