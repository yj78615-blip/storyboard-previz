"""2D 스크린 좌표 + 카메라 상태 → 3D 월드 좌표.

핵심 함수 screen_to_world_at_depth는 순수 수학. bpy 불필요.

가정:
  - depth_m은 카메라→피사체 광선을 따라 잰 거리(ray distance).
    DA3의 metric_depth는 optical-axis Z-depth지만, 첫 버전은 프리비즈 근사라 ray distance로 취급.
    ponytail: 나중에 DA3 정밀 대응 시 광축 투영 보정 추가.
  - screen_position은 (0..1) 정규화, 원점 좌상단. x=오른쪽, y=아래.
  - 월드 up = +Z (blender 규약).

fallback 거리표 (depth_m=null일 때):
  shot_type 별 대표 거리. 프리뷰 스케일이 크게 어긋나지 않게 하는 최소한.
"""

from __future__ import annotations
from math import atan, cos, radians, sin, sqrt, tan
from typing import Sequence

WORLD_UP = (0.0, 0.0, 1.0)

# Fallback 거리 (미터). shot_type 만으로 대략의 씬 스케일 잡을 때.
DEFAULT_DEPTH_M = {
    "extreme_wide":  20.0,
    "wide":          10.0,
    "medium_wide":    6.0,
    "medium":         3.0,
    "medium_close":   2.0,
    "close":          1.5,
    "extreme_close":  1.0,
}


def _vec_sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(a: Sequence[float], s: float) -> tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_norm(a: Sequence[float]) -> tuple[float, float, float]:
    m = sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if m < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / m, a[1] / m, a[2] / m)


def resolve_depth_m(est_depth: float | None, shot_type: str | None) -> float:
    if est_depth is not None and est_depth > 0:
        return float(est_depth)
    if shot_type and shot_type in DEFAULT_DEPTH_M:
        return DEFAULT_DEPTH_M[shot_type]
    return DEFAULT_DEPTH_M["medium"]


def screen_to_world_at_depth(
    cam_pos: Sequence[float],
    look_at: Sequence[float],
    screen_x: float,
    screen_y: float,
    focal_mm: float,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16.0 / 9.0,
    depth_m: float = 3.0,
) -> tuple[float, float, float]:
    """스크린 정규화 좌표(x, y in 0..1) → 카메라로부터 depth_m 떨어진 월드 점.

    - screen_x=0.5, screen_y=0.5 → 카메라 정면
    - 상단(y=0)은 카메라 up 방향
    """
    forward = _vec_norm(_vec_sub(look_at, cam_pos))
    if forward == (0.0, 0.0, 0.0):
        raise ValueError("look_at == cam_pos")

    # 카메라 right/up 기저. WORLD_UP과 forward가 평행이면 대체 up 사용.
    if abs(_vec_dot(forward, WORLD_UP)) > 0.9999:
        alt_up = (0.0, 1.0, 0.0)
        right = _vec_norm(_vec_cross(forward, alt_up))
    else:
        right = _vec_norm(_vec_cross(forward, WORLD_UP))
    up = _vec_norm(_vec_cross(right, forward))

    # NDC: [-1, 1]. y는 스크린이 아래로 증가하므로 반전.
    nx = (screen_x - 0.5) * 2.0
    ny = (0.5 - screen_y) * 2.0

    half_fov_h = atan((sensor_width_mm / 2.0) / focal_mm)
    half_fov_v = atan(tan(half_fov_h) / aspect_ratio)

    # 광선 방향 = forward + nx*tan(hh)*right + ny*tan(hv)*up
    d = _vec_add(
        _vec_add(forward, _vec_scale(right, nx * tan(half_fov_h))),
        _vec_scale(up, ny * tan(half_fov_v)),
    )
    d = _vec_norm(d)
    return _vec_add(cam_pos, _vec_scale(d, depth_m))


def pick_camera_reference_for_panel(
    panel_index: int,
    panel_count: int,
    camera_keyframes: list[dict],
) -> dict:
    """패널 → 대응 카메라 키프레임 매핑. MVP: 패널을 샷 타임라인에 균등 분할, 가장 가까운 키.

    ponytail: 나중에 panel_t_sec를 스키마에 추가하면 정확해짐.
    """
    if not camera_keyframes:
        raise ValueError("no camera keyframes")
    if panel_count <= 1:
        return camera_keyframes[-1]
    # 균등 분포 위치 (0..1)
    p_pos = panel_index / (panel_count - 1)
    t_min = camera_keyframes[0]["t_sec"]
    t_max = camera_keyframes[-1]["t_sec"]
    target_t = t_min + p_pos * (t_max - t_min)
    return min(camera_keyframes, key=lambda k: abs(k["t_sec"] - target_t))


