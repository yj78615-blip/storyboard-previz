# CAMERA_MOVES — 카메라 무빙 카탈로그 · Q&A 스킬

Claude가 사용자와 짧은 Q&A 후 씬 JSON `shots[].camera_keyframes[]` 를 채우는 참조 문서. 사용자가 "카메라 무빙 만들어줘", "이 샷에 이런 무빙 넣어줘", "무빙 뽑아줘" 라고 말하면 이 문서를 따라 진행한다.

## 1. 좌표계 규약

- **X**: 좌우 (관객 시점 우측 +)
- **Y**: 전후 (피사체 정면 방향 +, 즉 세계 정면)
- **Z**: 상하 (위 +)
- 눈높이 카메라 = Z 1.6m, 스탠딩 인체 정수리 = Z 1.75m
- 씬 JSON의 `pos_world`, `look_at_world` 는 모두 이 좌표계

## 2. 이징 화이트리스트 (스킬 근거 · 절대 위반 금지)

허용: `LINEAR` · `EASE_IN` · `EASE_OUT` · `EASE_IN_OUT`.
`easing_curve` 선택: `SINE` · `CUBIC` · `BEZIER`.
**금지**: `BACK` · `BOUNCE` · `ELASTIC` (오버슛/진동 → AI R2V 부적합).

## 3. 카메라 무빙 카탈로그 (기본 9종)

각 패턴은 두 개의 키프레임(시작·끝) 을 생성한다. 조합은 §5.

| 패턴 | 무엇이 바뀌나 | 무엇이 그대로 | 대표 easing |
|---|---|---|---|
| `static` | 없음 | pos, look_at 고정 | `LINEAR` (`hold: true`) |
| `dolly_in` | pos가 look_at에 접근 | look_at | `EASE_IN_OUT` + `CUBIC` |
| `dolly_out` | pos가 look_at에서 멀어짐 | look_at | `EASE_OUT` + `CUBIC` |
| `truck_left` / `truck_right` | pos·look_at 동시에 X축 병진 | 상대 프레이밍 | `LINEAR` 또는 `EASE_IN_OUT` |
| `pan_left` / `pan_right` | look_at이 X축 회전 | pos | `EASE_IN_OUT` |
| `tilt_up` / `tilt_down` | look_at이 Z축 회전 | pos | `EASE_IN_OUT` |
| `orbit_cw` / `orbit_ccw` | pos가 원호로 이동 | look_at (피사체) | `LINEAR` 또는 `EASE_IN_OUT` |
| `crane_up` / `crane_down` | pos.z 변화 | look_at (선택적으로 따라감) | `EASE_IN_OUT` |
| `dutch_tilt` | `dutch_tilt_deg` 변화 | pos, look_at | `LINEAR` |

### 3.1 공식

`P0` = 시작 pos, `L0` = 시작 look_at, `P1`/`L1` = 끝. `S` = 피사체 world center.

**dolly_in**: `L0 = L1 = S`, `P0 = S + n*d0`, `P1 = S + n*d1`, `d1 < d0`, `n` = 뷰 방향 유닛벡터 (예: 정면 = `(0,-1,0)`, 3/4 rear elevated = normalized `(1,-1,0.4)`).

**dolly_out**: `dolly_in` 반대 (`d1 > d0`).

**truck_right**: `P1 = P0 + (Δx, 0, 0)`, `L1 = L0 + (Δx, 0, 0)`. 좌트럭은 `-Δx`.

**pan_right**: `P0 = P1`, `L1 = P0 + R_z(θ) @ (L0 - P0)`, θ 양수 = 우측. 좌팬은 음수.

**tilt_up**: `P0 = P1`, `L1 = P0 + R_x_local(θ) @ (L0 - P0)`, θ 양수 = 위. 실무상 look_at.z 증분으로 근사 (θ°에 대해 Δz ≈ d·tan(θ), d = |L0-P0|).

**orbit_ccw** (피사체 중심 반시계): pos 를 피사체 중심으로 xy 평면 원호. `P0 = S + r·(cos α0, sin α0, h)`, `P1 = S + r·(cos α1, sin α1, h)`, `α1 > α0`, `L0 = L1 = S`. 시계는 `α1 < α0`.

**crane_up**: `P1 = P0 + (0, 0, Δh)`. look_at 옵션: (a) 고정 (b) `L1 = L0 + (0, 0, Δh)` (같이 올라감).

**dutch_tilt**: 두 kf 모두 pos·look_at 동일, `dutch_tilt_deg` 만 변화. 대개 정지 샷 위에 얹음.

## 4. Q&A 순서

Claude가 사용자에게 순서대로 묻는다. 답이 명확해질 때까지 각 단계 진행.

### Q1. 어느 shot이며 몇 초짜리?
- 예: "s001, 6초"
- 이미 씬 JSON에 shot이 있으면 duration 확인만.

### Q2. 피사체 world 좌표?
- "표준 스토리보드는 피사체 원점 (0, 0, Z)". 캐릭터 서있음 = (0, 0, 0.85)
- 오프센터면 좌표 직접 (예: 왼쪽 배치 = (-1.5, 0, 0.85))

