# gen3d API 연동 명세서

이미지·영상·메시를 보내면 GPU 서버가 3D 결과물을 만들어 돌려주는 HTTP API.
모든 생성은 **비동기 잡**이다 — 잡을 만들고, 상태를 조회하고, 끝나면 결과 파일을 받는다.

| 항목 | 값 |
|---|---|
| 기본 URL | `https://<podId>-8000.proxy.runpod.net` (발급 시 함께 전달) |
| 프로토콜 | HTTPS · JSON 응답(UTF-8) · 입력은 `multipart/form-data` |
| 인증 | 발급받은 API 키 — `X-API-Key: <키>` 또는 `Authorization: Bearer <키>` |
| 버전 | v1 (경로 접두사 `/v1`) |

## 1. 지원 모델

| 모델 ID | 입력 | 출력 | 처리 시간(H100, 모델 로딩 후) |
|---|---|---|---|
| `hunyuan3d-2.1` | 이미지 1장 | 텍스처 메시 `textured.glb` + 형상 `shape.glb` + PBR 텍스처(`textured.jpg`·`_metallic`·`_roughness`) | 약 75초 (형상 17초 · 텍스처 57초) |
| `triposplat` | 이미지 1장 | 3D Gaussian splat `splat.ply` · `splat.splat` | 약 6~8초 |
| `partllm` | 메시 1개(`.glb` `.gltf` `.ply` `.obj` `.stl` `.off` `.fbx`) | 부위 색 메시 `*_pred_mesh.ply` + 부위별 `*_part_<n>_<이름>.ply` + 라벨 `*.npy`·`*_metadata.json` | 약 60~95초 |
| `worldmirror-2.0` | 다시점 이미지 여러 장 또는 영상 1개 | 포인트클라우드 · 3DGS `.ply` · 깊이/노멀/카메라 | 준비 중(`ready: false` 동안 503) |

- 각 모델의 첫 잡은 모델을 GPU 에 올리는 시간(30~120초)이 더해진다
- 서버는 GPU 1장으로 잡을 **한 번에 하나씩** 순서대로 처리한다. 다른 모델로 바뀌면 로딩 시간이 다시 든다
- 이미지는 배경이 투명(RGBA)하면 그대로 쓰고, 아니면 서버가 배경을 자동 제거한다(`hunyuan3d-2.1`·`triposplat`)

## 2. 인증

API 키는 운영자가 호출자(파트너·서비스)별로 발급한다. 형식은 `g3d_<key_id 8자>_<비밀 40자>`.

```http
X-API-Key: g3d_1a2b3c4d_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- 키 원문은 발급 때 한 번만 전달된다. 서버는 해시만 보관하므로 분실하면 재발급한다
- 키마다 **자기 잡만** 조회·다운로드·체이닝할 수 있다. 다른 키의 잡 ID 로 요청하면 404
- 키마다 동시 잡 한도가 있다(기본 10개, 대기+실행 합계). 넘으면 429
- 폐기된 키는 즉시 401
- 키는 서버 간 호출에만 쓴다. 브라우저·앱 번들에 넣지 않는다

## 3. 엔드포인트 요약

| 메서드 | 경로 | 설명 | 성공 |
|---|---|---|---|
| GET | `/health` | 서버 상태(인증 불필요) | 200 |
| GET | `/v1/models` | 모델 목록 · 준비 여부 | 200 |
| POST | `/v1/jobs/{model}` | 잡 생성 | 202 |
| GET | `/v1/jobs` | 내 잡 목록(최신순) | 200 |
| GET | `/v1/jobs/{id}` | 잡 상태 · 결과 파일 목록 | 200 |
| GET | `/v1/jobs/{id}/files/{name}` | 결과 파일 다운로드 | 200 |

## 4. 엔드포인트 상세

### 4.1 `GET /v1/models`

```json
{
  "hunyuan3d-2.1": {"input": "image", "desc": "image → textured PBR mesh (.glb)", "ready": true, "loaded": false},
  "triposplat": {"input": "image", "desc": "image → 3D Gaussian splat (.ply/.splat)", "ready": true, "loaded": true}
}
```

`ready: false` 인 모델에 잡을 넣으면 503. `loaded: true` 면 GPU 에 올라가 있어 로딩 시간 없이 바로 시작한다.

### 4.2 `POST /v1/jobs/{model}` — 잡 생성

`multipart/form-data` 필드:

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `files` | 파일(여러 번 가능) | `urls` 와 둘 중 하나 | 입력 파일 업로드 |
| `urls` | JSON 배열 문자열 | `files` 와 둘 중 하나 | 공개 `http(s)` URL 또는 `job://<잡id>/<파일명>` |
| `params` | JSON 객체 문자열 | 아니오 | 모델별 옵션(5장) |

