"""blender-previz 스킬 대체 렌더러.

preview_adapter.py의 build_spec() 이 만드는 spec JSON을 읽어 EEVEE로 네온 프리뷰를
직접 렌더링한다. 원래는 외부 Claude 스킬(~/.claude/skills/blender-previz/scripts/previz.py)이
이 역할을 하도록 설계되어 있었으나, 그 스킬이 로컬에도 마켓플레이스에도 없어 동일한
spec 포맷을 소비하는 내장 대체 스크립트로 작성함.

spec 포맷: preview_adapter.py::build_spec() 참조.
  scene: {duration_sec, fps, resolution:[w,h], world_color:"#hex", min_distance}
  camera: {focal_mm, sensor_mm, hold_frames, keyframes:[{t,pos,look_at,easing,easing_curve?,hold?}]}
  subjects: [{id, shape, pos, rot_deg:[x,y,z], scale:[x,y,z], color:"#hex", final_role}]
  anchors:  [{id, shape, pos, scale:[x,y,z], color:"#hex", final_role}]

이 Blender 빌드는 image_settings.file_format='FFMPEG'를 지원하지 않아(라이선스 이슈로
빌드에서 제외됨) PNG 시퀀스로 렌더한 뒤 별도 설치된 ffmpeg로 인코딩한다.

용법 (bpy 필요, --demo만 예외):
  blender --background --python preview_render.py -- \\
      --spec out/s001_preview_spec.json --out out/s001_preview.mp4
  python preview_render.py --demo
"""

from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from math import radians
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "blender_previz"))


EMISSION_STRENGTH = 2.0

# spec의 scale은 blender-previz 스킬 프리미티브 크기를 전제로 계산돼 있다.
# 대체 렌더러는 proxy_library.create_prop의 프리미티브를 쓰는데 실제 크기가 달라서
# 그 비율만큼 보정해야 한다. cube/sphere/cylinder는 양쪽 다 1유닛이라 보정 대상이 아니다.
#
# 근거 (preview_adapter.py):
#   grid_plane : "스킬 prim_grid_plane 이 10x10 유닛" 주석 → (10, 10, -)
#   l_shape z  : L_SHAPE_UNIT_Z = 3.0 상수      → z 3.0
#   l_shape xy : HUMAN_XY_SCALE = 0.15 이 "30cm 폭 근사"라고 명시돼 있으므로
#                스킬 l_shape의 XY는 2유닛이어야 앞뒤가 맞는다 (0.15 x 2 = 0.30m).
#   그 외 소품  : preview_adapter가 scale_m(미터)를 그대로 싣는다 → 스킬 단위 1로 간주.
#                 cube/sphere/cylinder는 실제도 1유닛이라 보정이 1.0이 되지만,
#                 asymmetric_wedge는 실제 z가 0.8유닛이라 보정하지 않으면 20% 낮아진다.
SKILL_PRIMITIVE_UNITS = {
    "grid_plane":       (10.0, 10.0, 1.0),
    "l_shape":          (2.0, 2.0, 3.0),
    "asymmetric_wedge": (1.0, 1.0, 1.0),
}


def hex_to_rgba(hex_str: str) -> tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b, 1.0)


# ---- CLI -------------------------------------------------------------------

def _parse_argv() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(prog="preview_render")
    p.add_argument("--spec", required=True, help="preview_adapter.py가 만든 spec JSON")
    p.add_argument("--out", required=True, help="출력 MP4 경로")
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 실행 파일 (기본: PATH의 ffmpeg)")
    p.add_argument("--keep-frames", action="store_true", help="렌더된 PNG 시퀀스를 남겨둠")
    return p.parse_args(argv)


# ---- bpy 의존부 --------------------------------------------------------------

def _lazy_bpy():
    import bpy  # type: ignore
    return bpy


def _set_world_background(hex_color: str) -> None:
    bpy = _lazy_bpy()
    scene = bpy.context.scene
    world = bpy.data.worlds.new("previz_world") if not scene.world else scene.world
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = hex_to_rgba(hex_color)
    # Workbench는 world 대신 자체 배경 설정을 쓴다.
    shading = scene.display.shading
    shading.background_type = "VIEWPORT"
    shading.background_color = hex_to_rgba(hex_color)[:3]


