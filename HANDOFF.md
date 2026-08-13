# HANDOFF · 이어서 구현하기 위한 기획 문서

**대상 독자**: 다른 세션·다른 개발자가 이 저장소를 처음 열어 미구현 항목을 이어 구현할 사람.

## 0. 30초 요약

2D 스토리보드를 사람이 그리면 → 씬 JSON 으로 옮기고 → Blender 로 화이트모델 3D 블록아웃 만든 뒤 → Seedance 2.5 White-Model Control 에 넘겨 최종 사실적 영상을 얻는 파이프라인. 지금은 씬 JSON 수동 작성, 3D 조립, 프리뷰 렌더까지 동작. Seedance 전송 부분은 스켈레톤. 스토리보드 이미지 자동 추출·정밀 depth·리깅 매니큰은 미구현.

## 1. 왜 이렇게 하나 (설계 원칙)

AI 영상 모델(Seedance 등)에 이미지+텍스트만 주면 카메라 무빙·인물 위치·소품 배치를 정확히 통제할 수 없다. 3D 화이트모델 하나 만들어놓고 카메라 트랙과 인체 실루엣만 강제하면:
- 카메라 프레이밍이 결정적으로 재현
- 인물·소품 위치가 프레임 내 정확
- 표정·재질·조명은 프롬프트가 그림 (프리비즈는 구조만)

**blender-previz 스킬의 3대 원칙** 을 파이프라인에 내재화:
1. 단순 도형 카탈로그만 (`cube`, `sphere`, `cylinder`, `asymmetric_wedge`, `l_shape`, `grid_plane`)
2. 불가능 색 (프리뷰 한정. 네온 마젠타·시안·형광그린 — AI가 완성품으로 오독 안 하도록)
3. 각 오브젝트에 `final_role` 필수 (최종에 뭘로 치환되는지 서술)

## 2. 실행 환경

- Windows / macOS / Linux
- Python 3.11+ (stdlib 만 사용)
- Blender 5.2 LTS · Windows 경로: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
- ffmpeg (프리뷰 MP4 인코딩)
- (선택) `jsonschema` — 스키마 검증 강화. 없으면 경고만.

파이프라인 실행 관례:
- 파이썬 스크립트는 `uv` 로 실행 권장 (직접 `pip` / `venv` / `conda` 사용 금지 — 사용자 정책)
- Blender 헤드리스: `blender.exe --background --python <script.py> -- <args>` (`--` 다음이 스크립트 argv)

## 3. 아키텍처

```
사용자 스토리보드 이미지 · 자연어 기획서
              │
              ▼  (수동, 미래에는 VLM Pass 자동화)
    storyboard_scene_<name>.json  (Draft-07 스키마 v1.1)
              │
   ┌──────────┴──────────┐
   ▼                     ▼
[경로 A · Seedance 제출]   [경로 B · 사람 프리뷰]
blender_previz/main.py    preview_composite.py
├─ assembly.py            ├─ FBX 임포트 (proxy 매니큰 · 프리미티브 프롭)
│   screen_position →     ├─ 프리미티브 → 조합 도형 교체
│   world 역투영           │  (캡틴 체어·스티어링·대시보드·인체·나무 등)
├─ placement.py           ├─ 4방향 스틸 렌더 (left/right/front/rear)
├─ camera_builder.py      └─ shot 카메라 애니 (camera.json + JSON look_at)
│   (이징 화이트리스트)         → PNG 시퀀스 → ffmpeg → MP4
├─ proxy_library.py
└─ export_blockout.py
        │
        ▼
FBX + OBJ + camera.json
        │
        ▼
seedance_builder.py → payload.json
        │
        ▼
seedance_client.py --send (config 필요)
        │
        ▼
Seedance 2.5 R2V API → 최종 영상
```

## 4. 파일 맵

