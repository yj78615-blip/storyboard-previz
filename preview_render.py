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


def _place_item(item: dict) -> None:
    """create_prop()으로 도형 생성 후 spec의 pos/rot_deg/scale/color 그대로 적용."""
    from proxy_library import create_prop  # noqa: E402

    obj = create_prop(item["shape"], item["id"])
    obj.location = tuple(item["pos"])
    rot = item.get("rot_deg", [0.0, 0.0, 0.0])
    obj.rotation_euler = tuple(radians(float(d)) for d in rot)
    obj.scale = tuple(item["scale"])
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
    scene.render.engine = "BLENDER_EEVEE"
    res = scene_spec.get("resolution", [1280, 720])
    scene.render.resolution_x, scene.render.resolution_y = int(res[0]), int(res[1])
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"

    _set_world_background(scene_spec.get("world_color", "#101010"))

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