- 입력은 합쳐서 최대 64개, URL 입력 1개당 최대 500 MB
- URL 은 공개 주소만 받는다(사설·루프백 주소는 400)
- `job://` 는 내 잡의 결과 파일을 다음 모델 입력으로 바로 넘긴다(재업로드 불필요)

응답 `202 Accepted`:

```json
{"id": "33caeb9e799f", "status": "queued", "position": 1}
```

### 4.3 `GET /v1/jobs/{id}` — 상태 조회

```json
{
  "id": "33caeb9e799f",
  "model": "triposplat",
  "status": "succeeded",
  "params": {"num_gaussians": 262144},
  "created_at": 1793066201.12,
  "started_at": 1793066201.15,
  "finished_at": 1793066232.40,
  "info": {"num_gaussians": 262144, "sec": 7.3},
  "files": ["splat.ply", "splat.splat"],
  "urls": ["/v1/jobs/33caeb9e799f/files/splat.ply", "/v1/jobs/33caeb9e799f/files/splat.splat"]
}
```

| `status` | 뜻 | 다음 동작 |
|---|---|---|
| `queued` | 대기 중 | 5~10초 간격으로 다시 조회 |
| `running` | GPU 처리 중 | 5~10초 간격으로 다시 조회 |
| `succeeded` | 완료 | `urls` 의 파일을 받는다 |
| `failed` | 실패 | `error` 메시지 확인 후 재시도 여부 판단 |

- 시각은 Unix epoch 초(UTC)
- `info` 는 모델별 처리 정보(소요 초 등)이며 형식이 바뀔 수 있다
- 서버 재시작으로 끊긴 잡은 `failed` + `error: "interrupted by server restart"` — 같은 요청으로 다시 만든다

### 4.4 `GET /v1/jobs` — 내 잡 목록

쿼리 `limit`(기본 50, 최대 500). 4.3 과 같은 객체의 배열을 최신순으로 돌려준다.

### 4.5 `GET /v1/jobs/{id}/files/{name}` — 결과 다운로드

파일 본문을 그대로 돌려준다(`Content-Disposition: attachment`). 4.3 응답의 `urls` 를 기본 URL 뒤에 붙여 호출한다.

## 5. 모델별 `params`

| 모델 | 키 | 기본값 | 설명 |
|---|---|---|---|
| `hunyuan3d-2.1` | `texture` | `true` | `false` 면 형상(`shape.glb`)만 만들어 약 4배 빠르다 |
| | `seed` | `1234` | 같은 입력·seed 면 같은 형상 |
| | `steps` | `50` | 형상 확산 단계 수(낮추면 빠르고 거칠다) |
| | `octree` | `384` | 메시 해상도(256 / 384 / 512) |
| `triposplat` | `num_gaussians` | `262144` | Gaussian 개수(32768 ~ 262144) |
| `partllm` | `mode` | `full_shape` | `full_shape` · `text_guided` · `interactive` |
| | `prompt_set` | `general` | `full_shape` 분할 단위: `coarse` · `general` · `fine` |
| | `num_parts` | 자동 | `full_shape` 에서 부위 개수 지정 |
| | `part_names` | — | `text_guided` 에서 찾을 부위 이름 배열(영문) 예: `["seat","back","leg"]` |
| | `point` | — | `interactive` 에서 클릭한 3D 좌표 `[x, y, z]` |
| `worldmirror-2.0` | — | — | 옵션 없음 |

## 6. 오류

모든 오류는 같은 모양이다.

```json
{"error": "unknown_model", "message": "unknown model: foo (see GET /v1/models)"}
```