ASPECT_RATIOS = {
    "16:9":   16.0 / 9.0,
    "9:16":    9.0 / 16.0,
    "1:1":     1.0,
    "4:3":     4.0 / 3.0,
    "2.39:1":  2.39,
}


def parse_aspect(s: str | None) -> float:
    if not s:
        return 16.0 / 9.0
    return ASPECT_RATIOS.get(s, 16.0 / 9.0)


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    # depth resolve
    assert resolve_depth_m(5.0, "close") == 5.0
    assert resolve_depth_m(None, "wide") == 10.0
    assert resolve_depth_m(None, None) == 3.0
    assert resolve_depth_m(0, "wide") == 10.0

    # 중앙 스크린 → 카메라 forward 방향으로 depth만큼
    p = screen_to_world_at_depth(
        cam_pos=(0, -10, 1.6),
        look_at=(0, 0, 1.6),
        screen_x=0.5, screen_y=0.5,
        focal_mm=50.0, sensor_width_mm=36.0,
        aspect_ratio=16/9, depth_m=5.0,
    )
    # forward = (0,1,0), 5m 전진 → (0, -5, 1.6)
    assert abs(p[0]) < 1e-6, p
    assert abs(p[1] - (-5.0)) < 1e-6, p
    assert abs(p[2] - 1.6) < 1e-6, p

    # 오른쪽 스크린 → +X 방향으로 옆으로 벌어짐
    p = screen_to_world_at_depth(
        cam_pos=(0, -10, 1.6),
        look_at=(0, 0, 1.6),
        screen_x=0.8, screen_y=0.5,
        focal_mm=50.0, aspect_ratio=16/9, depth_m=5.0,
    )
    assert p[0] > 0.5, f"x should shift +right: {p}"
    assert abs(p[2] - 1.6) < 0.01, p  # 세로는 그대로

    # 상단 스크린 → +Z (위)
    p = screen_to_world_at_depth(
        cam_pos=(0, -10, 1.6),
        look_at=(0, 0, 1.6),
        screen_x=0.5, screen_y=0.1,
        focal_mm=50.0, aspect_ratio=16/9, depth_m=5.0,
    )
    assert p[2] > 1.7, f"z should be higher: {p}"

    # 하단 스크린 → 아래로
    p = screen_to_world_at_depth(
        cam_pos=(0, -10, 1.6),
        look_at=(0, 0, 1.6),
        screen_x=0.5, screen_y=0.9,
        focal_mm=50.0, aspect_ratio=16/9, depth_m=5.0,
    )
    assert p[2] < 1.5, f"z should be lower: {p}"

    # 광각(24mm)이 망원(85mm)보다 같은 x_screen에서 더 넓게 벌어짐
    p_wide = screen_to_world_at_depth(
        (0, -5, 0), (0, 0, 0), 0.8, 0.5, focal_mm=24.0, depth_m=5.0)
    p_tele = screen_to_world_at_depth(
        (0, -5, 0), (0, 0, 0), 0.8, 0.5, focal_mm=85.0, depth_m=5.0)
    assert abs(p_wide[0]) > abs(p_tele[0]), (p_wide, p_tele)

    # 패널→키프레임 매핑
    keys = [{"t_sec": 0.0}, {"t_sec": 4.0}, {"t_sec": 8.0}]
    assert pick_camera_reference_for_panel(0, 2, keys)["t_sec"] == 0.0
    assert pick_camera_reference_for_panel(1, 2, keys)["t_sec"] == 8.0
    assert pick_camera_reference_for_panel(0, 3, keys)["t_sec"] == 0.0
    assert pick_camera_reference_for_panel(1, 3, keys)["t_sec"] == 4.0

    # aspect
    assert abs(parse_aspect("16:9") - 16/9) < 1e-6
    assert parse_aspect(None) == 16/9
    assert parse_aspect("unknown") == 16/9  # fallback

    print("placement.py: OK")


if __name__ == "__main__":
    _demo()
