# gen3d-api — 이미지·영상 → 3D 생성 API

GPU pod 한 대(H100/A100 80GB)에서 4개 모델을 하나의 HTTP API로 외부에 노출한다.
모델마다 torch 버전이 달라 venv 를 분리하고, 게이트웨이가 GPU 큐 하나로 순서대로 돌린다.

## 모델 구성 (2026-10-27 기준)

| API 이름 | 입력 → 출력 | 라이선스 | VRAM |
|---|---|---|---|
| `hunyuan3d-2.1` | 이미지 → PBR 텍스처 메시 `.glb` | Tencent Community (한국·EU·UK 제외) | 형상 10GB · 텍스처 21GB |
| `triposplat` | 이미지 → 3D Gaussian `.ply`/`.splat` | MIT | 16GB 미만(추정) |
| `worldmirror-2.0` | 다시점 사진/영상 → 포인트클라우드·3DGS·깊이·카메라 | Tencent HY-World 2.0 Community (한국 제외) | 단일 GPU |
| `partllm` | 메시 → 파트 분할(색칠 메시 + 파트별 ply) | Apache-2.0 | 20–30GB(추정) |

**Hunyuan 최신 현황**: 공개 가중치 중 이미지→텍스처 메시 최고 모델은 여전히 **Hunyuan3D-2.1**.
2.5·3.0·3.1 은 Studio/API 전용(가중치 미공개). Omni(제어형 형상)·Part(분할)는 2.1 파생이며 품질 상향판이 아니다.

**HY-World 2.0 범위**: 단일 GPU 로 가능한 WorldMirror 2.0(복원)만 포함. 텍스트/이미지 → 월드 생성은
HY-Pano-2(약 80B) + WorldStereo-2 + 3DGS 학습으로 GPU 4장 이상이 필요해 제외.

**라이선스 주의**: Tencent 두 모델은 라이선스 적용 지역에서 대한민국이 빠져 있다. 사내 서비스에 쓰기 전 법무 검토가 필요하다.
TripoSplat(MIT)·PartLLM(Apache-2.0)은 제약이 없다.

## 배포

```bash
python3 deploy.py create   # pod 생성 — 부팅하면 코드를 풀고 게이트웨이를 띄운 뒤 모델을 설치
python3 deploy.py status   # 설치 진행(ready 목록 · GPU · 로그 꼬리)
python3 deploy.py push     # 코드만 갱신 + 게이트웨이 재시작
python3 deploy.py sh "nvidia-smi"
```

- 토큰은 `~/.gen3d-api-token`, pod ID 는 `~/.gen3d-api-pod` 에 저장된다(저장소 밖)
- 설치 순서: TripoSplat(수 분) → Hunyuan3D·WorldMirror·PartLLM 병렬(PartLLM 은 flash-attn 컴파일로 가장 오래 걸림)
- `/workspace` 는 250GB 볼륨이라 pod 를 재시작해도 설치본이 남고, 이미 설치된 모델은 건너뛴다
- 사내망(판교)에서는 외부 업로드 차단 정책에 걸려 `create`/`push` 가 막힌다 → 업로드가 허용되는 망에서 실행

## API

기본 주소 `https://<podId>-8000.proxy.runpod.net`, 헤더 `Authorization: Bearer <token>`.
RunPod 프록시는 100초 제한이 있어 모든 생성은 **비동기 잡**이다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 인증 없음 · 큐 길이 |
| GET | `/v1/models` | 모델별 설치 완료(`ready`) · 메모리 상주(`loaded`) |
| POST | `/v1/jobs/{model}` | multipart `files`(여러 개 가능) 또는 `urls`(JSON 배열) + `params`(JSON) |
| GET | `/v1/jobs/{id}` | `queued`/`running`/`succeeded`/`failed`, 결과 `urls` |
| GET | `/v1/jobs/{id}/files/{name}` | 결과 파일 다운로드 |

### params

- `hunyuan3d-2.1`: `texture`(기본 true) · `seed`(1234) · `steps`(50) · `octree`(384). 알파가 없으면 배경을 자동 제거
- `triposplat`: `num_gaussians`(기본 262144)
- `worldmirror-2.0`: 없음. 이미지 여러 장 또는 영상 한 개
- `partllm`: `mode` = `full_shape`(기본; `prompt_set`, `num_parts`) | `text_guided`(`part_names` 배열) | `interactive`(`point` [x,y,z])

### 예시

```bash
API=https://<podId>-8000.proxy.runpod.net; H="Authorization: Bearer $(cat ~/.gen3d-api-token)"
curl -X POST $API/v1/jobs/hunyuan3d-2.1 -H "$H" -F files=@chair.png -F 'params={"texture":true}'
# → {"id":"ab12…","status":"queued"}
curl $API/v1/jobs/ab12… -H "$H"          # succeeded 가 될 때까지 폴링
curl -O $API/v1/jobs/ab12…/files/textured.glb -H "$H"

# 파트 분할 체인: Hunyuan 결과 메시를 URL 로 PartLLM 에 넘긴다
curl -X POST $API/v1/jobs/partllm -H "$H" -F 'urls=["https://…/shape.glb"]' -F 'params={"mode":"text_guided","part_names":["seat","back","leg"]}'
```

## 구조

- 게이트웨이(`gateway.py`): 인증, 잡 저장(`/workspace/jobs/<id>`), GPU 큐 1개
- 러너(`runners/*.py`): 모델을 한 번 로드한 뒤 stdin 으로 잡 JSON 을 한 줄씩 받아 처리하는 상주 프로세스
- 모델이 바뀌면 이전 러너를 내려 VRAM 에 한 모델만 올린다
- 처음 받는 잡은 모델 로딩 시간이 더해진다

## 검증 현황

- 게이트웨이 로컬 스모크 테스트(`tests/smoke-local.sh`, GPU 불필요) 통과: 인증 401 · 설치 중 503 · 큐 · 워커 프로토콜 · 파일 다운로드
- 실제 GPU 추론 4종은 pod 생성 후 `deploy.py status` 에서 ready 를 확인하고 모델별로 한 번씩 돌려 검증해야 한다