### Q3. 원하는 무빙 카테고리?
- 카탈로그 9종 이름 제시. 사용자가 자연어로 표현하면 매핑:
  - "밀고 들어가" → dolly_in
  - "당겨서 빠지기" → dolly_out
  - "좌우로 흘려" → truck_left/right (병진)
  - "고개 돌려" → pan
  - "위/아래로 훑기" → tilt / crane
  - "빙 둘러" → orbit
  - "기울여" → dutch_tilt
- 여러 개면 시간대별 순서 확인 (§5).

### Q4. 파라미터?
- dolly: 시작 거리 · 끝 거리 (m)
- truck: 거리 (m)
- pan / tilt: 각도 (deg)
- orbit: 반경 · 시작·끝 각도 · 높이
- crane: Δh (m)
- dutch: 최대 tilt_deg (일반 0.5~2° 이내)

### Q5. 스타일?
- 시선 시작·끝: 카메라 눈높이 (m). 미명시면 1.6m.
- Focal length: 캐릭터 프레이밍 근거로 추천. wide 20~28, medium 35~50, close 70~85.
- 이징: 기본값 카탈로그의 대표 이징. 다른 표현 원하면 화이트리스트 내에서 지정.

### Q6. 프레이밍 검증?
- 계산된 pos·look_at 값 하나 이상이 [-15, 15]m 범위 밖이면 재확인.
- min_distance 검증: 모든 kf에서 카메라와 피사체 거리 ≥ 0.4m.

## 5. 조합 (시간 순차)

여러 패턴을 시간 구간으로 잇는다. 예: 6초 샷을 `0~3s dolly_in` + `3~6s pan_right` 로.

- 각 패턴 → 2 kf 생성 (시작·끝).
- 인접 두 패턴이 만나는 지점 (예: t=3s) 은 **한 번만** 삽입. 앞 패턴의 끝 = 뒤 패턴의 시작.
- 결과 `camera_keyframes[]` 는 시간 오름차순.
- `hold: true` 는 마지막 kf 에만 (샷 종료 정지 표시).

## 6. 완성 kf 구조

```json
{
  "t_sec": 0.0,
  "pos_world": [x, y, z],
  "look_at_world": [x, y, z],
  "easing": "EASE_IN_OUT",
  "easing_curve": "CUBIC",
  "hold": false,
  "dutch_tilt_deg": 0,
  "fov_deg": null,
  "fov_confidence": null,
  "focal_length_mm": 35.0,
  "shot_type": "medium_wide"
}
```

## 7. 예시

### 예 A. dolly_in (motorhome 콕핏, 6초, 캡틴 체어 정면 접근)

```json
[
  {"t_sec": 0.0, "pos_world": [3.2, -2.8, 2.3], "look_at_world": [-0.4, 0.8, 1.1],
   "easing": "EASE_IN_OUT", "easing_curve": "CUBIC", "hold": false,
   "focal_length_mm": 28.0, "shot_type": "wide"},
  {"t_sec": 6.0, "pos_world": [1.4, -1.5, 1.9], "look_at_world": [-0.2, 1.3, 1.0],
   "easing": "EASE_OUT", "easing_curve": "CUBIC", "hold": true,
   "focal_length_mm": 28.0, "shot_type": "medium_wide"}
]
```

### 예 B. orbit_ccw (숲 속 서있는 사람, 8초, 6m 반경 반원)

피사체 (0, 0, 0.85), 반경 6, 높이 2, α0=-90°(=정면), α1=+90°(=측면 넘어)

```json
[
  {"t_sec": 0.0, "pos_world": [0.0, -6.0, 2.0], "look_at_world": [0.0, 0.0, 0.85],
   "easing": "LINEAR", "easing_curve": "SINE", "hold": false,
   "focal_length_mm": 35.0, "shot_type": "wide"},
  {"t_sec": 8.0, "pos_world": [6.0, 0.0, 2.0], "look_at_world": [0.0, 0.0, 0.85],
   "easing": "LINEAR", "easing_curve": "SINE", "hold": true,
   "focal_length_mm": 35.0, "shot_type": "wide"}
]
```

### 예 C. dolly_in + pan_right 조합 (6초)

```json
[
  {"t_sec": 0.0, "pos_world": [0, -8, 1.6], "look_at_world": [0, 0, 1.4],
   "easing": "EASE_IN_OUT", "easing_curve": "CUBIC", "hold": false,
   "focal_length_mm": 35.0, "shot_type": "wide"},
  {"t_sec": 3.0, "pos_world": [0, -4, 1.6], "look_at_world": [0, 0, 1.4],
   "easing": "EASE_OUT", "easing_curve": "CUBIC", "hold": false,
   "focal_length_mm": 35.0, "shot_type": "medium_wide"},
  {"t_sec": 6.0, "pos_world": [0, -4, 1.6], "look_at_world": [2.5, 0, 1.4],
   "easing": "EASE_IN_OUT", "easing_curve": "SINE", "hold": true,
   "focal_length_mm": 35.0, "shot_type": "medium_wide"}
]
```

## 8. Claude가 반드시 지킬 것

- pos, look_at 계산 후 사용자에게 값 보여주고 확인 요청 → 승인 후 씬 JSON write.
- write 후 `python blender_previz/main.py --scene ... --shot ... --dry-run` 실행해 스키마 통과 여부 확인.
- 이후 `preview_composite.py` 로 렌더 원하는지 물어봄.
- 이징이 화이트리스트 밖이면 abort 하고 사용자에게 다시 물음.
- min_distance 위반 시 사용자에게 알리고 pos 조정 제안.
