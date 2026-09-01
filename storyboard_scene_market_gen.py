"""참고 이미지(한옥 행랑마당 장터) → storyboard_scene JSON 생성기.

■ 배치 원리 (조사 결과)
  중정(中庭) = 여러 채가 둘러싼 중앙 마당. ㄷ자/ㅁ자 배치.
  각 채는 마당을 향해 '안쪽으로' 선다 → 좌우 채의 정면이 서로 마주본다.
  참고 이미지는 멍석(곡식 건조)·장터·장작·장독대가 있는 행랑마당 성격.

  따라서 좌우 채는 카메라 정면이 아니라 마당 양옆에 세로로 서고,
  정면(기둥열+분합문)이 마당 안쪽을 향한다. 카메라는 마당 한가운데 선다.

      뒤: 돌담 ─ 그 너머 초가
         ┌─────────────────┐
   좌측채│      마 당       │우측채   ← 정면이 서로 마주봄
   (차양)│    (멍석/장터)    │(장작)
         └────── ▲ ────────┘
              카메라(마당 안)

■ 좌표 authoring
  스키마는 소품을 screen_position(0..1)+depth_m 으로 받지만 세트는 월드 좌표로
  설계하는 편이 자연스럽다. 월드로 배치 → 기준 키프레임에 역투영 →
  placement.screen_to_world_at_depth 로 왕복 검증(오차 <1e-6m).

  기준 키프레임은 pick_camera_reference_for_panel(placement.py)이 정한다.
  샷마다 패널을 2개 두고, 소품은 시작/끝 키프레임 중 먼저 화면 안에 들어오는
  쪽 패널로 자동 배정한다. 그래서 시작 프레임에만 보이는 것과 이동 후에야
  들어오는 것이 각각 올바른 카메라를 기준으로 좌표를 얻는다.

■ 건축 치수는 ASSUMPTIONS 블록이 전부 결정한다. 실측 도면이 생기면 그 블록만 고친다.

용법:
  python storyboard_scene_market_gen.py   → storyboard_scene_market.json 갱신
"""
from __future__ import annotations
import json
import math
import sys
from math import atan, cos, radians, sin, sqrt
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "blender_previz"))

from placement import screen_to_world_at_depth  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
#  ASSUMPTIONS — 한옥 민가 치수 (실측 자료 없음. 전부 가정값)
#  조선 후기 일반 민가 기준. 실제 도면 확보 시 이 블록만 교체하면 전체가 따라간다.
# ═══════════════════════════════════════════════════════════════════════════
KAN          = 2.4    # 1칸(주간거리). 민가 8자 기준
# 기둥 단면: 민가는 반드시 방주(方柱, 사각기둥). 원주(圓柱)는 격이 높아 정전·큰 건물에 쓰였고
# 조선시대 민가에는 원기둥 사용이 법으로 금지되었다. → shape 은 cylinder 가 아니라 cube.
COL_D        = 0.21   # 기둥 한 변. 민가 6~8치의 중간값
COL_H        = 2.4    # 기둥 높이(초석 상단~처마도리)
FOOT_D       = 0.45   # 초석(덤벙주초) 직경
FOOT_H       = 0.25   # 초석 노출 높이
STYLO_H      = 0.45   # 기단 높이. 민가 1~2단
STYLO_MARGIN = 0.6    # 기단이 기둥열 밖으로 나온 폭
EAVE         = 1.05   # 처마 내밀기. 민가 0.9~1.2m
TILE_ROOF_H  = 1.5    # 기와지붕 처마~용마루
DOOR_T       = 0.08   # 분합문 두께
MARU_T       = 0.12   # 대청마루 널 두께
TOEN_D       = 0.9    # 툇간 깊이. 앞 기둥열(툇기둥)과 분합문 사이 툇마루 폭.
                      # 민가는 반 칸 안팎.

THATCH_EAVE    = 0.7   # 초가 처마는 짧다
THATCH_ROOF_H  = 1.8   # 볏짚이 두꺼워 지붕 덩어리가 크다
THATCH_WALL_H  = 2.1   # 흙벽. 기와집보다 낮다
THATCH_STYLO_H = 0.3

WALL_H, WALL_T = 1.35, 0.45   # 돌담. 민가 1.2~1.5m

# 규모 (칸 수) — 참고 이미지에서 읽은 값이라 이것도 가정
EAST_BAYS_W, EAST_BAYS_D = 4, 2     # 우측 채: 정면 4칸
WEST_BAYS_W, WEST_BAYS_D = 3, 2     # 좌측 채: 정면 3칸
CHOGA_BAYS_W, CHOGA_BAYS_D = 3, 1.5 # 초가삼간

