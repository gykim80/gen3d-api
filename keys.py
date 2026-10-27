# API 키 저장소 — 외부 호출자별 키 발급·조회·폐기 · 원문은 발급 때 한 번만 돌려주고 SHA-256 해시만 저장한다
#   키 형식: g3d_<key_id 8자>_<비밀 40자> — key_id 로 찾고 해시를 상수 시간 비교한다
import hashlib, hmac, json, os, re, secrets, threading, time

PATH = os.environ.get("GEN3D_KEYS", "/workspace/keys.json")
KEY_RE = re.compile(r"^g3d_([0-9a-f]{8})_([A-Za-z0-9_-]{40})$")
_lock = threading.Lock()


def _load():
    try:
        return json.load(open(PATH))
    except (FileNotFoundError, ValueError):
        return {}


def _save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PATH)


def _hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def public(kid, k):
    return {"key_id": kid, "name": k["name"], "prefix": f"g3d_{kid}_…", "created_at": k["created_at"],
            "last_used_at": k.get("last_used_at"), "revoked_at": k.get("revoked_at"),
            "max_queued": k.get("max_queued", 10)}


def issue(name, max_queued=10):
    with _lock:
        d = _load()
        kid = secrets.token_hex(4)
        while kid in d:
            kid = secrets.token_hex(4)
        secret = secrets.token_urlsafe(30)[:40].ljust(40, "x")
        d[kid] = {"name": name, "hash": _hash(secret), "created_at": time.time(), "max_queued": max_queued}
        _save(d)
    return {"api_key": f"g3d_{kid}_{secret}", **public(kid, d[kid])}


def list_keys():
    return [public(kid, k) for kid, k in sorted(_load().items(), key=lambda x: x[1]["created_at"])]


def revoke(kid):
    with _lock:
        d = _load()
        if kid not in d:
            return None
        d[kid].setdefault("revoked_at", time.time())
        _save(d)
        return public(kid, d[kid])


def verify(raw):
    """유효하면 key_id 와 설정을, 아니면 None"""
    m = KEY_RE.match(raw or "")
    if not m:
        return None
    kid, secret = m.groups()
    k = _load().get(kid)
    if not k or k.get("revoked_at") or not hmac.compare_digest(k["hash"], _hash(secret)):
        return None
    # last_used 는 1분 단위로만 기록해 파일 쓰기를 줄인다
    if time.time() - k.get("last_used_at", 0) > 60:
        with _lock:
            d = _load()
            if kid in d:
                d[kid]["last_used_at"] = time.time()
                _save(d)
    return {"key_id": kid, "name": k["name"], "max_queued": k.get("max_queued", 10)}
