# Hunyuan3D-2.1 — 이미지 → 형상(DiT) → PBR 텍스처 → .glb
import os, sys, time

R = "/workspace/repos/Hunyuan3D-2.1"
os.chdir(R)
sys.path[:0] = [R, f"{R}/hy3dshape", f"{R}/hy3dpaint"]
from common import serve  # noqa: E402


def load():
    try:
        from torchvision_fix import apply_fix
        apply_fix()
    except Exception:  # noqa: BLE001
        pass
    import types

    import trimesh
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dshape.rembg import BackgroundRemover

    # bpy(Blender) 는 obj→glb 변환에만 쓰이는데 python 3.10 휠이 없다 → 빈 모듈로 import 를 통과시키고 trimesh 로 변환
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    import textureGenPipeline
    from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    def obj_to_glb(obj_path, glb_path, *_, **__):
        trimesh.load(obj_path, force="mesh").export(glb_path)
        return True

    textureGenPipeline.convert_obj_to_glb = obj_to_glb

    shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained("tencent/Hunyuan3D-2.1")
    conf = Hunyuan3DPaintConfig(6, 512)
    conf.realesrgan_ckpt_path = "hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
    conf.multiview_cfg_path = "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
    conf.custom_pipeline = "hy3dpaint/hunyuanpaintpbr"
    paint = Hunyuan3DPaintPipeline(conf)
    return {"shape": shape, "paint": paint, "rembg": BackgroundRemover()}


def run(s, inputs, out, p):
    import torch
    from PIL import Image

    t0 = time.time()
    img = Image.open(inputs[0])
    # 알파가 없으면 배경 제거
    if img.mode != "RGBA" or img.getchannel("A").getextrema() == (255, 255):
        img = s["rembg"](img.convert("RGB"))
    img = img.convert("RGBA")
    src = f"{out}/input_rgba.png"
    img.save(src)
    gen = torch.Generator("cuda").manual_seed(int(p.get("seed", 1234)))
    mesh = s["shape"](image=img, num_inference_steps=int(p.get("steps", 50)), octree_resolution=int(p.get("octree", 384)),
                      generator=gen)[0]
    shape_path = f"{out}/shape.glb"
    mesh.export(shape_path)
    files, info = [shape_path], {"shape_sec": round(time.time() - t0, 1)}
    if p.get("texture", True):
        t1 = time.time()
        tex = s["paint"](mesh_path=shape_path, image_path=src, output_mesh_path=f"{out}/textured.obj")
        # 페인트 파이프라인은 obj + 같은 이름 glb 를 남긴다
        for f in sorted(os.listdir(out)):
            if f.startswith("textured") and f.endswith((".glb", ".obj", ".mtl", ".jpg", ".png")):
                files.append(f"{out}/{f}")
        info["texture_sec"] = round(time.time() - t1, 1)
        info["paint_return"] = str(tex)
    return files, info


serve(load, run)