# 마당 규모 — 좌우 채 정면 사이 거리(가정 11m). 민가 행랑마당은 대체로 이 정도.
SENSOR_MM, FOCAL_MM = 36.0, 24.0
ASPECT, FPS, DURATION = 16.0 / 9.0, 24, 8.0

# 샷 정의: (cam, look) 쌍의 시작/끝. 소품 screen_position 은 각 샷의 두 키프레임 중
# 먼저 프레임 안에 들어오는 쪽을 기준으로 자동 배정된다.
SHOTS = [
    {
        "id": "s001", "dur": 8.0,
        # 오른쪽 레일 이동. 참고 이미지 프레이밍에서 출발해 시선이 단상으로 수렴.
        "start": ((0.0, -9.0, 1.6), (1.0, 6.0, 1.6)),
        "end":   ((5.0, -9.0, 1.6), (-4.0, 1.5, 1.1)),
        "frag_a": "empty Korean hanok service courtyard before market opens, ink-and-watercolor "
                  "style, two tiled-roof wings enclose the yard from left and right with their "
                  "column-and-lattice-door fronts facing each other, a hemp awning tied to the "
                  "left wing shelters a low wooden stage with a drum, stone wall closes the far "
                  "end with a thatched house and pine beyond, straw grain-drying mats on the dirt",
        "frag_b": "camera has railed to the right; the wooden stage under the awning now sits at "
                  "the centre of frame, the right-hand wing has slid past the right edge, the "
                  "stone wall and thatched house fill the upper right",
    },
    {
        # Seedance 2.5 최소 길이가 4초라 3초 요청은 클램프된다. 이동은 3초에 끝내고
        # 나머지 1초는 버드뷰에서 홀드 → 움직임 자체는 3초, 산출물은 4초.
        "id": "s002", "dur": 4.0, "arrive": 3.0,
        # 무대(단상) 근접에서 출발해 뒤로 물러나며 솟아올라 마당 전체를 내려다보는 버드뷰.
        # 프리뷰가 샷당 focal 하나만 쓰므로 줌이 아니라 달리아웃으로 구현한다.
        "start": ((-4.0, -3.0, 2.0), (-4.2, 1.0, 1.0)),
        "end":   ((0.0, -16.0, 24.0), (0.0, 6.0, 0.0)),
        "frag_a": "tight on the low wooden stage under the hemp awning, the barrel drum and "
                  "hourglass drum resting on worn planks, ink-and-watercolor style",
        "frag_b": "camera pulls back and rises into a high bird's-eye view of the whole "
                  "courtyard, both tiled-roof wings, the stone wall, the thatched house and the "
                  "straw mats laid out on the dirt yard all visible from above",
    },
]


def _place(cx, cy, lx, ly, yaw_deg):
    """건물 로컬좌표(lx,ly) → 월드. yaw 는 Z축 회전(로컬 -Y 가 정면)."""
    c, s = cos(radians(yaw_deg)), sin(radians(yaw_deg))
    return (cx + lx * c - ly * s, cy + lx * s + ly * c)


