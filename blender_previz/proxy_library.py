"""캐릭터 매니큰 append + 소품 프리미티브 생성.

입력 딕셔너리 형식 (스키마 관련 필드만):

  panel["characters_in_frame"][i] = {
    "character_id": str,               # 씬 로컬 유니크 id
    "kind": "adult" | "child" | "silhouette",
    "final_role": str,                 # Rule 3. 필수. Seedance 프롬프트로 치환될 대상
    "transform_world": {
      "position": [x, y, z],           # meters
      "yaw_deg": float,                # +Z 회전, 정면 = -Y 기준
    },
  }

  panel["props_in_frame"][i] = {
    "name": str,
    "shape": "cube"|"sphere"|"cylinder"|"asymmetric_wedge"|"l_shape"|"grid_plane",
    "final_role": str,                 # Rule 3. 필수
    "transform_world": {
      "position": [x, y, z],
      "yaw_deg": float,
      "scale": [x, y, z],              # meters (구/실린더는 반지름 = scale[0])
    },
  }

블렌더 5.x bpy 필요. 순수 함수는 bpy 없이 테스트됨(하단 __main__).
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

# blender-previz 스킬의 shape 카탈로그. 이 6종만 허용.
ALLOWED_PROP_SHAPES = {
    "cube", "sphere", "cylinder",
    "asymmetric_wedge", "l_shape", "grid_plane",
}

MANNEQUIN_COLLECTION = {
    "adult":       "ProxyAdultMannequin",
    "child":       "ProxyChildMannequin",
    "silhouette":  "ProxyGenericSilhouette",
}


# ---- 순수부 (bpy 불필요, 테스트 가능) --------------------------------------

def validate_final_role(item: dict, kind_hint: str) -> None:
    """Rule 3. final_role 없으면 파이프라인 abort."""
    role = item.get("final_role")
    if not role or not isinstance(role, str) or not role.strip():
        raise ValueError(
            f"V5: {kind_hint} missing 'final_role' — "
            f"프리비즈에 있는 오브젝트는 반드시 최종 치환 대상을 명시해야 함. item={item!r}"
        )


def validate_prop_shape(shape: str) -> None:
    if shape not in ALLOWED_PROP_SHAPES:
        raise ValueError(
            f"V1: prop shape '{shape}' not in allowed catalog {sorted(ALLOWED_PROP_SHAPES)}"
        )


def wedge_verts_faces() -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """비대칭 쐐기 — 회전 판독용. 앞은 뾰족, 뒤는 넓음, 상하 다름."""
    v = [
        (-0.5, -0.5, 0.0),  # 0 back-left-bottom
        ( 0.5, -0.5, 0.0),  # 1 back-right-bottom
        ( 0.5,  0.5, 0.0),  # 2 back-right-top(앞쪽으로 갈수록 좁음)
        (-0.5,  0.5, 0.0),
        (-0.2, -0.5, 0.8),  # 4 top-back-left  (상단은 뒤로 치우침)
        ( 0.2, -0.5, 0.8),
        ( 0.0,  0.4, 0.4),  # 6 front-tip
    ]
    f = [
        (0, 1, 2, 3),        # bottom
        (0, 1, 5, 4),        # back
        (1, 2, 6, 5),        # right
        (3, 0, 4),           # left-lower
        (4, 5, 6),           # top-front
        (2, 3, 6),           # front-top-triangle-ish
    ]
    return v, f


def l_shape_verts_faces() -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    """세로로 서는 L. 인체·의자 근사. Base = 1x1x0.2, Riser = 0.4x1x1.6."""
    v = [
        # base slab
        (-0.5, -0.5, 0.0), ( 0.5, -0.5, 0.0), ( 0.5,  0.5, 0.0), (-0.5,  0.5, 0.0),
        (-0.5, -0.5, 0.2), ( 0.5, -0.5, 0.2), ( 0.5,  0.5, 0.2), (-0.5,  0.5, 0.2),
        # riser at back
        (-0.2,  0.1, 0.2), ( 0.2,  0.1, 0.2), ( 0.2,  0.5, 0.2), (-0.2,  0.5, 0.2),
        (-0.2,  0.1, 1.8), ( 0.2,  0.1, 1.8), ( 0.2,  0.5, 1.8), (-0.2,  0.5, 1.8),
    ]
    f = [
        (0, 1, 2, 3), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        (8, 9, 10, 11), (12, 13, 14, 15),
        (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15),
    ]
    return v, f


# ---- bpy 의존부 -----------------------------------------------------------

def _lazy_bpy():
    import bpy  # type: ignore
    return bpy


def append_mannequin(blend_path: str | Path, kind: str) -> Any:
    """proxy_library.blend의 매니큰 collection에서 mesh를 복제해 씬에 링크.

    같은 kind(예: adult)를 여러 캐릭터가 공유해도 씬 링크 충돌 안 나게, collection 자체는
    데이터로만 로드하고 오브젝트를 매번 새로 복제. mesh는 각 캐릭터마다 독립 복제
    (Seedance FBX 익스포트 시 인스턴스 공유가 오도되지 않게).
    """
    bpy = _lazy_bpy()
    coll_name = MANNEQUIN_COLLECTION.get(kind)
    if coll_name is None:
        raise ValueError(f"unknown mannequin kind: {kind!r}")

    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
            if coll_name not in data_from.collections:
                raise RuntimeError(
                    f"'{coll_name}' collection not in {blend_path}. "
                    f"proxy_library.blend 스펙 참조."
                )
            data_to.collections = [coll_name]
        coll = bpy.data.collections[coll_name]

    src = next(o for o in coll.objects if o.type == "MESH")
    new_obj = src.copy()
    new_obj.data = src.data.copy()
    bpy.context.scene.collection.objects.link(new_obj)
    return new_obj


def create_prop(shape: str, name: str) -> Any:
    """스킬 카탈로그의 shape로 mesh 오브젝트 생성. 위치는 원점, 트랜스폼은 뒤에서 적용."""
    validate_prop_shape(shape)
    bpy = _lazy_bpy()

    if shape == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, 0, 0))
    elif shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1.0, location=(0, 0, 0))
    elif shape == "grid_plane":
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, 0))
    elif shape == "asymmetric_wedge":
        v, f = wedge_verts_faces()
        _build_mesh(name, v, f)
        return bpy.context.object
    elif shape == "l_shape":
        v, f = l_shape_verts_faces()
        _build_mesh(name, v, f)
        return bpy.context.object

    obj = bpy.context.object
    obj.name = name
    return obj


def _build_mesh(name: str, verts: list, faces: list) -> Any:
    bpy = _lazy_bpy()
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    return obj


def apply_transform(obj: Any, position: tuple, yaw_deg: float, scale: tuple | None = None) -> None:
    """월드 트랜스폼을 오브젝트에 반영. yaw는 +Z 축 회전."""
    from math import radians
    obj.location = tuple(position)
    obj.rotation_euler = (0.0, 0.0, radians(yaw_deg))
    if scale is not None:
        obj.scale = tuple(scale)


def stamp_final_role(obj: Any, final_role: str, item_kind: str) -> None:
    """Rule 3. 프리뷰 렌더 스크립트와 Seedance 프롬프트 빌더가 여기서 읽음."""
    obj["final_role"] = final_role
    obj["item_kind"] = item_kind


def place_character(blend_path: str | Path, char: dict) -> Any:
    validate_final_role(char, "character")
    obj = append_mannequin(blend_path, char["kind"])
    obj.name = char["character_id"]
    t = char["transform_world"]
    apply_transform(obj, t["position"], t.get("yaw_deg", 0.0))
    stamp_final_role(obj, char["final_role"], "character")
    return obj


def place_prop(prop: dict) -> Any:
    validate_final_role(prop, "prop")
    obj = create_prop(prop["shape"], prop["name"])
    t = prop["transform_world"]
    apply_transform(obj, t["position"], t.get("yaw_deg", 0.0), t.get("scale", (1, 1, 1)))
    stamp_final_role(obj, prop["final_role"], "prop")
    return obj


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    # 순수 함수만 검증. bpy 있으면 별도 통합 테스트에서 확인.
    assert ALLOWED_PROP_SHAPES == {
        "cube", "sphere", "cylinder", "asymmetric_wedge", "l_shape", "grid_plane"
    }

    validate_prop_shape("cube")
    try:
        validate_prop_shape("chair")
    except ValueError as e:
        assert "not in allowed catalog" in str(e)
    else:
        raise AssertionError("chair should have been rejected")

    validate_final_role({"final_role": "young_woman_in_red_dress"}, "character")
    for bad in [{}, {"final_role": ""}, {"final_role": None}]:
        try:
            validate_final_role(bad, "character")
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad final_role should have been rejected: {bad}")

    v, f = wedge_verts_faces()
    assert len(v) == 7 and len(f) >= 5
    # 상단이 뒤로 치우친 비대칭
    assert v[4][1] < 0 and v[6][1] > 0, "wedge should be asymmetric on Y"

    v, f = l_shape_verts_faces()
    assert len(v) == 16
    # riser는 뒤쪽(Y>0)에 배치되어야 함
    riser_ys = [v[i][1] for i in (8, 9, 10, 11, 12, 13, 14, 15)]
    assert min(riser_ys) >= 0.1

    print("proxy_library.py: OK")


if __name__ == "__main__":
    _demo()
