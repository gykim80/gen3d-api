# UniRig — 메시 → 골격 예측 → 스키닝 예측 → 원본 메시에 병합(rigged.glb) · 공식 launch 스크립트를 잡마다 호출
import os, shutil, subprocess, sys, time

R = "/workspace/repos/UniRig"
from common import serve  # noqa: E402


def sh(args, env):
    r = subprocess.run(["bash", *args], cwd=R, env=env, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {(r.stderr or r.stdout)[-1200:]}")


def run(_, inputs, out, p):
    t0 = time.time()
    env = {**os.environ, "PATH": f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}"}
    src = inputs[0]
    ext = os.path.splitext(src)[1].lower()
    mesh = f"{out}/input{ext}"
    shutil.copy(src, mesh)
    seed = str(p.get("seed", 42))
    sh(["launch/inference/generate_skeleton.sh", "--input", mesh, "--output", f"{out}/skeleton.fbx", "--seed", seed], env)
    t1 = time.time()
    sh(["launch/inference/generate_skin.sh", "--input", f"{out}/skeleton.fbx", "--output", f"{out}/skin.fbx"], env)
    t2 = time.time()
    sh(["launch/inference/merge.sh", "--source", f"{out}/skin.fbx", "--target", mesh, "--output", f"{out}/rigged.glb"], env)
    os.remove(mesh)
    files = [f"{out}/{f}" for f in ("rigged.glb", "skin.fbx", "skeleton.fbx") if os.path.exists(f"{out}/{f}")]
    return files, {"skeleton_sec": round(t1 - t0, 1), "skin_sec": round(t2 - t1, 1), "sec": round(time.time() - t0, 1)}


serve(lambda: None, run)