# 조명 모드 트레이드오프 (Workbench):
#   "FLAT"   — 오브젝트 색을 그대로 출력. 스킬 규칙 2(불가능한 네온 색)를 100% 보존하지만
#              면별 음영이 없다. 깊이는 그림자·외곽선·캐비티가 담당한다. ← 기본값
#   "STUDIO" — 면마다 방향 음영이 생겨 형태/방향이 더 잘 읽히는 대신,
#              오브젝트 색에 조명이 곱해져 네온이 중간톤으로 가라앉는다.
# 규칙 2는 저장소가 명시한 제약이므로 기본은 FLAT. 방향 판독이 더 급하면 STUDIO로 바꾼다.
SHADING_LIGHT = "FLAT"


def _setup_workbench_shading() -> None:
    """Workbench + 오브젝트 색 + 그림자/외곽선/캐비티로 렌더한다.

    Emission만 쓰면 모든 면이 각도와 무관하게 같은 색이라 음영이 0이고, 3D인데도
    납작한 색면으로 보인다. Workbench의 color_type='OBJECT'는 오브젝트 색을 유지한 채
    그림자와 외곽선을 얹으므로, 네온 식별성을 지키면서 공간감을 되살릴 수 있다.
    (preview_composite.py가 같은 이유로 쓰는 조합.)
    """
    bpy = _lazy_bpy()
    shading = bpy.context.scene.display.shading
    shading.light = SHADING_LIGHT
    shading.color_type = "OBJECT"
    shading.show_shadows = True          # 접지·거리를 알려주는 가장 강한 단서
    shading.shadow_intensity = 0.2       # 기본 0.5는 색을 과하게 눌러 네온이 죽는다
    shading.show_specular_highlight = False  # 하이라이트가 네온 위에서 흰색으로 튄다
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    shading.show_object_outline = True
    shading.object_outline_color = (0.0, 0.0, 0.0)
    bpy.context.scene.display.viewport_aa = "FXAA"