def tile_house(prefix, cx, cy, bays_w, bays_d, yaw, kor, bay_filter=None):
    """기와집 한 채. 한옥 단면을 앞에서 뒤로 그대로 쌓는다.

        툇기둥열 ─ 툇마루 ─ 분합문 ─ 몸채(방) ─ 뒷기둥열
        지붕은 양쪽 기둥열 밖으로 EAVE 만큼 처마를 내민다.

    분합문은 '몸채의 앞면'이다. 앞 기둥열에 붙이면 문 뒤에 또 벽이 서서 그 사이가
    빈 이중 껍질이 되므로 그러지 않는다. 앞 기둥열은 툇마루 위에 열린 채로 선다.

    기둥은 툇기둥 한 줄만 세운다. 실제 한옥엔 뒷기둥도 있지만 몸채 벽면에 묻혀
    보이지 않고, 몸채가 배면까지 차서 지붕을 이미 받친다. 블록아웃은 화면에
    드러나는 것만 만든다.

    로컬 기준 정면은 -Y 쪽. yaw 로 통째 회전시켜 마당을 향하게 한다.
    yaw=0 정면이 -Y(카메라쪽) / yaw=-90 정면이 -X(서) / yaw=+90 정면이 +X(동).
    bay_filter: 세울 기둥 인덱스 집합. 화면 밖 칸을 생략할 때 쓴다.
    scale_m 은 로컬 축 기준이고 회전은 prop 의 yaw_deg 가 담당한다.
    """
    w, d = bays_w * KAN, bays_d * KAN
    fy, by = -d / 2.0, d / 2.0         # 로컬 정면 / 배면 y
    door_y = fy + TOEN_D               # 분합문 = 몸채 앞면
    body_c, body_d = (door_y + by) / 2.0, by - door_y
    stylo_top = STYLO_H
    col_base = stylo_top + FOOT_H
    col_top = col_base + COL_H
    out = []

    px, py = _place(cx, cy, 0, 0, yaw)
    out.append((f"{prefix}_stylobate", "cube", (px, py, STYLO_H / 2),
                (w + 2 * STYLO_MARGIN, d + 2 * STYLO_MARGIN, STYLO_H), yaw,
                f"{kor} 기단, 다듬은 돌을 낮게 쌓은 단"))

    cols = [-w / 2.0 + i * KAN for i in range(bays_w + 1)]
    idxs = list(range(len(cols))) if bay_filter is None else sorted(bay_filter)
    # 툇기둥열. 덤벙주초는 다듬지 않은 자연석이라 둥그스름 → cylinder 로 근사.
    # 기둥은 방주(사각기둥) — 민가에 원기둥은 쓸 수 없다.
    for i in idxs:
        px, py = _place(cx, cy, cols[i], fy, yaw)
        out.append((f"{prefix}_footing{i}", "cylinder",
                    (px, py, stylo_top + FOOT_H / 2), (FOOT_D, FOOT_D, FOOT_H), yaw,
                    f"{kor} 덤벙주초, 다듬지 않은 자연석 주춧돌"))
        out.append((f"{prefix}_column{i}", "cube",
                    (px, py, col_base + COL_H / 2), (COL_D, COL_D, COL_H), yaw,
                    f"{kor} 네모진 나무 기둥(방주)"))

    for i in range(len(cols) - 1):
        if bay_filter is not None and not (i in bay_filter and i + 1 in bay_filter):
            continue
        px, py = _place(cx, cy, (cols[i] + cols[i + 1]) / 2.0, door_y, yaw)
        # 높이를 기둥과 같게 잡아 아래위로 뜨지 않게 한다
        out.append((f"{prefix}_door{i}", "cube", (px, py, col_base + COL_H / 2),
                    (KAN - COL_D, DOOR_T, COL_H), yaw,
                    f"{kor} 창호지 분합문 한 칸, 격자살이 비침"))

    # 툇마루: 앞 기둥열과 분합문 사이
    px, py = _place(cx, cy, 0, (fy + door_y) / 2.0, yaw)
    out.append((f"{prefix}_maru", "cube", (px, py, stylo_top + MARU_T / 2),
                (w * 0.96, TOEN_D, MARU_T), yaw,
                f"{kor} 툇마루, 처마 밑 기둥열 사이로 난 나무 바닥"))
    # 몸채: 분합문 뒤부터 배면까지
    px, py = _place(cx, cy, 0, body_c, yaw)
    out.append((f"{prefix}_body", "cube", (px, py, col_base + COL_H / 2),
                (w * 0.98, body_d, COL_H), yaw, f"{kor} 몸채 흙벽, 안쪽 방들"))
    px, py = _place(cx, cy, 0, 0, yaw)
    out.append((f"{prefix}_roof", "asymmetric_wedge", (px, py, col_top),
                (w + 2 * EAVE, d + 2 * EAVE, TILE_ROOF_H), yaw,
                f"{kor} 기와지붕, 처마가 깊게 내밀고 끝에 단청이 보임"))
    return out


def thatch_house(prefix, cx, cy, bays_w, bays_d, yaw, kor="초가집"):
    """초가. 기둥열을 드러내지 않고 흙벽 + 두꺼운 볏짚 지붕."""
    w, d = bays_w * KAN, bays_d * KAN
    wall_top = THATCH_STYLO_H + THATCH_WALL_H
    return [
        (f"{prefix}_stylobate", "cube", (cx, cy, THATCH_STYLO_H / 2),
         (w + 0.6, d + 0.6, THATCH_STYLO_H), yaw, f"{kor} 낮은 흙기단"),
        (f"{prefix}_wall", "cube", (cx, cy, THATCH_STYLO_H + THATCH_WALL_H / 2),
         (w, d, THATCH_WALL_H), yaw, f"{kor} 흙벽, 낮고 두툼한 벽면"),
        (f"{prefix}_roof", "asymmetric_wedge", (cx, cy, wall_top),
         (w + 2 * THATCH_EAVE, d + 2 * THATCH_EAVE, THATCH_ROOF_H), yaw,
         f"{kor} 볏짚 지붕, 두껍게 이어 얹어 모서리가 둥글다"),
    ]


