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

---

# 회고 · 2026-09-01 세션

## 시작 상태

- 파이프라인 1단계 ("스토리보드 촬영/스캔 → 각 컷을 하나의 파일에 정리") 가 완전 수동
- VLM Pass 1/2/3 미구현 상태 그대로 → 스토리보드 이미지를 컷 단위로 준비하는 것 자체가 병목
- 사용자에게 실사용 PDF 있음 (`얼쑤(심청전)_스토리보드_파일럿`, 5 페이지, CUT/PICTURE/MEMO 양식)

## 이번 세션이 실제로 만든 것

### `tools/pdf_panel_export/` (신규 · 경로 0)

PDF 스토리보드에서 컷 영역만 잘라 `1920x1080` PNG로 뽑는 PySide6 데스크톱 도구. Python 3.11+ / PySide6 · PyMuPDF · Pillow.

- **영역 지정** — 왼쪽 드래그로 16:9 고정 선택, 사각형 안쪽을 잡고 끌어 이동, 방향키 1px · Shift+방향키 10px 미세 조정, 좌표 직접 입력
- **크기 프리셋** — 오른쪽 드래그로 저장, 목록에서 적용 · 드래그 재정렬 · 삭제. `~/.pdf_crop_exporter/presets.json`
- **다중 영역** — 한 페이지의 여러 컷을 목록에 쌓아 일괄 추출. 목록 순서 = 컷 순서 (드래그로 변경)
- **영역 세트** — 영역 조합을 pt 단위로 저장/불러오기. 같은 양식의 다른 PDF에 재사용, 페이지 크기가 달라도 안쪽으로 클램핑. `~/.pdf_crop_exporter/region_sets.json`
- **연속 번호 출력** — 1페이지 영역1 → 1페이지 영역2 → 2페이지 영역1 … 순서로 `{PDF이름}_001.png` 부터. 파일명 번호가 곧 컷 번호라 `shots[]` 의 `s001`, `s002` 와 그대로 대응
- 단일 exe 패키징 (PyInstaller onefile · windowed) + 바탕화면 바로가기

## 발견한 버그와 근본 원인

### 1. 두 번째 내보내기가 첫 결과를 조용히 덮어씀

- **증상**: 영역을 바꿔 여러 번 뽑았는데 결과 폴더에 마지막 5장만 남음. 이전 산출물 손실.
- **원인**: 출력 폴더와 파일명이 매 실행 동일 (`{PDF이름}_page_001.png`). "같은 PDF에서 영역을 바꿔 여러 번 실행한다"는 사용 패턴을 PRD 단계에서 상정하지 않음.
- **해결**: 1차로 영역별 하위 폴더 (태그) 도입 → 최종적으로 다중 영역 목록 + 연속 번호 구조로 교체하고 덮어쓰기 확인 다이얼로그 추가.
- **교훈**: 파일을 쓰는 도구는 "두 번 실행하면 어떻게 되나" 를 설계 단계에서 반드시 물을 것.

### 2. 산출물을 못 찾음 (Windows 경로)

- **증상**: 내보내기 완료 메시지는 떴는데 바탕화면에서 파일이 안 보임.
- **원인**: 바탕화면이 OneDrive 로 리디렉션 + 폴더명이 러시아어 (`C:\Users\Pc\OneDrive\Рабочий стол`). 탐색기의 "바탕화면" 과 실제 저장 경로가 다름.
- **해결**: `[Environment]::GetFolderPath('Desktop')` 로 실제 경로 확인 후 안내.
- **교훈**: Windows 경로 추측 금지. 부수적으로, Git Bash 에서 이 경로의 비ASCII 문자가 깨져 `pymupdf` 가 파일을 못 여는 문제가 있어 PowerShell 로 우회함.

### 3. 좌클릭 드래그 회귀로 오인

- **증상**: 우클릭 프리셋 기능 추가 후 좌클릭 드래그가 동작하지 않는 것으로 보임.
- **원인**: 앱이 아니라 **검증 스크립트 쪽 버그** (창 크기 미설정으로 뷰포트 좌표가 영역 밖). 동일 조건으로 다시 짜니 581.8x327.3px, 16:9 정상.
- **교훈**: 헤드리스 테스트가 실패하면 앱보다 테스트 하네스를 먼저 의심할 것.

### 4. `.omc/` 운영 아티팩트가 커밋에 포함될 뻔

- **원인**: `git add <디렉터리>` 가 세션 상태 파일 (`.omc/state/**`) 까지 스테이징.
- **해결**: 언스테이징 후 `.gitignore` 에 `.omc/` 추가. 커밋 전 `git diff --cached --name-status` 로 실제 목록 확인하는 절차 적용.

## 알려진 한계

- **페이지마다 컷 개수가 다르면 빈 이미지가 생김**. 모든 페이지에 동일한 영역 세트를 적용하는 구조라, 마지막 페이지에 컷이 1개뿐이면 흰 PNG 가 여분으로 생성됨.
- 시작 번호 지정 (001 대신 007 부터), 영역별 컷 번호 직접 입력 미구현.
- 페이지 크기가 다른 PDF 는 첫 페이지 기준 절대 좌표를 그대로 적용 (세트 불러오기 시 클램핑만 수행).
- **사본이 두 벌**: 작업본 `pdf-crop-exporter/` 와 저장소 `tools/pdf_panel_export/` 를 수동 동기화. 코드 수정 후 exe 재빌드하지 않으면 바탕화면 아이콘에는 반영되지 않음.

## 미구현 · 다음 세션으로 넘길 것

### VLM Pass 1 연결 (진입 장벽 낮아짐)

- `pdf_panel_export` 산출 PNG 를 그대로 입력으로 받아 `panels[]` 초안 자동 생성.
- 이전 세션 회고에서 "완전 수동" 이라 적힌 부분 중 **이미지 준비 단계는 이번에 자동화됨**. 남은 것은 이미지 → JSON 추출.

### 컷 번호 ↔ `shots[]` 매핑 자동화

- `_001.png` → `s001` 대응이 이미 성립하므로, PNG 목록에서 `shots[]` 스켈레톤을 생성하는 스크립트는 소규모 (2-3시간).

## 프로세스 리뷰

### 잘 된 것

- GUI 를 눈으로 볼 수 없는 환경에서 `QT_QPA_PLATFORM=offscreen` 으로 마우스·키보드 이벤트를 시뮬레이션해 기능마다 검증.
- 연속 번호는 파일 **개수만 세지 않고**, `crop_page_region()` 결과와 실제 출력 PNG 를 픽셀 단위로 대조해 "001 이 정말 1페이지 첫 영역인가" 를 확인. 목록 재정렬 후에도 재검증.
- 커밋 시 사용자가 작업 중이던 다른 파일 (`preview_render.py` 등) 을 건드리지 않고 분리.

### 아쉬웠던 것

- 실행 안내를 상대경로 (`cd pdf-crop-exporter`) 로 제시해 "경로 없음" 오류를 유발.
- PRD 단계에서 질문을 4개 던졌으면서 정작 "반복 실행 시 덮어쓰기" 를 묻지 않아 사용자 산출물 손실로 이어짐.
- 기능이 붙을수록 우측 패널이 계속 길어짐 (좌표 · 프리셋 · 영역 목록 · 세트 · 출력). UI 정리 부채.

### 다음 세션 진입점

1. VLM Pass 1 스켈레톤 — 입력 이미지 확보가 자동화됐으므로 지금이 적기.
2. 또는 스키마 v1.2 확장 (이전 세션에서 이월).
3. 또는 `pdf_panel_export` 한계 해소 — 페이지별 컷 개수 가변 지원.
