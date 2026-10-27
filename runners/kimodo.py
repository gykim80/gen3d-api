# Kimodo — 텍스트 → 사람(SOMA 77관절) 모션 · BVH(표준 T포즈) + NPZ
import glob, os, subprocess, sys, time

R = "/workspace/repos/kimodo"
from common import serve  # noqa: E402


def run(_, inputs, out, p):
    t0 = time.time()
    env = {**os.environ, "TEXT_ENCODERS_DIR": "/workspace/models/text_encoders",
           "PATH": f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}"}
    prompt = p.get("prompt", "A person walks forward.")
    n = int(p.get("num_samples", 2))
    args = [f"{os.path.dirname(sys.executable)}/kimodo_gen", prompt, "--model", p.get("model", "Kimodo-SOMA-RP-v1.2"),
            "--duration", str(p.get("duration", 4.0)), "--num_samples", str(n), "--seed", str(p.get("seed", 0)),
            "--output", f"{out}/motion", "--bvh", "--bvh_standard_tpose"]
    r = subprocess.run(args, cwd=R, env=env, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    files = sorted(glob.glob(f"{out}/**/*.bvh", recursive=True) + glob.glob(f"{out}/**/*.npz", recursive=True))
    # 하위 폴더에 생기면 out 바로 아래로 끌어올린다
    flat = []
    for f in files:
        dst = f"{out}/{os.path.basename(f)}"
        if f != dst:
            os.replace(f, dst)
        flat.append(dst)
    return flat, {"sec": round(time.time() - t0, 1), "prompt": prompt, "fps": 30}


serve(lambda: None, run)
