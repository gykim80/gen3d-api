# UniMate — 리깅된 메시 + 텍스트 → 그 골격 전용 모션 → 메시에 구운 animated.glb
#   1) rig_preprocess(관절 라벨 · cond.npy · 정규화 메시) 2) sample(텍스트 → 모션) 3) run_animate_motion.sh(굽기)
import glob, json, os, shutil, subprocess, sys, time

R = "/workspace/repos/UniMate"
EXP = f"{R}/outputs/unimate_uniml3d_f60_v3"
from common import collect, serve  # noqa: E402


def py(args, env):
    r = subprocess.run([sys.executable, "-m", *args], cwd=R, env=env, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {(r.stderr or r.stdout)[-1500:]}")


def run(_, inputs, out, p):
    t0 = time.time()
    env = {**os.environ, "PATH": f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}"}
    prompts = p.get("prompts") or [p.get("prompt", "An object walks forward.")]
    rig = f"{out}/../rig"
    os.makedirs(rig, exist_ok=True)
    src = f"{rig}/character{os.path.splitext(inputs[0])[1].lower()}"
    shutil.copy(inputs[0], src)
    pre = ["data_process.rig_preprocess", "run", "--input", src, "--output_dir", rig, "--no_review"]
    if p.get("rest_rotation"):
        pre += ["--rest_rotation", *map(str, p["rest_rotation"])]
    py(pre, env)
    t1 = time.time()
    samples = f"{out}/../samples"
    py(["unimate.inference.sample", "--exp_dir", EXP, "--asset", rig, "--prompt", *prompts,
        "--num_repetitions", str(p.get("num_repetitions", 2)), "--cfg_scale", str(p.get("cfg_scale", 3)),
        "--output_dir", samples], env)
    t2 = time.time()
    r = subprocess.run(["bash", "scripts/run_animate_motion.sh", samples, out], cwd=R, env=env, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
    if r.returncode != 0:
        raise RuntimeError(f"animate failed: {(r.stderr or r.stdout)[-1500:]}")
    # 관절 라벨 미리보기 · 매니페스트(프롬프트 ↔ 파일)도 함께 돌려준다
    for f in ("preview.png", "annotation_preview.png", "annotation.json", "summary.json"):
        if os.path.exists(f"{rig}/{f}"):
            shutil.copy(f"{rig}/{f}", f"{out}/rig_{f}")
    for m in glob.glob(f"{samples}/**/manifest.json", recursive=True)[:1]:
        shutil.copy(m, f"{out}/manifest.json")
    files = [f for f in collect(out, (".glb", ".png", ".json")) if not f.endswith(".fbx")]
    return files, {"preprocess_sec": round(t1 - t0, 1), "sample_sec": round(t2 - t1, 1), "sec": round(time.time() - t0, 1),
                   "prompts": prompts}


serve(lambda: None, run)
