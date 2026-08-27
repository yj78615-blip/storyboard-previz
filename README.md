# storyboard-previz

**2D 스토리보드 → 3D 프리비즈 (Blender) → Seedance 2.5 White-Model Control 파이프라인.**

손으로 그린 스토리보드를 화이트 모델 FBX + 카메라 트랙 + 텍스트 프롬프트로 변환해 AI 영상 모델(Seedance 2.5) 에 넘길 수 있는 형태로 만든다. 카메라 확인용 네온 프리뷰 MP4 도 함께 뽑을 수 있다.

## 왜 이렇게 하나

AI 영상 모델은 이미지·프롬프트만으로는 카메라 무빙·인물 위치·소품 배치를 예측 가능하게 통제하기 어렵다. 3D 블록아웃 하나를 미리 만들어놓고 카메라 트랙을 강제하면:

- 카메라 프레이밍이 결정적으로 재현된다
- 인물·소품이 프레임 안에서 원하는 위치에 있다
- 표정·재질·조명은 프롬프트가 그린다 (프리비즈는 위치만)

blender-previz 스킬의 **3대 원칙** 을 파이프라인 코드에 내재화했다:

1. **단순 도형 카탈로그만** (`cube`, `sphere`, `cylinder`, `asymmetric_wedge`, `l_shape`, `grid_plane`)
2. **불가능 색** (프리뷰 렌더 한정. 네온 마젠타·시안·형광그린 등)
3. **`final_role` 필수** — 스키마 v1.1이 강제. 화이트모델의 각 오브젝트가 최종에 뭘로 치환될지 서술.

## 요구사항

