"""샷별 카메라 생성 + 키프레임 애니메이션.

Focal 우선순위 (context 문서 결정):
  1. DA3 fov_deg   (estimated_pose.fov_deg, confidence >= threshold)
  2. focal_length_mm (VLM 추정)
  3. shot_type 휴리스틱 폴백

blender-previz 스킬 규약 반영:
  - easing 화이트리스트만 허용, BACK/BOUNCE/ELASTIC abort
  - Track-To 컨스트레인트 금지 → rotation_euler를 look_at으로 매 키 직접 계산
  - min_distance 0.4m 위반 시 abort
  - hold: true 인 키는 5프레임 뒤 VECTOR 홀드 자동 삽입

입력 형식:
  shot["camera_keyframes"] = [
    {
      "t_sec": float,
      "pos_world": [x, y, z],
      "look_at_world": [x, y, z],
      "easing": "LINEAR"|"EASE_IN"|"EASE_OUT"|"EASE_IN_OUT",
      "easing_curve": "SINE"|"CUBIC"|"BEZIER",  # optional
      "hold": bool,
      "dutch_tilt_deg": float,                  # roll
      # focal 지시(우선순위 순)
      "fov_deg": float | None,           # DA3 결과
      "fov_confidence": float | None,    # 0..1
      "focal_length_mm": float | None,   # VLM
      "shot_type": str | None,           # 최종 폴백
    }, ...
  ]

  scene_meta = { "fps": int, "sensor_width_mm": float, "min_distance_m": float,
                 "fov_confidence_threshold": float }
"""

from __future__ import annotations
from math import atan, degrees, radians, tan, sqrt
from typing import Any, Sequence