| HTTP | `error` | 원인 | 대응 |
|---|---|---|---|
| 400 | `invalid_request` | `urls`·`params` 가 JSON 이 아님 | 요청 형식 수정 |
| 400 | `no_input` · `too_many_inputs` | 입력 없음 / 64개 초과 | 입력 수 조정 |
| 400 | `invalid_url` · `fetch_failed` | 허용되지 않는 URL / 다운로드 실패 | 공개 URL 확인 |
| 401 | `unauthorized` | 키 없음 · 잘못됨 · 폐기됨 | 키 확인 · 재발급 요청 |
| 404 | `unknown_model` | 없는 모델 ID | `GET /v1/models` 확인 |
| 404 | `job_not_found` · `file_not_found` · `job_output_not_found` | 없는 잡/파일 또는 다른 키의 잡 | ID·파일명 확인 |
| 413 | `input_too_large` | URL 입력이 500 MB 초과 | 입력 축소 |
| 422 | — | 필수 필드 형식 오류(FastAPI 검증) | 요청 형식 수정 |
| 429 | `too_many_jobs` | 이 키의 대기+실행 잡이 한도 초과 | 기존 잡이 끝난 뒤 재시도 |
| 503 | `model_not_ready` | 모델 설치·준비 중 | 잠시 후 재시도 |
| 502 · 503(HTML) | — | 서버(pod)가 꺼져 있거나 시작 중 | 운영자에게 문의 · 지수 백오프 재시도 |

## 7. 호출 예시

### 7.1 curl — 이미지 → 텍스처 메시

```bash
API=https://<podId>-8000.proxy.runpod.net
KEY=g3d_xxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 파일 업로드로 잡 생성
curl -X POST $API/v1/jobs/hunyuan3d-2.1 -H "X-API-Key: $KEY" \
  -F files=@chair.png -F 'params={"texture":true}'
# → {"id":"ab12cd34ef56","status":"queued","position":1}

# 공개 URL 로 잡 생성
curl -X POST $API/v1/jobs/triposplat -H "X-API-Key: $KEY" \
  -F 'urls=["https://example.com/butterfly.webp"]' -F 'params={"num_gaussians":131072}'

curl $API/v1/jobs/ab12cd34ef56 -H "X-API-Key: $KEY"                        # 상태 조회
curl -OJ $API/v1/jobs/ab12cd34ef56/files/textured.glb -H "X-API-Key: $KEY"  # 결과 받기
```

### 7.2 체이닝 — 생성한 메시를 바로 부위 분할

```bash
curl -X POST $API/v1/jobs/partllm -H "X-API-Key: $KEY" \
  -F 'urls=["job://ab12cd34ef56/shape.glb"]' \
  -F 'params={"mode":"text_guided","part_names":["seat","back","leg"]}'
```

### 7.3 Python

```python
import json, time, requests

API = "https://<podId>-8000.proxy.runpod.net"
H = {"X-API-Key": "g3d_xxxxxxxx_…"}


def generate(model, path=None, urls=None, params=None, out_dir="."):
    files = [("files", open(path, "rb"))] if path else None
    data = {"urls": json.dumps(urls or []), "params": json.dumps(params or {})}
    r = requests.post(f"{API}/v1/jobs/{model}", headers=H, files=files, data=data, timeout=120)
    r.raise_for_status()
    jid = r.json()["id"]
    while True:
        j = requests.get(f"{API}/v1/jobs/{jid}", headers=H, timeout=30).json()
        if j["status"] in ("succeeded", "failed"):
            break
        time.sleep(5)
    if j["status"] == "failed":
        raise RuntimeError(j["error"])
    for name, url in zip(j["files"], j["urls"]):
        with requests.get(API + url, headers=H, stream=True, timeout=300) as f, open(f"{out_dir}/{name}", "wb") as o:
            for chunk in f.iter_content(1 << 20):
                o.write(chunk)
    return j


mesh = generate("hunyuan3d-2.1", path="chair.png", params={"texture": True})
parts = generate("partllm", urls=[f"job://{mesh['id']}/shape.glb"])
```

### 7.4 Node.js (18+)