# ─── 세트 조립 (ㄷ자 중정) ──────────────────────────────────────────────────
PROPS = [
    ("madang_ground", "grid_plane", (0.0, 4.0, 0.0), (110.0, 110.0, 1.0), 0,
     "밟아 다져진 흙마당, 마른 모래빛 바닥"),
]

# 우측 채 — 마당 동쪽. 정면(기둥열)이 서쪽 마당을 향한다.
PROPS += tile_house("east", cx=8.0, cy=4.5, bays_w=EAST_BAYS_W, bays_d=EAST_BAYS_D,
                    yaw=-90, kor="우측 기와 채")

# 좌측 채 — 마당 서쪽. 정면이 동쪽 마당을 향한다. 앞칸은 화면 밖이라 생략.
PROPS += tile_house("west", cx=-8.5, cy=5.0, bays_w=WEST_BAYS_W, bays_d=WEST_BAYS_D,
                    yaw=90, kor="좌측 기와 채", bay_filter={0, 1, 2, 3})

# 안쪽 — 돌담과 그 너머 초가삼간
PROPS += thatch_house("choga", cx=-1.0, cy=16.5,
                      bays_w=CHOGA_BAYS_W, bays_d=CHOGA_BAYS_D, yaw=0)

PROPS += [
    ("stone_wall", "cube", (0.0, 13.0, WALL_H / 2), (17.0, WALL_T, WALL_H), 0,
     "기와를 얹은 낮은 돌담"),

    # 좌측 채에 매인 장터 차양 — 마당 안쪽으로 뻗는다
    ("chayang_pole_a", "cylinder", (-4.9, -0.3, 1.55), (0.09, 0.09, 3.1), 0,
     "차양을 받친 대나무 장대"),
    ("chayang_pole_b", "cylinder", (-4.3, 1.6, 1.6), (0.09, 0.09, 3.2), 0,
     "차양을 받친 대나무 장대"),
    ("chayang_pole_c", "cylinder", (-3.7, 3.5, 1.6), (0.09, 0.09, 3.2), 0,
     "차양을 받친 대나무 장대"),
    ("chayang_canopy", "cube", (-4.6, 1.6, 3.05), (2.6, 5.4, 0.06), 0,
     "장터 차양, 빛바랜 삼베 천막이 마당 쪽으로 늘어짐"),
    ("dansang_platform", "cube", (-4.0, 1.5, 0.35), (2.4, 4.0, 0.7), 0,
     "낮은 나무 단상, 널빤지가 드러난 마루"),
    ("buk_drum", "cylinder", (-4.4, 0.2, 1.0), (0.6, 0.6, 0.6), 0,
     "단상 위에 놓인 전통 북, 나무통에 가죽을 메운 북"),
    ("janggu_drum", "cylinder", (-3.9, 2.0, 0.95), (0.3, 0.3, 0.5), 0,
     "장구, 잘록한 허리의 장구통"),
    ("jwapan_stall", "cube", (-3.4, 4.6, 0.4), (1.1, 2.0, 0.8), 0,
     "좌판 매대, 천을 덮은 나무 판매대"),
    ("basket_goods", "cylinder", (-3.2, 3.9, 0.95), (0.5, 0.5, 0.35), 0,
     "곡식이 담긴 싸리 광주리"),

    # 안쪽 담 앞 장독대
    ("jangdok_big", "sphere", (1.6, 11.4, 0.4), (0.8, 0.8, 0.8), 0,
     "장독대의 큰 옹기 항아리"),
    ("jangdok_small", "sphere", (2.4, 11.5, 0.35), (0.7, 0.7, 0.7), 0,
     "장독대의 작은 옹기 항아리"),
    ("jangdok_table", "cube", (3.6, 11.2, 0.4), (1.8, 0.8, 0.8), 0,
     "항아리를 올려둔 낮은 나무 상"),

    # 우측 채 기단 앞 — 장작과 항아리
    ("firewood_stack", "cube", (4.6, 1.4, 0.5), (1.0, 1.6, 1.0), 0,
     "차곡히 쌓은 장작더미"),
    ("jangdok_right", "sphere", (4.4, 3.4, 0.35), (0.7, 0.7, 0.7), 0,
     "댓돌 옆에 놓인 옹기 항아리"),

    # 마당 — 곡식 말리는 멍석 (행랑마당의 성격)
    ("mengseok_a", "cube", (-0.6, 4.4, 0.02), (2.6, 1.8, 0.04), 0,
     "곡식 말리려 펼친 짚 멍석"),
    ("mengseok_b", "cube", (2.2, 5.0, 0.02), (2.6, 1.8, 0.04), 0,
     "곡식 말리려 펼친 짚 멍석"),
    ("mengseok_c", "cube", (0.6, 1.8, 0.02), (2.8, 1.9, 0.04), 0,
     "마당 앞쪽에 펼친 짚 멍석"),
    ("mengseok_rolled", "cube", (2.8, 2.4, 0.12), (2.2, 0.25, 0.25), 0,
     "둘둘 말아둔 멍석 한 통"),
    ("mengseok_front", "cube", (1.6, -3.6, 0.02), (3.4, 2.4, 0.04), 0,
     "화면 앞쪽에 크게 걸치는 짚 멍석"),

    # 배경
    ("pine_trunk", "cylinder", (-3.2, 19.5, 2.0), (0.4, 0.4, 4.0), 0,
     "담장 너머 소나무 줄기"),
    ("pine_canopy", "sphere", (-3.2, 19.5, 4.8), (3.2, 3.2, 1.8), 0,
     "옆으로 퍼진 소나무 솔잎 덩어리"),
]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a):
    m = sqrt(sum(c * c for c in a))
    return tuple(c / m for c in a) if m > 1e-12 else (0.0, 0.0, 0.0)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def world_to_screen(cam_pos, look_at, p):
    forward = _norm(_sub(look_at, cam_pos))
    up_w = (0.0, 0.0, 1.0)
    right = _norm(_cross(forward, (0.0, 1.0, 0.0))) if abs(_dot(forward, up_w)) > 0.9999 \
        else _norm(_cross(forward, up_w))
    up = _norm(_cross(right, forward))
    d = _sub(p, cam_pos)
    depth = sqrt(sum(c * c for c in d))
    dir_ = _norm(d)
    f, r, u = _dot(dir_, forward), _dot(dir_, right), _dot(dir_, up)
    half_h = atan((SENSOR_MM / 2.0) / FOCAL_MM)
    half_v = atan(math.tan(half_h) / ASPECT)
    return ((r / f) / math.tan(half_h) / 2.0 + 0.5,
            0.5 - (u / f) / math.tan(half_v) / 2.0,
            depth)