ALLOWED_EASING = {"LINEAR", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"}
BLACKLIST_EASING = {"BACK", "BOUNCE", "ELASTIC"}
ALLOWED_CURVES = {"SINE", "CUBIC", "BEZIER"}

# 스킬 references/research.md 표에 맞춘 shot_type → focal 폴백
SHOT_TYPE_FOCAL_MM = {
    "extreme_wide":  24.0,
    "wide":          28.0,
    "medium_wide":   35.0,
    "medium":        50.0,
    "medium_close":  70.0,
    "close":         85.0,
    "extreme_close": 100.0,
}

DEFAULT_SENSOR_WIDTH_MM = 36.0     # 풀프레임 기준. Blender 카메라 sensor_width 세팅과 일치시킬 것
DEFAULT_MIN_DISTANCE_M = 0.4
DEFAULT_FOV_CONF_THRESHOLD = 0.3
HOLD_FRAMES = 6                    # 스킬 규약 5-8프레임 중간값


# ---- 순수부 --------------------------------------------------------------

def validate_easing(easing: str, curve: str | None) -> None:
    if easing in BLACKLIST_EASING:
        raise ValueError(f"V2: easing '{easing}' blacklisted (오버슛/진동 금지)")
    if easing not in ALLOWED_EASING:
        raise ValueError(f"V2: easing '{easing}' not in {sorted(ALLOWED_EASING)}")
    if curve is not None and curve not in ALLOWED_CURVES:
        raise ValueError(f"V2: easing_curve '{curve}' not in {sorted(ALLOWED_CURVES)}")


def fov_to_focal_mm(fov_deg: float, sensor_width_mm: float = DEFAULT_SENSOR_WIDTH_MM) -> float:
    """수평 FOV → 초점거리. f = (S/2) / tan(fov/2)."""
    if fov_deg <= 0 or fov_deg >= 180:
        raise ValueError(f"fov_deg out of range: {fov_deg}")
    return (sensor_width_mm / 2.0) / tan(radians(fov_deg) / 2.0)


def resolve_focal_mm(
    kf: dict,
    sensor_width_mm: float = DEFAULT_SENSOR_WIDTH_MM,
    fov_confidence_threshold: float = DEFAULT_FOV_CONF_THRESHOLD,
) -> tuple[float, str]:
    """(focal_mm, source) 반환. source는 로그용."""
    fov = kf.get("fov_deg")
    conf = kf.get("fov_confidence") or 0.0
    if fov and conf >= fov_confidence_threshold:
        return fov_to_focal_mm(float(fov), sensor_width_mm), f"da3(conf={conf:.2f})"

    fl = kf.get("focal_length_mm")
    if fl:
        return float(fl), "vlm"

    st = kf.get("shot_type")
    if st and st in SHOT_TYPE_FOCAL_MM:
        return SHOT_TYPE_FOCAL_MM[st], f"heuristic({st})"

    # 최후 폴백. medium.
    return SHOT_TYPE_FOCAL_MM["medium"], "default(medium)"


def euler_from_look_at(
    cam_pos: Sequence[float],
    target: Sequence[float],
    roll_deg: float = 0.0,
) -> tuple[float, float, float]:
    """블렌더 카메라는 로컬 -Z 방향을 바라봄. 월드 방향 벡터로부터 XYZ Euler 계산.

    roll은 카메라 로컬 Z(=바라보는 축의 반대)에 대한 회전, 즉 Dutch tilt.
    간단한 유도로 충분한 정확도 — 짐벌락 회피는 룩업이 정수직인 극단 케이스만 문제라 상관없음.
    """
    dx = target[0] - cam_pos[0]
    dy = target[1] - cam_pos[1]
    dz = target[2] - cam_pos[2]
    dist_xy = sqrt(dx * dx + dy * dy)

    # 카메라 기본이 -Z. 타겟 방향 벡터를 이 축에 정렬.
    # rot_x: 피치, rot_z: 요, rot_y: 롤(Dutch)
    yaw = atan(dx / dy) if dy != 0 else (radians(90) if dx > 0 else radians(-90))
    if dy > 0:  # 카메라 뒤쪽 방향을 보는 경우 보정
        yaw += radians(180)
    pitch = -atan(dz / dist_xy) if dist_xy > 1e-6 else (radians(-90) if dz > 0 else radians(90))
    # 블렌더 XYZ Euler: rot_x(pitch about X), rot_y(roll), rot_z(yaw about Z)
    return (radians(90) + pitch, radians(roll_deg), yaw)


def point_to_segment_min_distance(
    p: Sequence[float],
    a: Sequence[float],
    b: Sequence[float],
) -> float:
    """점 p에서 선분 ab까지 최단거리. 카메라 경로 vs 정지 오브젝트 거리 검증용."""
    ax, ay, az = a
    bx, by, bz = b
    ex, ey, ez = bx - ax, by - ay, bz - az
    seg_len2 = ex * ex + ey * ey + ez * ez
    if seg_len2 < 1e-12:
        dx, dy, dz = p[0] - ax, p[1] - ay, p[2] - az
        return sqrt(dx * dx + dy * dy + dz * dz)
    t = ((p[0] - ax) * ex + (p[1] - ay) * ey + (p[2] - az) * ez) / seg_len2
    t = max(0.0, min(1.0, t))
    qx, qy, qz = ax + t * ex, ay + t * ey, az + t * ez
    dx, dy, dz = p[0] - qx, p[1] - qy, p[2] - qz
    return sqrt(dx * dx + dy * dy + dz * dz)


def check_min_distance(
    keyframes: list[dict],
    subject_positions: list[Sequence[float]],
    min_distance_m: float = DEFAULT_MIN_DISTANCE_M,
) -> None:
    """카메라 경로(연속된 키 사이 선분) 각 구간이 어떤 피사체와 min_distance보다 가까우면 abort."""
    if not subject_positions:
        return
    for i in range(len(keyframes) - 1):
        a = keyframes[i]["pos_world"]
        b = keyframes[i + 1]["pos_world"]
        for si, sp in enumerate(subject_positions):
            d = point_to_segment_min_distance(sp, a, b)
            if d < min_distance_m:
                raise ValueError(
                    f"V3: camera path segment {i}->{i+1} passes {d:.2f}m from subject#{si} "
                    f"(min={min_distance_m}m). 스킬 §3.3 위반. "
                    f"조치: 피사체 스케일↓, 렌즈 광각화, 또는 min_distance 재검토."
                )


# ---- bpy 의존부 ----------------------------------------------------------

def _lazy_bpy():
    import bpy  # type: ignore
    return bpy


def build_camera(
    shot: dict,
    scene_meta: dict,
    subject_positions: list[Sequence[float]] | None = None,
) -> Any:
    """카메라 오브젝트 생성 + 키프레임 삽입 + focal 애니메이션.

    Return: 생성된 bpy 카메라 오브젝트.
    """
    bpy = _lazy_bpy()

    fps = int(scene_meta.get("fps", 24))
    sensor_w = float(scene_meta.get("sensor_width_mm", DEFAULT_SENSOR_WIDTH_MM))
    min_d = float(scene_meta.get("min_distance_m", DEFAULT_MIN_DISTANCE_M))
    fov_thr = float(scene_meta.get("fov_confidence_threshold", DEFAULT_FOV_CONF_THRESHOLD))

    keys = shot["camera_keyframes"]
    if len(keys) < 1:
        raise ValueError("V4: shot has no camera keyframes")

    # 사전 검증
    for kf in keys:
        validate_easing(kf.get("easing", "LINEAR"), kf.get("easing_curve"))
    check_min_distance(keys, list(subject_positions or []), min_d)

    cam_data = bpy.data.cameras.new(shot.get("shot_id", "cam"))
    cam_data.sensor_width = sensor_w
    cam_obj = bpy.data.objects.new(shot.get("shot_id", "cam") + "_obj", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    for kf in keys:
        frame = round(kf["t_sec"] * fps)
        focal_mm, source = resolve_focal_mm(kf, sensor_w, fov_thr)
        eul = euler_from_look_at(
            kf["pos_world"], kf["look_at_world"], kf.get("dutch_tilt_deg", 0.0)
        )

        cam_data.lens = focal_mm
        cam_obj.location = kf["pos_world"]
        cam_obj.rotation_euler = eul

        cam_data.keyframe_insert("lens", frame=frame)
        cam_obj.keyframe_insert("location", frame=frame)
        cam_obj.keyframe_insert("rotation_euler", frame=frame)

        _apply_easing_to_last(cam_obj, kf.get("easing", "LINEAR"), kf.get("easing_curve"))

        if kf.get("hold"):
            hold_frame = frame + HOLD_FRAMES
            cam_data.keyframe_insert("lens", frame=hold_frame)
            cam_obj.keyframe_insert("location", frame=hold_frame)
            cam_obj.keyframe_insert("rotation_euler", frame=hold_frame)
            _set_last_interpolation(cam_obj, "VECTOR")

        cam_obj["focal_source"] = source  # 디버그용 커스텀 프로퍼티

    return cam_obj


def _get_action_fcurves(action: Any) -> list:
    """Blender 4.4+ 슬롯 기반 Action / 구버전 통합 접근. 스킬 previz.py 참조."""
    if action is None:
        return []
    if hasattr(action, "fcurves") and len(action.fcurves) > 0:
        return list(action.fcurves)
    fcurves = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", []):
                fcurves.extend(cb.fcurves)
    return fcurves


def _apply_easing_to_last(obj: Any, easing: str, curve: str | None) -> None:
    """마지막에 삽입된 키프레임들의 interpolation·easing 세팅.

    Blender FCurve API: keyframe_point.interpolation은 CONSTANT|LINEAR|BEZIER|...
    ease 인/아웃/인아웃은 easing 필드. easing_curve는 interpolation type에 매핑.
    """
    curve_map = {"SINE": "SINE", "CUBIC": "CUBIC", "BEZIER": "BEZIER"}
    interp = curve_map.get(curve or "BEZIER", "BEZIER") if easing != "LINEAR" else "LINEAR"
    ease_map = {
        "LINEAR":     "AUTO",
        "EASE_IN":    "EASE_IN",
        "EASE_OUT":   "EASE_OUT",
        "EASE_IN_OUT":"EASE_IN_OUT",
    }
    ease = ease_map[easing]

    action = obj.animation_data.action if obj.animation_data else None
    for fc in _get_action_fcurves(action):
        if not fc.keyframe_points:
            continue
        kp = fc.keyframe_points[-1]
        kp.interpolation = interp
        if hasattr(kp, "easing"):
            kp.easing = ease


def _set_last_interpolation(obj: Any, interp: str) -> None:
    """VECTOR는 keyframe interpolation이 아니라 handle_type. hold 유지용으로 이 값이 들어오면
    양쪽 handle을 VECTOR로 (스킬 previz.py 방식과 정렬). 그 외 값은 interpolation에 세팅."""
    action = obj.animation_data.action if obj.animation_data else None
    for fc in _get_action_fcurves(action):
        if not fc.keyframe_points:
            continue
        kp = fc.keyframe_points[-1]
        if interp == "VECTOR":
            kp.handle_left_type = "VECTOR"
            kp.handle_right_type = "VECTOR"
        else:
            kp.interpolation = interp


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    # easing 화이트리스트
    validate_easing("EASE_OUT", "CUBIC")
    for bad in ["BACK", "BOUNCE", "ELASTIC"]:
        try:
            validate_easing(bad, None)
        except ValueError as e:
            assert "blacklisted" in str(e)
        else:
            raise AssertionError(f"{bad} should abort")

    # FOV ↔ focal 역변환
    focal = fov_to_focal_mm(50.0, 36.0)
    assert 38.0 < focal < 39.0, focal   # 50도 @36mm → ~38.6mm
    # 라운드 트립: 50mm는 대략 39.6도
    from math import atan2  # noqa
    fov_from_50 = 2 * degrees(atan(18.0 / 50.0))
    assert 39.0 < fov_from_50 < 40.0, fov_from_50

    # focal 우선순위: DA3 > VLM > shot_type > default
    r, s = resolve_focal_mm({"fov_deg": 60.0, "fov_confidence": 0.9,
                             "focal_length_mm": 100.0, "shot_type": "close"})
    assert s.startswith("da3"), s
    r, s = resolve_focal_mm({"fov_deg": 60.0, "fov_confidence": 0.1,
                             "focal_length_mm": 100.0, "shot_type": "close"})
    assert s == "vlm" and r == 100.0
    r, s = resolve_focal_mm({"shot_type": "wide"})
    assert s.startswith("heuristic") and r == 28.0
    r, s = resolve_focal_mm({})
    assert s.startswith("default") and r == 50.0

    # look_at: 원점→(-Y) 바라봄 = 회전 없어야 함(pitch=90도, yaw=0, roll=0 in blender convention)
    eul = euler_from_look_at((0, 5, 0), (0, 0, 0))
    # pitch = 90도 근처(radians(90) + 0)
    assert abs(eul[0] - radians(90)) < 1e-6, eul
    assert abs(eul[1]) < 1e-6

    # min_distance: 정면 가까이 지나가면 abort
    keys = [
        {"pos_world": [0, 2, 0], "easing": "LINEAR"},
        {"pos_world": [0, 0.1, 0], "easing": "LINEAR"},
    ]
    try:
        check_min_distance(keys, [(0, 0, 0)], 0.4)
    except ValueError as e:
        assert "V3" in str(e)
    else:
        raise AssertionError("should have aborted on min_distance")
    check_min_distance(keys, [(5, 5, 5)], 0.4)  # 멀면 통과

    print("camera_builder.py: OK")


if __name__ == "__main__":
    _demo()
