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

from assumptions import A, report, unverified, write_sidecar  # noqa: E402
from placement import screen_to_world_at_depth  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
#  가정값 — assumptions.A() 로 등록한다. source 는 키워드 전용 필수 인자라,
#  출처를 모르면 source=None 이라고 명시할 수밖에 없고 그 값은 실행할 때마다
#  '미확인' 목록에 떠서 주석 뒤에 숨지 못한다. 자세한 이유는 assumptions.py 참조.
#
#  실측 도면이 생기면 미확인 항목부터 교체한다. (motorhome 씬처럼 도면이 있으면
#  그 값이 사실이고, 이 블록은 도면이 없을 때의 대체물일 뿐이다.)
# ═══════════════════════════════════════════════════════════════════════════
KAN = A("KAN", 2.4, "m", "1칸(주간거리)",
        source="조선 민가 영조법식 기준 8자. 영조척 1자=30.8~31cm → 8자≈2.46m, "
               "통상 2.4m 로 쓴다")
COL_D = A("COL_D", 0.21, "m", "기둥 한 변(방주)",
          source="주간 8자일 때 기둥은 7~8치 각이 적정하고 살림집은 7치가 적당. "
                 "7치=21.2cm. 민가는 방주만 허용(조선시대 원기둥 금지)")
TOEN_D = A("TOEN_D", 0.9, "m", "툇간 깊이(툇기둥~분합문)",
           source="전면 평주와 안쪽 고주 사이 '반칸 정도(3~4자)'=0.91~1.21m 중 "
                  "하한인 3자(0.909m). 툇마루는 남부지방 一자형 민가의 보편 요소")
COL_H = A("COL_H", 2.25, "m", "기둥 높이(초석 상단~처마도리)",
          source="한옥 방의 천장 높이 약 7.5자(225cm) 기준. 다만 천장고와 기둥고는 "
                 "정확히 같지 않아 근사값이다")

# 지붕은 높이가 아니라 물매(수평 10 에 대한 수직 비)로 잡는다. 그래야 문헌의
# '초가가 기와보다 물매가 뜨다'는 관계가 건물 크기와 무관하게 유지된다.
TILE_PITCH = A("TILE_PITCH", 0.4, "비", "기와지붕 물매(4치)",
               source="기와는 물매를 세치(0.3) 이하로 하면 물이 역류해 누수가 생기므로 "
                      "그보다 세운 4치를 택했다")
THATCH_PITCH = A("THATCH_PITCH", 0.3, "비", "초가지붕 물매(3치)",
                 source="초가는 기와집보다 물매가 뜨다(작다)는 것이 가장 큰 차이. "
                        "방향만 문헌 근거이고 3치라는 값 자체는 미확인")

FOOT_D       = A("FOOT_D", 0.45, "m", "초석(덤벙주초) 직경", source=None)
FOOT_H       = A("FOOT_H", 0.25, "m", "초석 노출 높이", source=None)
STYLO_H      = A("STYLO_H", 0.45, "m", "기단 높이", source=None)
STYLO_MARGIN = A("STYLO_MARGIN", 0.6, "m", "기단이 기둥열 밖으로 나온 폭", source=None)
EAVE         = A("EAVE", 1.05, "m", "처마 내밀기", source=None)
DOOR_T       = A("DOOR_T", 0.08, "m", "분합문 두께", source=None)
MARU_T       = A("MARU_T", 0.12, "m", "마루 널 두께", source=None)

THATCH_EAVE    = A("THATCH_EAVE", 0.7, "m", "초가 처마 내밀기", source=None)
THATCH_WALL_H  = A("THATCH_WALL_H", 2.1, "m", "초가 흙벽 높이", source=None)
THATCH_STYLO_H = A("THATCH_STYLO_H", 0.3, "m", "초가 기단 높이", source=None)

WALL_H = A("WALL_H", 1.35, "m", "돌담 높이", source=None)
WALL_T = A("WALL_T", 0.45, "m", "돌담 두께", source=None)