def _prop_entry(name, shape, role, sx, sy, depth, yaw, scale):
    return {"name": name, "shape": shape, "final_role": role,
            "screen_position": {"x": round(sx, 5), "y": round(sy, 5)},
            "estimated_transform": {"depth_m": round(depth, 4), "yaw_deg": yaw,
                                    "scale_m": list(scale)}}


def split_props_for_shot(shot, problems):
    """이 샷의 시작/끝 키프레임 중 먼저 화면에 들어오는 쪽으로 소품을 배정."""
    (cam_a, look_a), (cam_b, look_b) = shot["start"], shot["end"]
    a_props, b_props = [], []
    for name, shape, pos, scale, yaw, role in PROPS:
        for cam, look, bucket in ((cam_a, look_a, a_props), (cam_b, look_b, b_props)):
            sx, sy, depth = world_to_screen(cam, look, pos)
            if not (0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0 and depth > 0):
                continue
            back = screen_to_world_at_depth(
                cam_pos=cam, look_at=look, screen_x=sx, screen_y=sy,
                focal_mm=FOCAL_MM, sensor_width_mm=SENSOR_MM,
                aspect_ratio=ASPECT, depth_m=depth)
            err = max(abs(x - y) for x, y in zip(back, pos))
            if err > 1e-6:
                problems.append(f"  [{shot['id']}] {name}: 왕복 오차 {err:.6f}m")
            bucket.append(_prop_entry(name, shape, role, sx, sy, depth, yaw, scale))
            break
        else:
            sa = world_to_screen(cam_a, look_a, pos)
            sb = world_to_screen(cam_b, look_b, pos)
            problems.append(f"  [{shot['id']}] {name}: 시작({sa[0]:.2f},{sa[1]:.2f})·"
                            f"끝({sb[0]:.2f},{sb[1]:.2f}) 모두 프레임 밖")
    return a_props, b_props