- **Windows / macOS / Linux**
- **Python 3.11+** (stdlib 만 사용, 외부 의존성 없음)
- **Blender 5.2 LTS** — [blender.org/download](https://www.blender.org/download/)
- **ffmpeg** — 프리뷰 MP4 인코딩용 (스킬 previz.py 재사용 시)
- (선택) `jsonschema` — 스키마 검증 강화. 없어도 파이프라인 동작.

## 폴더 구조

```
storyboard_previz/
├── storyboard_scene_schema.json     ← 씬 JSON 스키마 (Draft-07, v1.1)
├── storyboard_scene_example.json    ← 검증된 예시 씬 (해변, 8초, 2 패널)
├── tools/pdf_panel_export/          ← 경로 0: PDF 스토리보드 → 컷별 PNG 패널 추출 (Windows GUI)
├── blender_previz/                  ← 경로 A: Seedance 제출용 FBX 파이프라인
│   ├── main.py                          CLI 엔트리포인트
│   ├── assembly.py                      샷 조립 (캐릭터 · 소품 · 카메라)
│   ├── camera_builder.py                카메라 kf + 이징 화이트리스트
│   ├── placement.py                     스크린좌표 → 월드좌표
│   ├── proxy_library.py                 매니큰 append + 소품 프리미티브
│   ├── export_blockout.py               FBX / OBJ / camera.json 익스포트
│   └── assets/
│       ├── bootstrap_proxy_library.py       임시 매니큰 부트스트랩 스크립트
│       └── verify_proxy_library.py          proxy_library.blend 스펙 검증
├── preview_adapter.py               ← 경로 B: 스킬 previz.py 로 네온 프리뷰
├── seedance_builder.py              ← 프롬프트 + payload.json 조립
├── seedance_client.py               ← Seedance HTTP wrapper (provider-agnostic)
└── seedance_config.example.json     ← API 설정 스켈레톤 (endpoint/필드/auth)
```

## 첫 실행 (5분)

### 1. 저장소 클론

```bash
git clone <repo-url>
cd storyboard_previz
```

### 2. 매니큰 애셋 부트스트랩

정식 리깅 매니큰이 없어서 임시로 `l_shape` 프록시 3종 (성인/아동/실루엣) 을 생성:

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" \
    --background --python blender_previz/assets/bootstrap_proxy_library.py -- \
    --out blender_previz/assets/proxy_library.blend
```

검증:

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" \
    --background --python blender_previz/assets/verify_proxy_library.py -- \
    --blend blender_previz/assets/proxy_library.blend
```

3종 모두 통과 (`[pass] proxy_library.blend 스펙 준수`) 확인.

### 3. 예시 씬으로 전체 파이프라인 검증

**경로 A** (Seedance 제출용 FBX + payload):

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" \
    --background --python blender_previz/main.py -- \
    --scene storyboard_scene_example.json --shot s001 \
    --blend blender_previz/assets/proxy_library.blend \
    --out out
```

산출: `out/s001.fbx`, `out/s001.obj`, `out/s001_camera.json`

```bash
python seedance_builder.py --scene storyboard_scene_example.json --shot s001 \
    --blockout-dir out --out out/s001_payload.json
```

산출: `out/s001_payload.json` (prompt + Seedance API 페이로드)

**경로 B** (카메라 확인용 네온 프리뷰 MP4):

```bash
python preview_adapter.py --scene storyboard_scene_example.json --shot s001 \
    --out-spec out/s001_preview_spec.json --render out/s001_preview.mp4
```

산출: `out/s001_preview.mp4` (~192 프레임, EEVEE Next, 네온 색상)

## 자기 스토리보드로 씬 만들기

### 1. 스토리보드 촬영/스캔 → 각 컷을 하나의 파일에 정리

CUT/PICTURE/MEMO 형식의 스토리보드 PDF가 있다면, [`tools/pdf_panel_export`](./tools/pdf_panel_export/README.md)로 컷마다 PICTURE 영역만 `1920x1080` PNG로 잘라 정리할 수 있다. 이렇게 뽑은 이미지를 아래 `panels[]` 작성 시 참고 이미지로 쓴다.

### 2. `storyboard_scene_example.json` 을 복사해서 편집

주요 편집 필드:

- `story_meta.aspect_ratio` — `"16:9" / "9:16" / "1:1" / "4:3" / "2.39:1"`
- `characters[]` — 각 캐릭터의 `character_id`, `kind` (`adult` / `child` / `silhouette`), `reference_description`
- `locations[]` — 각 로케이션 서술
- `panels[]` — 스토리보드 컷 한 장당 한 패널:
  - `camera_state.shot_type` — `wide / medium_wide / medium / medium_close / close / extreme_close / extreme_wide`
  - `characters_in_frame[].screen_position` — `{x: 0..1, y: 0..1}`, 원점 좌상단
  - `characters_in_frame[].final_role` — Seedance R2V가 그릴 외모 서술 (**필수**)
  - `props_in_frame[].shape` — 6종 카탈로그 중 하나 (**필수**)
  - `seedance_prompt_fragment` — 이 컷의 프롬프트 조각
- `shots[]` — 스토리보드 관례상 **컷 하나 = shot 하나** (컨티뉴어스 테이크 아니면):
  - `panel_ids: ["pXXX"]` — 이 shot에 속한 패널
  - `duration_sec`
  - `camera_keyframes[]` — kf 2개 (시작 hold=false, 끝 hold=true) 가 카메라 정지의 최소 스펙
  - `shot_level_seedance_prompt` — null 이면 seedance_builder가 timeline 형식으로 자동 조립. 문자열 넣으면 그걸 그대로 사용.

### 3. dry-run 으로 스키마 검증

```bash
python blender_previz/main.py --scene my_scene.json --shot s001 \
    --blend blender_previz/assets/proxy_library.blend --out out --dry-run
```

### 4. 실제 빌드 → payload → (선택) 프리뷰

위 "첫 실행 3단계" 와 동일. `--scene` 인자만 자기 파일로 교체.

## Seedance API 전송

`seedance_client.py` 는 provider-agnostic HTTP wrapper 다. Seedance 2.5 공식 문서 확인 후:

### 1. `seedance_config.example.json` → `seedance_config.json` 복사

편집 필드:

- `endpoint` — 실제 API URL
- `auth.env_var` — API key 담을 환경변수 이름 (기본 `SEEDANCE_API_KEY`)
- `field_mapping` — 우리 payload 필드 → API 필드 이름 매핑
- `upload.mode` — `multipart` / `inline_base64` / `presigned`
- `polling.mode` — `sync` (즉시 응답) 또는 `poll` (job id → 상태 폴링)

### 2. API key 세팅

```bash
# Windows PowerShell
$env:SEEDANCE_API_KEY = "your-key"

# bash
export SEEDANCE_API_KEY="your-key"
```

### 3. dry-run으로 조립 확인

```bash
python seedance_client.py --payload out/s001_payload.json --config seedance_config.json
```

`--send` 없이 실행하면 request 조립까지만 하고 실제 전송 없이 출력.

### 4. 실전송

```bash
python seedance_client.py --payload out/s001_payload.json --config seedance_config.json --send
```

응답: `out/s001_payload_response.json`.

## 스토리보드 관례 · 카메라 무빙

- **스토리보드에서 프레이밍이 다른 그림 여러 장 = 개별 shot (컷 편집)**. 카메라 무빙이 아니다.
- 카메라 무빙을 원할 때는 **한 shot 안에 kf 여러 개** (`t_sec` 다르게). 스토리보드에 궤적 화살표/문자 지시가 있을 때만.
- 각 shot 은 카메라 정지가 기본:
  ```json
  "camera_keyframes": [
    {"t_sec": 0.0, "pos_world": [0,-3,1.5], "look_at_world": [0,0,1.5], "easing": "LINEAR", "hold": false, ...},
    {"t_sec": 3.0, "pos_world": [0,-3,1.5], "look_at_world": [0,0,1.5], "easing": "LINEAR", "hold": true,  ...}
  ]
  ```

## 이징 화이트리스트

`camera_builder.py` 가 강제 (스킬 references/research.md 근거):

| easing | 허용 |
|---|---|
| `LINEAR` `EASE_IN` `EASE_OUT` `EASE_IN_OUT` | ✅ |
| `BACK` `BOUNCE` `ELASTIC` | ❌ abort (오버슛/진동은 AI 영상에 부적합) |

`easing_curve`: `SINE` / `CUBIC` / `BEZIER` (선택).

## 자체 검증

각 모듈은 bpy 없이 실행 가능한 `_demo()` / `--demo` 를 가진다:

```bash
python blender_previz/placement.py     # 스크린→월드 좌표 계산
python blender_previz/camera_builder.py # 이징 화이트리스트, focal 우선순위
python blender_previz/assembly.py      # 인덱싱 · 마지막 등장 패널
python preview_adapter.py --demo       # 스킬 스펙 변환 · 팔레트 순환
python seedance_client.py --demo       # 필드 매핑 · multipart 조립 · config validation
```

## 알려진 한계 (MVP)

- **한 shot 안 캐릭터 이동 미지원**. 각 캐릭터는 "마지막 등장 패널" 의 트랜스폼에 정지. 여러 shot 으로 나누는 게 관례상 자연스러움.
- **proxy_library.blend 는 부트스트랩 상태** — `l_shape` 세로 형태. 정식은 리깅된 매니큰으로 교체 예정.
- **DA3METRIC-LARGE depth 통합은 스텁**. `estimated_transform.depth_m` 은 수동 입력 or `shot_type` 폴백.
- **VLM Pass 1/2/3 자동 추출 미구현**. 스토리보드 이미지 → 씬 JSON 은 수동 작성.
- **Seedance HTTP wrapper 는 config 완성 후 사용 가능**. presigned URL 모드는 provider별 커스텀 구현 필요 (스텁만 존재).

## 참고 · 감사

- [blender-previz 스킬](https://www.anthropic.com/claude-code) — 3대 원칙 (단순 도형 / 불가능 색 / 역할 분리) 근거
- Seedance 2.5 White-Model Control API — ByteDance 2026-07-31 릴리스

## 라이선스

MIT. [LICENSE](./LICENSE) 참조.