# 규모 — 참고 이미지를 눈으로 읽은 값이라 측정이 아니다
EAST_BAYS_W = A("EAST_BAYS_W", 4, "칸", "우측 채 정면 칸수", source=None)
EAST_BAYS_D = A("EAST_BAYS_D", 2, "칸", "우측 채 측면 칸수", source=None)
WEST_BAYS_W = A("WEST_BAYS_W", 3, "칸", "좌측 채 정면 칸수", source=None)
WEST_BAYS_D = A("WEST_BAYS_D", 2, "칸", "좌측 채 측면 칸수", source=None)
CHOGA_BAYS_W = A("CHOGA_BAYS_W", 3, "칸", "초가 정면 칸수(초가삼간)", source=None)
CHOGA_BAYS_D = A("CHOGA_BAYS_D", 1.5, "칸", "초가 측면 칸수", source=None)

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
                f"{kor} 기단, 다듬지 않은 자연석을 낮게 쌓은 단"))

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
    roof_d = d + 2 * EAVE
    out.append((f"{prefix}_roof", "asymmetric_wedge", (px, py, col_top),
                (w + 2 * EAVE, roof_d, roof_d / 2 * TILE_PITCH), yaw,
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
         (w + 2 * THATCH_EAVE, d + 2 * THATCH_EAVE,
          (d + 2 * THATCH_EAVE) / 2 * THATCH_PITCH), yaw,
         f"{kor} 볏짚 지붕, 두껍게 이어 얹었으나 물매는 기와보다 뜨다"),
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

    # 좌측 채에 매인 장터 차양.
    # 차양은 건물 처마에서 마당 쪽으로 뻗고, 장대는 그 '바깥 모서리'를 받친다.
    # 장대를 단상 위에 세우면 무대 한복판에 기둥이 박혀 사람이 설 자리가 없어진다.
    # x 를 하나로 통일해 일직선으로 세운다(제각각 두면 사선으로 박힌다).
    ("chayang_pole_a", "cylinder", (-2.9, -0.6, 1.55), (0.09, 0.09, 3.1), 0,
     "차양 바깥 모서리를 받친 대나무 장대"),
    ("chayang_pole_b", "cylinder", (-2.9, 1.5, 1.6), (0.09, 0.09, 3.2), 0,
     "차양 바깥 모서리를 받친 대나무 장대"),
    ("chayang_pole_c", "cylinder", (-2.9, 3.6, 1.6), (0.09, 0.09, 3.2), 0,
     "차양 바깥 모서리를 받친 대나무 장대"),
    ("chayang_canopy", "cube", (-4.2, 1.5, 3.05), (2.8, 5.0, 0.06), 0,
     "장터 차양, 건물 처마에서 마당 쪽으로 늘어진 삼베 천막"),
    # 단상: 건물과 장대 사이. 가운데는 사람이 올라설 수 있게 비워둔다.
    ("dansang_platform", "cube", (-4.4, 1.5, 0.35), (2.0, 3.6, 0.7), 0,
     "낮은 나무 단상, 널빤지가 드러난 마루"),
    ("buk_drum", "cylinder", (-4.7, 0.5, 1.0), (0.6, 0.6, 0.6), 0,
     "단상 한쪽에 놓인 전통 북, 나무통에 가죽을 메운 북"),
    ("janggu_drum", "cylinder", (-4.1, 2.4, 0.95), (0.3, 0.3, 0.5), 0,
     "장구, 잘록한 허리의 장구통"),
    ("jwapan_stall", "cube", (-3.6, 5.4, 0.4), (1.1, 2.0, 0.8), 0,
     "좌판 매대, 천을 덮은 나무 판매대"),
    ("basket_goods", "cylinder", (-3.3, 4.7, 0.95), (0.5, 0.5, 0.35), 0,
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


def check_clear_surfaces(problems):
    """사람이 올라서는 면(단상·마루) 한복판에 수직 부재가 박혔는지 검사.

    차양 장대를 단상 위에 세워 무대 가운데를 막아버린 적이 있다. 눈으로는
    프리뷰를 한참 봐야 보이지만 좌표로는 즉시 잡힌다.

    회전한 건물의 마루는 yaw!=0 이라 축정렬 사각형으로 볼 수 없어 건너뛴다.
    건물 기둥은 설계상 마루의 '가장자리'에 서므로 안쪽 판정에서 걸리지 않는다.
    """
    boxes = {n: (p, s) for n, sh, p, s, y, r in PROPS if y == 0}
    surfaces = [n for n in boxes if "platform" in n or n.endswith("_maru")]
    verticals = [n for n in boxes if "pole" in n or "column" in n]
    for sn in surfaces:
        (sx, sy, _), (sw, sd, _) = boxes[sn]
        x0, x1, y0, y1 = sx - sw / 2, sx + sw / 2, sy - sd / 2, sy + sd / 2
        for vn in verticals:
            (vx, vy, _), _ = boxes[vn]
            if x0 < vx < x1 and y0 < vy < y1:
                problems.append(
                    f"  {vn} ({vx:+.2f},{vy:+.2f}) 가 {sn} "
                    f"(x {x0:+.2f}~{x1:+.2f}, y {y0:+.2f}~{y1:+.2f}) 한복판에 박혔다")


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
    check_clear_surfaces(problems)
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

    # 가정값 출처 현황을 매 실행마다 드러낸다. 주석 뒤에 숨지 못하게.
    side = write_sidecar(REPO / "storyboard_scene_market_assumptions.md",
                         "한옥 마당 씬 가정값")
    for line in report():
        print(line)
    print(f"[가정] 표 -> {side.name}")

    if "--strict-assumptions" in sys.argv and unverified():
        print(f"[error] 미확인 가정 {len(unverified())}개 — --strict-assumptions 위반",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
