"""샷 오케스트레이션.

책임:
  1. 씬 초기화 (기존 오브젝트 삭제)
  2. 이 샷에 참여하는 캐릭터/소품을 마지막 등장 패널 기준으로 배치
  3. camera_builder로 카메라 생성 + 애니메이션
  4. 서브젝트 월드좌표 목록을 camera_builder에 넘겨 min_distance 검증

MVP 한계 (context 문서 알려진 한계 4번):
  - 한 샷 내 캐릭터 이동(연기) 미처리. 각 캐릭터는 "마지막 등장 패널"의 트랜스폼에 정지.
  - 소품도 동일. 애니메이션 필요 시 v2.

입력: scene(dict, storyboard_scene_schema.json 인스턴스), shot_id, blend_path.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Sequence

from placement import (
    parse_aspect,
    pick_camera_reference_for_panel,
    resolve_depth_m,
    screen_to_world_at_depth,
)
from camera_builder import (
    DEFAULT_SENSOR_WIDTH_MM,
    build_camera,
    resolve_focal_mm,
)
from proxy_library import place_character, place_prop


def _lazy_bpy():
    import bpy  # type: ignore
    return bpy


def reset_scene() -> None:
    """카메라/메시/라이트 모두 삭제. 재실행 안전성."""
    bpy = _lazy_bpy()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # 남은 데이터 블록도 정리 (append로 쌓인 것 포함)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    for c in list(bpy.data.cameras):
        bpy.data.cameras.remove(c)


def _index_by_id(items: list[dict], key: str) -> dict[str, dict]:
    return {it[key]: it for it in items}


def _last_appearance_index(
    panels: list[dict],
    group_key: str,
    item_id_key: str,
) -> dict[str, tuple[int, dict]]:
    """각 id별로 (마지막 등장 패널 인덱스, 그 패널의 항목 dict)."""
    last: dict[str, tuple[int, dict]] = {}
    for pi, panel in enumerate(panels):
        for item in panel.get(group_key, []):
            last[item[item_id_key]] = (pi, item)
    return last


def _prop_key(prop_item: dict) -> str:
    return prop_item["name"]


def _last_prop_appearances(panels: list[dict]) -> dict[str, tuple[int, dict]]:
    last: dict[str, tuple[int, dict]] = {}
    for pi, panel in enumerate(panels):
        for item in panel.get("props_in_frame", []):
            last[_prop_key(item)] = (pi, item)
    return last


def _resolve_world_pos_from_panel(
    panel: dict,
    item: dict,
    camera_keyframes: list[dict],
    panel_index: int,
    panel_count: int,
    scene_meta: dict,
    aspect_ratio: float,
) -> tuple[float, float, float]:
    """스키마의 screen_position + estimated_transform.depth_m → 월드 좌표."""
    kf = pick_camera_reference_for_panel(panel_index, panel_count, camera_keyframes)
    # 이 키프레임의 focal 결정 (DA3 > VLM > shot_type > default)
    # 패널의 camera_state를 kf에 병합해서 resolve — 패널 focal 정보를 우선 활용.
    merged = dict(kf)
    cs = panel.get("camera_state", {})
    if cs.get("focal_length_mm") is not None:
        merged.setdefault("focal_length_mm", cs["focal_length_mm"])
    est = cs.get("estimated_pose") or {}
    if est.get("fov_deg") is not None:
        merged.setdefault("fov_deg", est["fov_deg"])
        merged.setdefault("fov_confidence", est.get("confidence"))
    merged.setdefault("shot_type", cs.get("shot_type"))

    focal_mm, _src = resolve_focal_mm(
        merged,
        sensor_width_mm=float(scene_meta.get("sensor_width_mm", DEFAULT_SENSOR_WIDTH_MM)),
        fov_confidence_threshold=float(scene_meta.get("fov_confidence_threshold", 0.3)),
    )

    depth = resolve_depth_m(
        (item.get("estimated_transform") or {}).get("depth_m"),
        cs.get("shot_type"),
    )
    sp = item["screen_position"]
    return screen_to_world_at_depth(
        cam_pos=kf["pos_world"],
        look_at=kf["look_at_world"],
        screen_x=sp["x"], screen_y=sp["y"],
        focal_mm=focal_mm,
        sensor_width_mm=float(scene_meta.get("sensor_width_mm", DEFAULT_SENSOR_WIDTH_MM)),
        aspect_ratio=aspect_ratio,
        depth_m=depth,
    )


def build_shot(
    scene: dict,
    shot_id: str,
    blend_path: str | Path,
) -> dict:
    """샷 하나 씬에 조립. Return: {subject_positions, cam_obj_name, placed}."""
    shots_by_id = _index_by_id(scene["shots"], "shot_id")
    if shot_id not in shots_by_id:
        raise KeyError(f"shot_id '{shot_id}' not in scene.shots")
    shot = shots_by_id[shot_id]
    panels_by_id = _index_by_id(scene["panels"], "panel_id")
    panels = [panels_by_id[pid] for pid in shot["panel_ids"]]
    if not panels:
        raise ValueError(f"shot {shot_id} has no valid panels")

    char_reg = _index_by_id(scene["characters"], "character_id")
    scene_meta = scene["scene_meta"]
    aspect = parse_aspect(scene.get("story_meta", {}).get("aspect_ratio"))
    keys = shot["camera_keyframes"]

    reset_scene()

    subject_positions: list[tuple[float, float, float]] = []
    placed = {"characters": [], "props": []}

    # 캐릭터: 마지막 등장 패널 기준
    for cid, (pi, item) in _last_appearance_index(panels, "characters_in_frame", "character_id").items():
        panel = panels[pi]
        pos = _resolve_world_pos_from_panel(panel, item, keys, pi, len(panels), scene_meta, aspect)
        kind = char_reg[cid]["kind"]
        yaw = (item.get("estimated_transform") or {}).get("yaw_deg", 0.0)
        char_payload = {
            "character_id": cid,
            "kind": kind,
            "final_role": item["final_role"],
            "transform_world": {"position": pos, "yaw_deg": yaw},
        }
        obj = place_character(str(blend_path), char_payload)
        obj["pose_category"] = item.get("pose_category", "standing")
        subject_positions.append(pos)
        placed["characters"].append(cid)

    # 소품
    for _pname, (pi, item) in _last_prop_appearances(panels).items():
        panel = panels[pi]
        pos = _resolve_world_pos_from_panel(panel, item, keys, pi, len(panels), scene_meta, aspect)
        et = item.get("estimated_transform") or {}
        prop_payload = {
            "name": item["name"],
            "shape": item["shape"],
            "final_role": item["final_role"],
            "transform_world": {
                "position": pos,
                "yaw_deg": et.get("yaw_deg", 0.0),
                "scale": et.get("scale_m", [1, 1, 1]),
            },
        }
        place_prop(prop_payload)
        subject_positions.append(pos)
        placed["props"].append(item["name"])

    # 카메라 (마지막에 만들어 subject_positions로 min_distance 검증)
    cam = build_camera(shot, scene_meta, subject_positions)

    return {
        "shot_id": shot_id,
        "cam_obj_name": cam.name,
        "subject_positions": subject_positions,
        "placed": placed,
    }


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    """bpy 없이 검증 가능한 부분: 인덱싱 로직 + 월드좌표 계산."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    scene = json.loads((root / "storyboard_scene_example.json").read_text(encoding="utf-8"))

    # 인덱싱
    idx = _index_by_id(scene["shots"], "shot_id")
    assert "s001" in idx
    idx = _index_by_id(scene["characters"], "character_id")
    assert set(idx) == {"yuna", "minsu"}

    # 마지막 등장 패널: yuna는 p001, p002 모두 등장 → p002 (마지막)
    last = _last_appearance_index(scene["panels"], "characters_in_frame", "character_id")
    assert last["yuna"][0] == 1, last["yuna"][0]
    assert last["minsu"][0] == 1
    assert last["yuna"][1]["final_role"].startswith("young woman")
    # p002는 depth=3.0 → 그 값이 뽑혀야 함
    assert last["yuna"][1]["estimated_transform"]["depth_m"] == 3.0

    # 소품 인덱싱: sand_ground는 두 패널 모두 → p002 마지막
    last_p = _last_prop_appearances(scene["panels"])
    assert last_p["sand_ground"][0] == 1
    # beach_umbrella_far는 p001만
    assert last_p["beach_umbrella_far"][0] == 0

    # 월드좌표 계산: 각 캐릭터가 카메라 정면 근처에 자리잡는지 산술로 확인
    shot = scene["shots"][0]
    panels = [{p["panel_id"]: p for p in scene["panels"]}[pid] for pid in shot["panel_ids"]]
    scene_meta = scene["scene_meta"]
    aspect = parse_aspect(scene["story_meta"]["aspect_ratio"])
    for cid, (pi, item) in last.items():
        pos = _resolve_world_pos_from_panel(
            panels[pi], item, shot["camera_keyframes"], pi, len(panels), scene_meta, aspect
        )
        # yuna는 x=0.3 (좌측), minsu는 x=0.7 (우측). 카메라 look_at은 대략 [0.5, 0, 1.6].
        # 마지막 키프레임은 pos=[0.5, -3, 1.6] look=[0.5, 0, 1.6]에서 depth=3, 3.2.
        # yuna는 좌측 스크린 → 월드 x < 0.5
        # minsu는 우측 스크린 → 월드 x > 0.5
        assert pos[2] == 1.6 or abs(pos[2] - 1.6) < 0.5, f"{cid} z: {pos}"
        if cid == "yuna":
            assert pos[0] < 0.5, f"yuna should be left of camera axis: {pos}"
        else:
            assert pos[0] > 0.5, f"minsu should be right of camera axis: {pos}"

    print("assembly.py (bpy-free portion): OK")


if __name__ == "__main__":
    _demo()
