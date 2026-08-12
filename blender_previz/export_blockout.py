"""Seedance 2.5 White-Model Control 제출용 익스포트.

내보내는 것:
  - <shot_id>.fbx       카메라 애니메이션 포함 블록아웃 (권장 형식)
  - <shot_id>.obj       스태틱 스냅샷 (호환용 옵션)
  - <shot_id>_camera.json  프레임별 카메라 위치/회전/초점거리 베이크

지침:
  - 씬의 모든 mesh에 MatWhitePreviz 통일 적용 (Seedance가 화이트 모델로 인식하기 좋도록)
  - OBJ 익스포트는 Blender 4.x의 wm.obj_export가 기본, 구버전 폴백 시도

bpy 필요.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

WHITE_MAT_NAME = "MatWhitePreviz"
WHITE_MAT_COLOR = (0.85, 0.85, 0.85, 1.0)
WHITE_MAT_ROUGHNESS = 0.7


def _lazy_bpy():
    import bpy  # type: ignore
    return bpy


def get_or_create_white_material() -> Any:
    bpy = _lazy_bpy()
    mat = bpy.data.materials.get(WHITE_MAT_NAME)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(WHITE_MAT_NAME)
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = WHITE_MAT_COLOR
        # Roughness 소켓 이름은 4.x에서 그대로. 없으면 스킵.
        rough = principled.inputs.get("Roughness")
        if rough is not None:
            rough.default_value = WHITE_MAT_ROUGHNESS
    return mat


def apply_white_material_to_all_meshes() -> int:
    """씬의 모든 mesh 오브젝트에 화이트 재질 적용. 반환: 적용된 오브젝트 수."""
    bpy = _lazy_bpy()
    mat = get_or_create_white_material()
    n = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        n += 1
    return n


def export_fbx(path: str | Path) -> None:
    """카메라 애니메이션 + 메시 포함 FBX. Seedance R2V 업로드 기본 포맷."""
    bpy = _lazy_bpy()
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=False,
        apply_unit_scale=True,
        bake_space_transform=True,
        object_types={"MESH", "CAMERA", "EMPTY"},
        bake_anim=True,
        bake_anim_use_all_bones=False,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        path_mode="COPY",
        embed_textures=False,
    )


def export_obj(path: str | Path) -> str:
    """정지 스냅샷 OBJ. 4.x는 wm.obj_export, 그 외는 export_scene.obj 폴백.

    반환: 실제로 쓴 오퍼레이터 이름 (디버그용).
    """
    bpy = _lazy_bpy()
    path_s = str(path)
    if hasattr(bpy.ops.wm, "obj_export"):
        bpy.ops.wm.obj_export(filepath=path_s, export_selected_objects=False, export_animation=False)
        return "wm.obj_export"
    if hasattr(bpy.ops.export_scene, "obj"):
        bpy.ops.export_scene.obj(filepath=path_s, use_selection=False)
        return "export_scene.obj"
    raise RuntimeError("no OBJ exporter available in this Blender build")


def bake_camera_track(
    cam_obj: Any,
    start_frame: int,
    end_frame: int,
    fps: int,
) -> list[dict]:
    """프레임별 위치/회전/초점거리 스냅. 시뮬레이션 대비 절대 재현 가능."""
    bpy = _lazy_bpy()
    scene = bpy.context.scene
    prev = scene.frame_current
    rows = []
    for f in range(start_frame, end_frame + 1):
        scene.frame_set(f)
        loc = tuple(cam_obj.location)
        rot = tuple(cam_obj.rotation_euler)
        focal = float(cam_obj.data.lens)
        rows.append({
            "frame": f,
            "t_sec": f / fps,
            "location": loc,
            "rotation_euler_rad": rot,
            "focal_mm": focal,
        })
    scene.frame_set(prev)
    return rows


def export_camera_track_json(
    path: str | Path,
    cam_obj: Any,
    shot: dict,
    scene_meta: dict,
    aspect_ratio: float,
) -> None:
    import json
    fps = int(scene_meta.get("fps", 24))
    duration = float(shot["duration_sec"])
    end_frame = round(duration * fps)
    rows = bake_camera_track(cam_obj, 0, end_frame, fps)
    payload = {
        "shot_id": shot["shot_id"],
        "fps": fps,
        "sensor_width_mm": float(scene_meta.get("sensor_width_mm", 36.0)),
        "aspect_ratio": aspect_ratio,
        "duration_sec": duration,
        "frames": rows,
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def export_all(
    cam_obj: Any,
    shot: dict,
    scene_meta: dict,
    aspect_ratio: float,
    out_dir: str | Path,
) -> dict[str, str]:
    """세 종류 파일 모두 내보내기. 반환: {kind: path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sid = shot["shot_id"]

    apply_white_material_to_all_meshes()

    fbx_path = out_dir / f"{sid}.fbx"
    obj_path = out_dir / f"{sid}.obj"
    cam_json_path = out_dir / f"{sid}_camera.json"

    export_fbx(fbx_path)
    used_op = export_obj(obj_path)
    export_camera_track_json(cam_json_path, cam_obj, shot, scene_meta, aspect_ratio)

    return {
        "fbx": str(fbx_path),
        "obj": str(obj_path),
        "obj_operator": used_op,
        "camera_track": str(cam_json_path),
    }


# ---- 자체 검증 (bpy 없이 확인 가능한 부분만) --------------------------------

def _demo():
    assert WHITE_MAT_NAME == "MatWhitePreviz"
    assert 0.8 < WHITE_MAT_COLOR[0] < 0.9  # 순백 회피
    # 함수 존재 검증만 — 실행은 bpy 필요
    for fn in [get_or_create_white_material, apply_white_material_to_all_meshes,
               export_fbx, export_obj, bake_camera_track, export_camera_track_json, export_all]:
        assert callable(fn)
    print("export_blockout.py: OK (bpy-free portion)")


if __name__ == "__main__":
    _demo()
