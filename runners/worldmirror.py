# HY-World 2.0 WorldMirror — 여러 장 사진/영상 → 포인트클라우드 · 3DGS · depth/normal/camera (단일 GPU 로 가능한 HY-World 구성)
import inspect, os, shutil, sys, time

R = "/workspace/repos/HY-World-2.0"
os.chdir(R)
sys.path.insert(0, R)
from common import collect, serve  # noqa: E402


def load():
    from hyworld2.worldrecon.pipeline import WorldMirrorPipeline

    return WorldMirrorPipeline.from_pretrained("tencent/HY-World-2.0")


def run(pipe, inputs, out, p):
    t0 = time.time()
    # 영상 하나면 그대로, 이미지 여러 장이면 폴더로 넘긴다
    if len(inputs) == 1 and inputs[0].lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        src = inputs[0]
    else:
        src = f"{out}/../frames"
        os.makedirs(src, exist_ok=True)
        for f in inputs:
            shutil.copy(f, src)
    sig = inspect.signature(pipe.__call__).parameters
    kw = {"strict_output_path": out} if "strict_output_path" in sig else {"output_path": out}
    res = pipe(src, **kw)
    if isinstance(res, str) and os.path.isdir(res) and os.path.abspath(res) != os.path.abspath(out):
        shutil.copytree(res, f"{out}/recon", dirs_exist_ok=True)
    files = collect(out, (".ply", ".glb", ".json", ".txt", ".bin", ".png", ".mp4"))
    return files, {"sec": round(time.time() - t0, 1), "n_inputs": len(inputs)}


serve(load, run)