```js
const API = "https://<podId>-8000.proxy.runpod.net";
const H = { "X-API-Key": process.env.GEN3D_API_KEY };

async function generate(model, { blob, filename, urls = [], params = {} }) {
  const form = new FormData();
  if (blob) form.append("files", blob, filename);
  form.append("urls", JSON.stringify(urls));
  form.append("params", JSON.stringify(params));
  const r = await fetch(`${API}/v1/jobs/${model}`, { method: "POST", headers: H, body: form });
  if (!r.ok) throw new Error((await r.json()).message);
  const { id } = await r.json();
  for (;;) {
    const j = await (await fetch(`${API}/v1/jobs/${id}`, { headers: H })).json();
    if (j.status === "succeeded") return j;
    if (j.status === "failed") throw new Error(j.error);
    await new Promise((s) => setTimeout(s, 5000));
  }
}

const job = await generate("triposplat", { urls: ["https://example.com/butterfly.webp"] });
const splat = await fetch(API + job.urls[0], { headers: H }); // splat.ply
```

## 8. 운영 조건

| 항목 | 값 |
|---|---|
| 처리 방식 | GPU 1장 · 잡을 순서대로 하나씩 처리(FIFO) |
| 키당 동시 잡 | 기본 10개(대기+실행), 발급 시 조정 |
| 입력 한도 | 64개 · URL 입력 1개당 500 MB |
| 결과 보관 | 서버 볼륨에 보관 — 정기 삭제 정책 확정 전까지는 받은 즉시 자체 저장소로 옮긴다 |
| 응답 시간 | 잡 생성·조회는 즉시 응답, 생성은 비동기(4.3 폴링) |
| 프록시 제한 | 한 HTTP 요청은 100초 안에 끝나야 한다 — 큰 입력은 업로드 대신 `urls` 사용 권장 |
| 가용성 | 운영자가 비용 절감을 위해 서버를 정지할 수 있다 — 502·HTML 응답이면 운영자에게 문의 |
| TLS 검사 프록시 환경 | 사내망처럼 TLS 를 중간에서 검사하는 곳에서 Python 이 `CERTIFICATE_VERIFY_FAILED` 를 내면 `pip install truststore` 후 코드 맨 앞에 `import truststore; truststore.inject_into_ssl()` — OS 신뢰 저장소로 검증한다(검증을 끄지 않는다) |

## 9. 결과 파일 보기

| 파일 | 열 수 있는 도구 |
|---|---|
| `.glb` | 브라우저 `<model-viewer>`, three.js `GLTFLoader`, Blender, Windows 3D 뷰어 |
| splat `.ply` · `.splat` | SuperSplat(supersplat.playcanvas.com), Spark(sparkjs.dev) |
| 메시·점군 `.ply` | three.js `PLYLoader`, MeshLab, Blender |

## 10. 운영자용 — 키 발급·관리

프로젝트 루트의 `run.sh` 로 한다(관리자 토큰은 운영자 PC 의 `~/.gen3d-api-token` 에만 있다).

```bash
./run.sh key create partner-studio-a 5   # 이름 · 동시 잡 한도 → API 키 원문 1회 표시
./run.sh key list                        # key_id · 활성/폐기 · 마지막 사용 시각
./run.sh key revoke 1a2b3c4d             # 즉시 401
./run.sh url                             # 호출자에게 줄 기본 URL
./run.sh pod stop | start                # 정지 중에는 GPU 과금 없음(볼륨 보관비만)
```

같은 기능의 HTTP API(관리자 토큰 필요): `POST /v1/admin/keys` `{"name": "...", "max_queued": 10}` →
`{"api_key", "key_id", ...}`, `GET /v1/admin/keys`, `DELETE /v1/admin/keys/{key_id}`.

키를 전달할 때는 API 키 · 기본 URL · 이 문서를 함께 보내고, 키는 메신저 평문 대신 비밀번호 관리자나 일회성 링크로 전달한다.

## 11. 라이선스

| 모델 | 라이선스 | 상업 이용 |
|---|---|---|
| TripoSplat | MIT | 가능 |
| PartLLM | Apache-2.0 | 가능 |
| Hunyuan3D 2.1 | Tencent Hunyuan 3D 2.1 Community License | 대한민국·EU·영국은 라이선스 적용 지역에서 제외 — 사용 전 법무 검토 필요 |
| WorldMirror 2.0 | Tencent HY-World 2.0 Community License | 대한민국 제외 — 사용 전 법무 검토 필요 |
