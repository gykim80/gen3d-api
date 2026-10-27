# TripoSplat — 이미지 한 장 → 3D Gaussian splat (.ply / .splat)
import os, sys, time

R = "/workspace/repos/TripoSplat"
sys.path.insert(0, R)
from common import serve  # noqa: E402


def load():
    from triposplat import TripoSplatPipeline

    c = f"{R}/ckpts"
    return TripoSplatPipeline(ckpt_path=f"{c}/diffusion_models/triposplat_fp16.safetensors",
                              decoder_path=f"{c}/vae/triposplat_vae_decoder_fp16.safetensors",
                              dinov3_path=f"{c}/clip_vision/dino_v3_vit_h.safetensors",
                              flux2_vae_encoder_path=f"{c}/vae/flux2-vae.safetensors",
                              rmbg_path=f"{c}/background_removal/birefnet.safetensors", device="cuda")


def run(pipe, inputs, out, p):
    t0 = time.time()
    n = int(p.get("num_gaussians", 262144))
    g, _ = pipe.run(inputs[0], num_gaussians=n)
    files = [f"{out}/splat.ply", f"{out}/splat.splat"]
    g.save_ply(files[0]); g.save_splat(files[1])
    return files, {"num_gaussians": n, "sec": round(time.time() - t0, 1)}


serve(load, run)