def _make_emission_material(name: str, hex_color: str):
    bpy = _lazy_bpy()
    mat = bpy.data.materials.new(name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = hex_to_rgba(hex_color)
    emission.inputs["Strength"].default_value = EMISSION_STRENGTH
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def _local_size(obj) -> tuple[float, float, float]:
    """스케일 적용 전 메시 자체의 bounding box 크기. depsgraph 갱신에 의존하지 않는다."""
    verts = obj.data.vertices
    if not verts:
        return (0.0, 0.0, 0.0)
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def unit_fixup(shape: str, actual_size: tuple[float, float, float]) -> tuple[float, float, float]:
    """spec이 전제한 스킬 프리미티브 크기 ÷ 실제 프리미티브 크기. (순수 함수)

    실제 크기를 런타임에 재서 넘기므로 proxy_library의 프리미티브가 바뀌어도 자동으로 따라간다.
    두께가 0인 축(예: grid_plane의 z)은 보정하지 않는다.
    """
    assumed = SKILL_PRIMITIVE_UNITS.get(shape)
    if assumed is None:
        return (1.0, 1.0, 1.0)
    return tuple(
        (a / act) if act > 1e-9 else 1.0
        for a, act in zip(assumed, actual_size)
    )


def _place_item(item: dict) -> None:
    """create_prop()으로 도형 생성 후 spec의 pos/rot_deg/scale/color 적용."""
    from proxy_library import create_prop  # noqa: E402

    obj = create_prop(item["shape"], item["id"])
    obj.location = tuple(item["pos"])
    rot = item.get("rot_deg", [0.0, 0.0, 0.0])
    obj.rotation_euler = tuple(radians(float(d)) for d in rot)
    fixup = unit_fixup(item["shape"], _local_size(obj))
    obj.scale = tuple(s * f for s, f in zip(item["scale"], fixup))
    # Workbench는 obj.color를, EEVEE로 되돌릴 경우엔 머티리얼을 쓴다. 둘 다 채워둔다.
    obj.color = hex_to_rgba(item["color"])
    mat = _make_emission_material(item["id"], item["color"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _build_camera(spec: dict, fps: int) -> tuple[object, int]:
    """카메라 생성 + 키프레임 애니메이션. (cam_obj, max_frame) 반환."""
    bpy = _lazy_bpy()
    from camera_builder import (  # noqa: E402
        euler_from_look_at,
        _apply_easing_to_last,
        _set_last_interpolation,
        validate_easing,
    )

    cam_spec = spec["camera"]
    hold_frames = int(cam_spec.get("hold_frames", 6))

    for kf in cam_spec["keyframes"]:
        validate_easing(kf.get("easing", "LINEAR"), kf.get("easing_curve"))

    cam_data = bpy.data.cameras.new("previz_cam")
    cam_data.sensor_width = float(cam_spec["sensor_mm"])
    cam_data.lens = float(cam_spec["focal_mm"])
    cam_obj = bpy.data.objects.new("previz_cam_obj", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    max_frame = 0
    for kf in cam_spec["keyframes"]:
        frame = round(float(kf["t"]) * fps)
        eul = euler_from_look_at(kf["pos"], kf["look_at"], 0.0)
        cam_obj.location = tuple(kf["pos"])
        cam_obj.rotation_euler = eul
        cam_obj.keyframe_insert("location", frame=frame)
        cam_obj.keyframe_insert("rotation_euler", frame=frame)
        _apply_easing_to_last(cam_obj, kf.get("easing", "LINEAR"), kf.get("easing_curve"))
        max_frame = max(max_frame, frame)

        if kf.get("hold"):
            hold_frame = frame + hold_frames
            cam_obj.keyframe_insert("location", frame=hold_frame)
            cam_obj.keyframe_insert("rotation_euler", frame=hold_frame)
            _set_last_interpolation(cam_obj, "VECTOR")
            max_frame = max(max_frame, hold_frame)

    return cam_obj, max_frame


def _render_frames(spec: dict, frames_dir: Path, max_frame: int) -> None:
    bpy = _lazy_bpy()
    scene = bpy.context.scene
    frames_dir.mkdir(parents=True, exist_ok=True)
    for frame in range(0, max_frame + 1):
        scene.frame_set(frame)
        scene.render.filepath = str(frames_dir / f"frame_{frame:05d}.png")
        bpy.ops.render.render(write_still=True)
    print(f"[render] {max_frame + 1} frames -> {frames_dir}")


def _encode_mp4(frames_dir: Path, out_mp4: Path, fps: int, ffmpeg: str) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-framerate", str(fps),
        "-start_number", "0",
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    print("[ffmpeg]", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"ffmpeg exited {result.returncode}")


def main() -> int:
    args = _parse_argv()
    bpy = _lazy_bpy()
    from assembly import reset_scene  # noqa: E402

    # 절대경로로 강제 변환: Blender가 한글 등 비-ASCII cwd에서 상대경로를 "C:\" 루트 기준으로
    # 잘못 풀어버리는 버그가 있음(scene.render.filepath 등 bpy 경로 API 전반에서 관찰됨).
    spec_path = Path(args.spec).resolve()
    out_mp4 = Path(args.out).resolve()

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    scene_spec = spec["scene"]
    fps = int(scene_spec.get("fps", 24))

    reset_scene()

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    res = scene_spec.get("resolution", [1280, 720])
    scene.render.resolution_x, scene.render.resolution_y = int(res[0]), int(res[1])
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"

    # 스킬 규칙 2: "불가능한 네온 색". Blender 기본 뷰 트랜스폼(AgX)은 채도가 높은 색을
    # 필름처럼 눌러서 네온이 파스텔로 바랜다. 색 자체가 식별 수단인 프리뷰이므로 톤매핑을 끈다.
    for candidate in ("Standard", "Raw"):
        try:
            scene.view_settings.view_transform = candidate
            break
        except TypeError:
            continue
    else:
        print("[warn] Standard/Raw 뷰 트랜스폼 없음 — 네온 색이 바랠 수 있음", file=sys.stderr)

    _set_world_background(scene_spec.get("world_color", "#101010"))
    _setup_workbench_shading()

    cam_obj, max_frame = _build_camera(spec, fps)

    subjects = spec.get("subjects", [])
    anchors = spec.get("anchors", [])

    from camera_builder import check_min_distance  # noqa: E402
    kf_pos = [{"pos_world": kf["pos"]} for kf in spec["camera"]["keyframes"]]
    subject_positions = [s["pos"] for s in subjects]
    check_min_distance(kf_pos, subject_positions, float(scene_spec.get("min_distance", 0.4)))

    for item in subjects + anchors:
        _place_item(item)

    frames_dir = out_mp4.parent / f"{out_mp4.stem}_frames"
    _render_frames(spec, frames_dir, max_frame)
    _encode_mp4(frames_dir, out_mp4, fps, args.ffmpeg)

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    print(f"[done] preview mp4: {out_mp4}")
    return 0


# ---- 자체 검증 (bpy 불필요) --------------------------------------------------

def _demo():
    assert hex_to_rgba("#FF00FF") == (1.0, 0.0, 1.0, 1.0)
    r, g, b, a = hex_to_rgba("#39FF14")
    assert abs(r - 0x39 / 255.0) < 1e-6
    assert abs(g - 0xFF / 255.0) < 1e-6
    assert abs(b - 0x14 / 255.0) < 1e-6
    assert a == 1.0

    # 프리미티브 단위 보정: spec의 scale이 실제 미터로 환산되는지 검증.
    # proxy_library의 실제 프리미티브 크기를 그대로 넣어 확인한다.
    from proxy_library import l_shape_verts_faces  # noqa: E402

    zs = [v[2] for v in l_shape_verts_faces()[0]]
    l_h = max(zs) - min(zs)
    assert abs(l_h - 1.8) < 1e-9, f"l_shape 실제 높이가 바뀜: {l_h}"

    # 성인 1.75m: preview_adapter가 1.75/3.0=0.5833을 싣고, 보정 후 실제 1.75m가 되어야 함
    fx = unit_fixup("l_shape", (1.0, 1.0, l_h))
    assert abs((1.75 / 3.0) * fx[2] * l_h - 1.75) < 1e-9, (fx, "성인 키가 1.75m가 아님")
    # HUMAN_XY_SCALE=0.15가 주석대로 "30cm 폭"이 되어야 함 (6cm 각목 방지)
    assert abs(0.15 * fx[0] * 1.0 - 0.30) < 1e-9, (fx, "캐릭터 폭이 30cm가 아님")
    assert abs(0.15 * fx[1] * 1.0 - 0.30) < 1e-9, (fx, "캐릭터 깊이가 30cm가 아님")

    # 20m 바닥: adapter가 20/10=2.0을 싣고, 1x1 평면에 보정 후 20m가 되어야 함
    fx = unit_fixup("grid_plane", (1.0, 1.0, 0.0))
    assert abs(2.0 * fx[0] * 1.0 - 20.0) < 1e-9, (fx, "바닥이 20m가 아님")
    assert fx[2] == 1.0, f"두께 0인 축은 보정하지 않아야 함: {fx}"

    # 미터를 그대로 쓰는 도형은 보정 없음
    for shape in ("cube", "sphere", "cylinder"):
        assert unit_fixup(shape, (1.0, 1.0, 1.0)) == (1.0, 1.0, 1.0), shape

    # asymmetric_wedge: 실제 z가 0.8유닛이라 scale_m을 미터로 쓰려면 1/0.8 보정 필요
    from proxy_library import wedge_verts_faces  # noqa: E402

    wz = [v[2] for v in wedge_verts_faces()[0]]
    w_h = max(wz) - min(wz)
    assert abs(w_h - 0.8) < 1e-9, f"wedge 실제 높이가 바뀜: {w_h}"
    fx = unit_fixup("asymmetric_wedge", (1.0, 1.0, w_h))
    assert abs(1.7 * fx[2] * w_h - 1.7) < 1e-9, (fx, "지붕 높이가 scale_m과 다름")

    print("preview_render.py: OK")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        try:
            sys.exit(main())
        except SystemExit:
            raise
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)
