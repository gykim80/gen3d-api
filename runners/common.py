# 러너 공통 루프 — 모델을 한 번 로드해 두고 stdin 잡을 하나씩 처리한다(라이브러리 print 는 stderr 로 돌린다)
import json, os, sys, traceback

_proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr


def serve(load, run):
    """load() → state, run(state, inputs, out_dir, params) → (files, info)"""
    state = load()
    for line in sys.stdin:
        job = json.loads(line)
        try:
            os.makedirs(job["out_dir"], exist_ok=True)
            files, info = run(state, job["inputs"], job["out_dir"], job.get("params") or {})
            msg = {"ok": True, "files": files, "info": info}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        _proto.write(json.dumps(msg) + "\n")


def collect(out_dir, exts):
    """out_dir 하위의 결과 파일을 평평하게 out_dir 로 끌어올려 목록을 돌려준다"""
    files = []
    for root, _, names in os.walk(out_dir):
        for n in names:
            if n.lower().endswith(exts):
                src = os.path.join(root, n)
                rel = os.path.relpath(src, out_dir).replace(os.sep, "__")
                dst = os.path.join(out_dir, rel)
                if src != dst:
                    os.replace(src, dst)
                files.append(dst)
    return sorted(files)
