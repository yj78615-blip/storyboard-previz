# 회고 · 2026-08-13 세션

## 시작 상태

- 저장소 초기 push 완료 (README, LICENSE, blender_previz/ 스킬 파이프라인, seedance_builder/client 뼈대, 해변 예시 씬)
- Windows Journey 34N 도면 사용자로부터 받음 (Class A 디젤 푸셔)

## 이번 세션이 실제로 만든 것

### 씬 두 개
- **`storyboard_scene_motorhome.json`** — Winnebago Journey 34N 콕핏, 실측 반영 (전장 10.82m · 폭 2.58m · 실내고 2.13m), Freightliner XCM · 커브드 파노라마 앞유리 · DriveTech 대시보드 · 6-way 캡틴 시트 · TRW 스티어링
- **`storyboard_scene_forest.json`** — 숲 속 서있는 사람 (성인 175cm · 활엽수 6그루 · orbit_ccw 90°)

### 사람용 프리뷰 렌더
- **`preview_composite.py`** — FBX 임포트 → 프리미티브를 인식 가능한 조합 도형으로 교체 → 워크벤치 엔진 오브젝트별 고정 팔레트 → 4방향 스틸 + shot 애니 (144 프레임) 렌더
- 지원 조합: 캡틴 체어 5조각 · 스티어링 링+허브+스포크 · 대시보드+LCD+계기판 · 앉은 인체 10조각 · 서있는 인체 10조각 · 나무 (트렁크+캐노피)
- CLI: `--fbx --out --shot-id --frames --scene`

### 카메라 무빙 카탈로그
- **`CAMERA_MOVES.md`** — 9종 (static · dolly · truck · pan · tilt · orbit · crane · dutch) + 조합 규칙 + 6단계 Q&A + 예시 3개
- 다음 세션부터 사용자가 "카메라 무빙 만들어줘" 하면 이 문서 따라 진행

## 발견한 버그와 근본 원인

### 1. FBX 카메라 Y-up 회전 부호 반전
- **증상**: 프리뷰 애니 MP4 프레임 전부 텅 빈 회색. motorhome 이전 렌더에서도 같은 문제 있었지만 못 알아챔.
- **원인**: FBX 익스포트 시 Y-up 컨벤션 변환. Blender native (Z-up) `rotation_euler` 이 FBX 왕복 후 뒤바뀜. 결과: 위쪽 하늘 응시.
- **해결**: `preview_composite.py` 가 FBX 카메라 회전 무시하고 `camera.json` 위치 + 씬 JSON `look_at_world` 를 `mathutils.Vector.to_track_quat` 로 조합해 프레임별 계산.
- **교훈**: FBX 임포트 카메라 회전 신뢰하지 말 것. 방향 정보는 씬 JSON 원본에서.

### 2. shot 카메라 변경 시 프롭 world 좌표 붕괴
- **증상**: forest 씬에 orbit_ccw 넣으니 캐릭터가 공간에서 사라짐.
- **원인**: `_resolve_world_pos_from_panel` 이 shot 카메라 첫 keyframe 기준으로 `screen_position`을 월드로 역투영. shot 카메라를 바꾸면 같은 `screen_position` 이 다른 월드 좌표로 매핑됨.
- **해결**: 새 shot 시작 카메라 기준으로 모든 프롭 `screen_position` · `depth_m` 재계산.
- **교훈 · 스키마 v1.2 제안**: 프롭에 `pos_world` 직접 지정 필드 추가하면 shot 카메라 독립성 확보. 지금은 v1.1로 재계산 워크플로 유지.

### 3. l_shape 매니큰 발이 공중에 뜸
- **증상**: 캐릭터가 바닥에서 0.55m 위로 부양.
- **원인**: 씬 JSON의 캐릭터 target Z를 "중앙" 으로 잡음 (0.875). 매니큰 origin은 발이므로 발이 그 값으로 배치.
- **해결**: target Z = 0 (발이 바닥).

