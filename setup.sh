#!/bin/bash
# gen3d 모델 설치 — 모델마다 venv 를 따로 만든다(torch 버전이 서로 다르다) · 끝나면 /workspace/ready/<모델> 마커
#   재부팅 시 다시 불려도 ready 마커가 있는 모델은 건너뛴다(/workspace 는 볼륨이라 남는다)
set -x
W=/workspace
export HF_HOME=$W/hf PIP_ROOT_USER_ACTION=ignore TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" MAX_JOBS=16
mkdir -p $W/{logs,ready,repos,venvs,models,jobs}
command -v uv || pip install -q uv
SYS_PY=$(command -v python3)

triposplat() {
  V=$W/venvs/triposplat
  cd $W/repos && { [ -d TripoSplat ] || git clone -q https://github.com/VAST-AI-Research/TripoSplat; } && cd TripoSplat
  # 이미지 기본 torch 2.8(cu128) 를 그대로 쓴다
  uv venv -q --system-site-packages -p $SYS_PY $V
  uv pip install -q --python $V/bin/python numpy safetensors pillow tqdm "huggingface_hub[cli]"
  $V/bin/hf download VAST-AI/TripoSplat --local-dir ckpts
}

hy3d() {
  V=$W/venvs/hy3d
  cd $W/repos && { [ -d Hunyuan3D-2.1 ] || git clone -q https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1; } && cd Hunyuan3D-2.1
  # bpy==4.0 은 python 3.10 휠만 있다
  uv venv -q --seed -p 3.10 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
  grep -v -E "extra-index-url|gradio" requirements.txt > /tmp/hy3d-req.txt
  $P -r /tmp/hy3d-req.txt
  $P setuptools wheel ninja pybind11
  export PATH=$V/bin:$PATH
  (cd hy3dpaint/custom_rasterizer && $P --no-build-isolation -e .)
  (cd hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh)
  mkdir -p hy3dpaint/ckpt
  [ -f hy3dpaint/ckpt/RealESRGAN_x4plus.pth ] || wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth -P hy3dpaint/ckpt
  $V/bin/python -c "from huggingface_hub import snapshot_download as s; s('tencent/Hunyuan3D-2.1')"
}

hyworld() {
  V=$W/venvs/hyworld
  cd $W/repos && { [ -d HY-World-2.0 ] || git clone -q https://github.com/Tencent-Hunyuan/HY-World-2.0; } && cd HY-World-2.0
  uv venv -q --seed -p 3.11 $V
  P="uv pip install -q --python $V/bin/python"
  $P torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
  $P -r requirements.txt
  # WorldMirror 서브폴더만 받는다(HY-Pano-2.0 80B 는 단일 GPU 로 못 돌린다)
  $V/bin/python -c "from huggingface_hub import snapshot_download as s; s('tencent/HY-World-2.0', allow_patterns=['HY-WorldMirror-2.0/*'])"
}

partllm() {
  V=$W/venvs/partllm
  cd $W/repos && { [ -d PartLLM ] || git clone -q https://github.com/czvvd/PartLLM; } && cd PartLLM
  uv venv -q --seed -p 3.11 $V
  . $V/bin/activate
  bash scripts/install.sh
  pip install -q "huggingface_hub[cli]"
  hf download Czvvd/PartLLM --local-dir $W/models/partllm
  deactivate
}

install() {  # install <함수> <모델 이름>
  [ -f $W/ready/$2 ] && return 0
  ( $1 ) > $W/logs/install-$2.log 2>&1 && touch $W/ready/$2 || echo "INSTALL FAILED: $2" >> $W/logs/install-$2.log
}

apt-get update -qq && apt-get install -y -qq ffmpeg libgl1 libglib2.0-0 libxrender1 libxi6 libxkbcommon0 libsm6 > /dev/null
install triposplat triposplat
# 나머지는 병렬로 — PartLLM(flash-attn 컴파일)이 가장 오래 걸린다
install hy3d hunyuan3d-2.1 &
install hyworld worldmirror-2.0 &
install partllm partllm &
wait
echo SETUP DONE