def main() -> int:
    problems = []
    per_shot = [(s, *split_props_for_shot(s, problems)) for s in SHOTS]

    if problems:
        print("[error] 배치 문제:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 1

    def panel(pid, frag, props_in):
        return {
            "panel_id": pid, "source_image_path": None, "location_id": "hanok_haengrang_madang",
            "camera_state": {"shot_type": "extreme_wide", "angle_type": "eye_level",
                             "dutch_tilt_deg": 0, "focal_length_mm": FOCAL_MM,
                             "estimated_pose": {"fov_deg": None, "confidence": None}},
            "characters_in_frame": [], "props_in_frame": props_in,
            "lighting": {"time_of_day": "morning",
                         "notes": "엷은 구름을 통과한 부드러운 확산광, 그림자가 옅음"},
            "sound_notes": "마당의 마른 바람, 멀리 새소리, 인적 없음",
            "seedance_prompt_fragment": frag,
        }

    def kf(t, pos, look, easing, curve, hold=False):
        d = {"t_sec": t, "pos_world": list(pos), "look_at_world": list(look),
             "easing": easing, "hold": hold, "dutch_tilt_deg": 0,
             "fov_deg": None, "fov_confidence": None, "focal_length_mm": FOCAL_MM}
        if curve is not None:      # 스키마 enum 에 null 이 없으므로 없을 땐 키 자체를 뺀다
            d["easing_curve"] = curve
        if not hold:
            d["shot_type"] = "extreme_wide"
        return d

    panels, shots = [], []
    for i, (shot, a_props, b_props) in enumerate(per_shot):
        pa, pb = f"p{2*i+1:03d}", f"p{2*i+2:03d}"
        panels.append(panel(pa, shot["frag_a"], a_props))
        panels.append(panel(pb, shot["frag_b"], b_props))
        (cam_a, look_a), (cam_b, look_b) = shot["start"], shot["end"]
        arrive = shot.get("arrive", shot["dur"])
        keys = [kf(0.0, cam_a, look_a, "EASE_IN_OUT", "CUBIC"),
                kf(arrive, cam_b, look_b, "EASE_OUT", "SINE", hold=(arrive >= shot["dur"]))]
        if arrive < shot["dur"]:
            # 도착 후 남은 시간은 같은 자리에서 정지 (LINEAR + hold 로 미동 없음)
            keys.append(kf(shot["dur"], cam_b, look_b, "LINEAR", None, hold=True))
        shots.append({
            "shot_id": shot["id"], "panel_ids": [pa, pb],
            "duration_sec": shot["dur"], "continuous_take": True,
            "camera_keyframes": keys,
            "shot_level_seedance_prompt": None})

    scene = {
        "schema_version": "1.1",
        "story_meta": {"title": "한옥 행랑마당 장터",
                       "logline": "장이 서기 전, 비어 있는 마당을 훑는다.",
                       "aspect_ratio": "16:9"},
        "characters": [],
        "locations": [{"location_id": "hanok_haengrang_madang",
                       "description": "기와 채 둘이 좌우에서 감싸고 안쪽을 돌담이 막은 ㄷ자 행랑마당. "
                                      "좌측 채에 차양을 매어 장터 단상을 놓았고, 마당에는 곡식 "
                                      "말리는 멍석이 깔렸다. 담 너머로 초가삼간과 소나무가 보인다"}],
        "panels": panels,
        "shots": shots,
        "scene_meta": {"fps": FPS, "sensor_width_mm": SENSOR_MM,
                       "min_distance_m": 0.4, "fov_confidence_threshold": 0.3},
    }

    out = REPO / "storyboard_scene_market.json"
    out.write_text(json.dumps(scene, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[ok] {out.name}: 소품 {len(PROPS)}종, 샷 {len(shots)}개, 왕복 오차 <1e-6m")
    for shot, a_props, b_props in per_shot:
        (ca, _), (cb, _) = shot["start"], shot["end"]
        print(f"  {shot['id']} {shot['dur']:>4.1f}s  cam z {ca[2]:>5.1f}m -> {cb[2]:>5.1f}m  "
              f"패널 {len(a_props)}+{len(b_props)}개")
    print(f"[배치] ㄷ자 중정. 마당 폭 "
          f"{(8.0-EAST_BAYS_D*KAN/2)-(-8.5+WEST_BAYS_D*KAN/2):.1f}m")
    print(f"[가정] 1칸={KAN}m, 기둥 h{COL_H}m, 기단 {STYLO_H}m, 처마 {EAVE}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
