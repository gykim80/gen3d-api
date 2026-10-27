# PartLLM — 메시 → 파트 분할(색칠 메시 + 파트별 ply) · 공식 infer.sh 를 잡마다 호출한다
import os, shutil, subprocess, sys, time

R = "/workspace/repos/PartLLM"
from common import collect, serve  # noqa: E402

MODEL = "/workspace/models/partllm"


def load():
    return None


def run(_, inputs, out, p):
    t0 = time.time()
    mode = p.get("mode", "full_shape")
    mesh = inputs[0]
    env = {**os.environ, "MODEL_PATH": MODEL, "PATH": f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}"}
    if mode == "full_shape":
        # full_shape 는 폴더를 입력으로 받는다
        src = f"{out}/../mesh_dir"
        os.makedirs(src, exist_ok=True)
        shutil.copy(mesh, src)
        args = ["full_shape", MODEL, src, out, "--prompt_set", p.get("prompt_set", "general")]
        if p.get("num_parts"):
            args += ["--num_parts", str(p["num_parts"])]
    elif mode == "text_guided":
        args = ["text_guided", MODEL, mesh, out, "--part_names", *p.get("part_names", [])]
    elif mode == "interactive":
        args = ["interactive", MODEL, mesh, out, "--point", *map(str, p["point"])]
    else:
        raise ValueError(f"unknown mode {mode}")
    args += ["--save_mesh", "true", "--save_per_part", "true"]
    r = subprocess.run(["bash", "scripts/infer.sh", *args], cwd=R, env=env, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-6000:] + r.stderr[-6000:])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    files = collect(out, (".glb", ".ply", ".obj", ".json", ".npy", ".txt"))
    return files, {"sec": round(time.time() - t0, 1), "mode": mode}


serve(load, run)