| 파일 | 역할 | 상태 |
|---|---|---|
| `storyboard_scene_schema.json` | 스키마 v1.1 (Draft-07) | 안정 |
| `storyboard_scene_example.json` | 해변 예시 | 안정 |
| `storyboard_scene_motorhome.json` | Winnebago Journey 34N 콕핏 예시 | 안정 |
| `storyboard_scene_forest.json` | 숲 속 서있는 사람 · orbit 예시 | 안정 |
| `blender_previz/main.py` | 파이프라인 엔트리 (경로 A) | 안정 |
| `blender_previz/assembly.py` | 샷 조립 · 스크린→월드 역투영 | 안정 |
| `blender_previz/placement.py` | 스크린→월드 좌표 수학 | 안정 |
| `blender_previz/camera_builder.py` | 카메라 kf + 이징 화이트리스트 | 안정 (Blender 4.4+ slot API 대응 필요할 수 있음) |
| `blender_previz/proxy_library.py` | 매니큰 append + 소품 프리미티브 | 안정 |
| `blender_previz/export_blockout.py` | FBX / OBJ / camera.json | 안정 (**주의**: FBX 카메라 rotation은 Y-up 반전됨) |
| `blender_previz/assets/proxy_library.blend` | 부트스트랩 매니큰 (l_shape 근사) | **개선 여지**: 정식 리깅 매니큰 |
| `blender_previz/assets/bootstrap_proxy_library.py` | 매니큰 blend 부트스트랩 스크립트 | 안정 |
| `blender_previz/assets/verify_proxy_library.py` | 매니큰 스펙 검증 | 안정 |
| `preview_adapter.py` | 스킬 previz.py 재사용 (네온 프리뷰) | 안정 |
| `preview_composite.py` | 사람용 조합 도형 프리뷰 | 안정 (`--scene` 인자 필수) |
| `seedance_builder.py` | payload 조립 | 안정 |
| `seedance_client.py` | provider-agnostic HTTP wrapper | 안정 |
| `seedance_config.example.json` | Seedance API config 스켈레톤 | **스텁** — 실제 API 스펙 필요 |
| `CAMERA_MOVES.md` | 카메라 무빙 카탈로그 + Q&A | 안정 |
| `README.md` | 사용법 (한글) | 안정 |
| `RETRO.md` | 2026-08-13 회고 | 참고 |

## 5. 미구현 항목 · 우선순위 · 구체 작업

### P1. 스키마 v1.2 확장 (반나절, 낮은 리스크)

**왜 우선**: 지금 v1.1은 프롭 `screen_position` 이 shot 카메라 첫 keyframe 에 종속. shot 카메라 바꾸면 프롭 world 좌표 모두 붕괴. 사용자가 반복적으로 겪음.

**작업**:
1. `storyboard_scene_schema.json` 에 다음 필드 추가:
   - `props_in_frame[].estimated_transform.pos_world`: `[x, y, z]` optional (있으면 screen_position 무시)
   - `characters_in_frame[].estimated_transform.pos_world`: 동일
   - `locations[].dimensions_m`: `{w, d, h}` optional
   - `locations[].anchors[]`: `{kind: "wall"|"door"|"window"|"floor", pos_world, size_m, yaw_deg, final_role}` optional
2. `blender_previz/assembly.py` `_resolve_world_pos_from_panel` 수정: `pos_world` 있으면 바로 반환, 없으면 기존 screen_position 경로
3. `verify` 헬퍼: 두 방식 다 있으면 pos_world 우선, 경고 로그
4. `storyboard_scene_example.json` 은 그대로 v1.1 스타일 유지, 새 예시 `storyboard_scene_room_v12.json` 로 v1.2 데모
5. README + HANDOFF 업데이트

**검증**: 기존 forest / motorhome 씬 무수정으로 여전히 통과. 새 v1.2 예시로 pos_world 직접 지정 시 shot 카메라 변경해도 프롭 이동 없음.

### P2. VLM Pass 1 스켈레톤 (1일, 중간 리스크)

**왜**: 지금 씬 JSON 완전 수동 작성. 스토리보드 한 컷 → 씬 JSON 초안 자동화 시 파이프라인 사용성 극적으로 향상.