### 4. Class A 캠핑카 외관 추측
- **증상**: 모델 확신 없이 "파노라마 앞유리" 로 렌더.
- **원인**: 도면(평면도)에는 외관 정보 없음. 임의 가정.
- **해결**: 사용자가 "Winnebago Journey" 알려주자 웹 서치로 실측·외관 특성 확인 후 반영.
- **교훈**: 확신 없으면 즉시 "모른다" 응답 (memory rule 재확인).

## 미구현 · 다음 세션으로 넘길 것

### VLM Pass 1/2/3 (스토리보드 이미지 → 씬 JSON 자동 추출)
- 현재: 완전 수동 (내가 이미지 보고 직접 JSON 작성).
- 필요: Claude API 호출 스크립트, 3단계 프롬프트 (locations/characters/panels), JSON 검증 루프.
- 예상 규모: 1일 (스켈레톤), 다수 반복 필요.
- 진입 파일 제안: `vlm_extract.py` (uv env, anthropic SDK, 스키마 검증 with jsonschema).

### DA3METRIC-LARGE depth 정밀화
- 현재: `estimated_transform.depth_m` 은 수동 값 또는 `shot_type` 폴백.
- 필요: DA3METRIC-LARGE (또는 대체) 모델로 스토리보드 이미지 depth 추정.
- 규모: 반나절 (모델 다운로드 · 추론 · 스키마 필드 매핑).
- 스펙 확인 먼저: GPU · VRAM · 라이선스 (memory rule).

### Seedance 2.5 API config 완성
- 현재: `seedance_config.example.json` 뼈대만.
- 필요: 실제 Seedance 공식 endpoint · auth 스펙 · field_mapping · upload_mode.
- 블록: 사용자가 Seedance API key + 공식 문서 제공해야 진행 가능.
- 이후: `seedance_client.py --send` 로 실전송 검증.

### 리깅 매니큰 교체
- 현재: `proxy_library.blend` 는 l_shape 근사 (성인 1.75m · 아동 1.20m · 실루엣 1.75m 세로 봉).
- 필요: 정식 리깅된 인체 매니큰. 무료 라이선스 소스 (Mixamo, Adobe Substance Character 등).
- 규모: 반나절 (자산 다운로드 · Blender 임포트 · proxy_library.blend 재구성 · `verify_proxy_library.py` 통과).
- Path A 결과 실루엣 정확도 크게 향상.

### 스키마 v1.2 확장 (권장)
- `props_in_frame[].estimated_transform.pos_world` 추가 → shot 카메라 독립적 배치.
- `locations[].dimensions_m` · `anchors[]` (벽·문·창) → 사용자 요청 있던 도면 실측 반영 정식화.
- 규모: 2-3시간 (스키마 파일 수정 · placement.py 옵션 추가 · 예시 씬 업데이트).

## 프로세스 리뷰

### 잘 된 것
- 사용자가 "눈으로 분간이 안 돼" 라고 하자 즉시 조합 도형으로 방향 전환. 결과 완전 다름.
- FBX 카메라 회전 버그 발견 후 근본 원인 (Y-up 변환) 까지 파고들어 해결. 이전 motorhome MP4도 같은 문제였음을 인정.
- CAMERA_MOVES.md 를 스킬/문서로 만드는 결정 (사용자 확인 후). 다음 세션의 자기·타 사용자에게 유용.

### 아쉬웠던 것
- Class A 캠핑카 외관 처음에 추측함. Memory rule 있었는데 즉시 따르지 못함. 사용자가 "너는 공간이 이해가가?" 라고 물어서야 인정.
- 세션 비용이 $460 넘음 (32 파일 수정). 스코프 경고 반복. 씬 iteration 하는 동안 재렌더 여러 번.

### 다음 세션 진입점
1. VLM Pass 1 스켈레톤 → 스토리보드 이미지 한 장으로 파이프라인 자동화 데모.
2. 또는 스키마 v1.2 확장 → 지금 반복적으로 발생하는 shot 카메라 의존성 해소.
3. 또는 리깅 매니큰 도입 → Path A 최종 결과 품질 크게 향상.

우선순위는 사용자가 다음 세션 진입점에서 결정.

## 저장소 URL

https://github.com/yj78615-blip/storyboard-previz