**작업**:
1. `vlm_extract.py` 신규:
   - CLI: `--image <path> --schema storyboard_scene_schema.json --out <path>`
   - Anthropic Claude API 호출 (모델: `claude-opus-5` 또는 `claude-sonnet-5`)
   - 프롬프트: "이 스토리보드를 v1.1 스키마의 panel 하나로 변환. characters_in_frame / props_in_frame / camera_state / seedance_prompt_fragment 채워라. 결과는 JSON 객체 하나만."
   - 응답 JSON 파싱 → `jsonschema` 로 검증 → 파일 저장
2. `uv run --with anthropic --with jsonschema vlm_extract.py ...` 로 실행
3. API key: `ANTHROPIC_API_KEY` 환경변수
4. 예시 스토리보드 이미지 하나 넣어서 end-to-end 데모 (`examples/storyboard_sample.png` + 산출 JSON)

**검증**: 이미지 하나 → JSON 초안 자동 생성 → `blender_previz/main.py --dry-run` 통과.

**주의**: VLM 출력은 신뢰도 가변. 초안이지 최종본 아님. `--interactive` 플래그로 사용자 확인 루프 추가 가능.

### P3. 리깅 매니큰 교체 (반나절, 낮은 리스크)

**왜**: 지금 `proxy_library.blend` 는 세로 L-shape 봉. 최종 Seedance R2V 결과의 인체 실루엣 정확도가 이 근사에 영향받음.

**작업**:
1. 무료 리깅 매니큰 소스 선정 (라이선스 호환):
   - Mixamo (Adobe, 무료, 개인·상업 사용 OK)
   - Blender Studio 캐릭터 라이브러리
   - MakeHuman
2. FBX 다운로드 → Blender 임포트 → collection 이름 `ProxyAdultMannequin` / `ProxyChildMannequin` / `ProxyGenericSilhouette` 로 재구성
3. 신장 정규화: adult 1.75m · child 1.20m · silhouette 1.75m, origin at feet
4. `proxy_library.blend` 저장 (교체)
5. `verify_proxy_library.py` 로 검증

**검증**: 기존 씬 (motorhome / forest) 재렌더 시 인체 실루엣이 리깅된 형태로 나옴. Path A (Seedance) 결과 실루엣 정확도 향상 확인.

### P4. Seedance 2.5 API config 완성 (사용자 블록 해제 후 반나절)

**왜**: 파이프라인의 마지막 단계. 이거 안 되면 사실적 영상 생성 불가.

**블록**: Seedance 2.5 공식 API 문서 · endpoint URL · auth 스펙 · 파일 업로드 모드 (multipart / inline_base64 / presigned) · 응답 스키마. 사용자가 제공해야 함.

**작업 (문서 확보 후)**:
1. `seedance_config.json` 채우기: `endpoint` · `auth.env_var` · `field_mapping` · `upload.mode` · `polling.mode`
2. `seedance_client.py` 필요시 확장 (지금은 provider-agnostic 뼈대)
3. `SEEDANCE_API_KEY` 환경변수 세팅
4. 예시 씬 하나 (motorhome_s001) 로 실전송 테스트: `python seedance_client.py --payload out/s001_payload.json --config seedance_config.json --send`
5. 응답 JSON 저장 · 결과 영상 URL 로그

**검증**: 실제 Seedance 2.5 에서 영상 파일 획득. 예상 시간 · 비용 로그.

### P5. DA3METRIC-LARGE depth 통합 (반나절, 중간 리스크)

**왜**: 지금 `estimated_transform.depth_m` 은 수동 또는 `shot_type` 폴백. VLM Pass 완료 후 자동 depth 있으면 정확도 크게 향상.

**작업**:
1. DA3METRIC-LARGE (또는 대체: Depth Anything V2, ZoeDepth, Marigold) 스펙 확인 — GPU · VRAM · 라이선스 (memory rule)
2. `depth_extract.py` 신규: `--image <path> --out <path>` → 픽셀당 depth 맵 저장
3. `vlm_extract.py` 또는 별도 단계에서 depth 맵 참조해 각 프롭의 `screen_position` → `depth_m` 산출
4. 스키마에 `estimated_transform.depth_confidence` 추가 (VLM > depth model > shot_type 폴백 우선순위)

**검증**: VLM 만으로 만든 JSON vs VLM+depth 로 만든 JSON 비교. 프리뷰 렌더 상 공간감 개선 확인.

## 6. 알려진 GOTCHA · 함정

### FBX 카메라 rotation Y-up 반전
- **증상**: FBX 재임포트한 카메라를 `scene.camera` 로 지정해 렌더하면 위쪽 하늘만 나옴.
- **원인**: FBX 익스포트 시 Blender Z-up → FBX Y-up 변환. 회전 반전.
- **회피**: FBX 카메라 회전 신뢰하지 말고 `camera.json` 위치 + 씬 JSON `look_at_world` 를 `to_track_quat('-Z', 'Y')` 로 재계산. (`preview_composite.py` 참조)

### shot 카메라 변경 시 프롭 world 좌표 붕괴
- **증상**: shot 카메라 keyframe 바꿨더니 캐릭터 위치가 어긋남.
- **원인**: `_resolve_world_pos_from_panel` 이 shot 카메라 첫 keyframe 기준으로 `screen_position` 역투영.
- **회피**: 새 shot 카메라 기준으로 모든 프롭 `screen_position` · `depth_m` 재계산. 근본 해결은 P1 (스키마 v1.2 `pos_world`).

### 이징 화이트리스트
- 허용: `LINEAR` · `EASE_IN` · `EASE_OUT` · `EASE_IN_OUT` + `SINE`/`CUBIC`/`BEZIER` 커브
- 금지: `BACK` · `BOUNCE` · `ELASTIC` (오버슛/진동 → AI R2V 부적합)
- `camera_builder.py` 가 강제. 위반 시 abort.

### min_distance
- 카메라-피사체 0.4m 이하 시 스킬 V1 검증 실패.
- 근접 샷은 (a) 프롭 스케일 다운 (b) 광각 렌즈 (c) `scene_meta.min_distance_m` 낮춤 순으로 검토.

### 매니큰 origin은 발
- `proxy_library.blend` 매니큰은 origin (0,0,0) = 발밑. 세운 배치 시 world Z=0 지정.
- 지난 세션에서 이거 몰라서 캐릭터가 부양했던 사례 여러 번.

### Blender 4.4+ Action slot API
- `action.fcurves` 대신 `action.layers[].strips[].channelbags[].fcurves` 로 이동.
- `camera_builder.py` 에 폴백 로직 있음. Blender 5.2 LTS 는 문제없음. 다른 버전 사용 시 확인 필요.

### 조합 도형 프리뷰는 시각화 전용
- `preview_composite.py` 는 사람이 공간 알아보기 위한 것. 최종 Seedance R2V 에 넘기는 FBX/OBJ/payload 는 여전히 스킬 3대 원칙 준수 (원시 도형만).
- 절대 이 조합 도형을 Seedance 에 넘기지 말 것.

## 7. 개발 리듬 · 검증

각 미구현 항목 완료 기준:
1. 스키마 · 코드 변경
2. 기존 예시 씬 (`example` · `motorhome` · `forest`) 셋 다 `--dry-run` 통과
3. 새 예시 씬 하나 만들어 파이프라인 전체 (FBX 빌드 + payload + 프리뷰) 동작 검증
4. README 또는 관련 문서 업데이트

## 8. 참고

- [blender-previz 스킬 문서](.claude/skills/blender-previz/SKILL.md) (사용자 로컬)
- [CAMERA_MOVES.md](./CAMERA_MOVES.md) — 카메라 무빙 카탈로그
- [RETRO.md](./RETRO.md) — 최근 세션 회고
- Seedance 2.5 릴리스: ByteDance 2026-07-31 (공식 문서 별도 확인)
- 저장소: https://github.com/yj78615-blip/storyboard-previz
