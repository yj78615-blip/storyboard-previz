"""프리뷰 렌더 어댑터.

스토리보드 씬 JSON → blender-previz 스킬 스펙 → 카메라 확인용 MP4.
경로 B: Seedance 크레딧 소모 전 카메라 무빙/블로킹 검토.

blender-previz 스킬 3대 규칙 적용:
  1. 단순 도형만 (인체는 l_shape 근사)
  2. 네온 색만 (마젠타/시안/오렌지/노랑/핑크. 형광그린은 바닥 앵커 전용)
  3. 모든 subject/anchor에 final_role 필수 (스키마 v1.1이 이미 강제)

용법 (bpy 불필요):
  python preview_adapter.py --scene scene.json --shot s001 --out-spec spec.json
  python preview_adapter.py --scene scene.json --shot s001 --out-spec spec.json --render preview.mp4
  python preview_adapter.py --demo
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "blender_previz"))

from assembly import (  # noqa: E402
    _index_by_id,
    _last_appearance_index,
    _last_prop_appearances,
    _resolve_world_pos_from_panel,
)
from camera_builder import DEFAULT_SENSOR_WIDTH_MM, resolve_focal_mm  # noqa: E402
from placement import parse_aspect  # noqa: E402


# ---- 팔레트 & 상수 -------------------------------------------------------

# 형광그린은 grid_plane 앵커 전용. 캐릭터/소품이 침범 못하게 예약.
GROUND_NEON = "#39FF14"
CHAR_PALETTE = ["#FF00FF", "#00FFFF", "#FF6E00", "#F7FF00", "#FF3EA5"]
PROP_PALETTE = ["#F7FF00", "#FF3EA5", "#FF6E00", "#00FFFF", "#FF00FF"]

ASPECT_TO_RES = {
    "16:9":   [1280, 720],
    "9:16":   [720, 1280],
    "1:1":    [1024, 1024],
    "4:3":    [1024, 768],
    "2.39:1": [1280, 536],
}

# 인체 l_shape 근사. 스킬 prim_l_shape 는 z=0..3 유닛.
HUMAN_HEIGHT_M = {"adult": 1.75, "child": 1.20, "silhouette": 1.75}
L_SHAPE_UNIT_Z = 3.0
HUMAN_XY_SCALE = 0.15  # 30cm 폭 근사

BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
SKILL_PREVIZ_PY = Path.home() / ".claude" / "skills" / "blender-previz" / "scripts" / "previz.py"
# blender-previz 스킬이 없는 환경(대부분)을 위한 내장 대체 렌더러. 같은 spec 포맷을 소비함.
FALLBACK_PREVIZ_PY = _HERE / "preview_render.py"


# ---- 변환 ----------------------------------------------------------------

def _human_scale(kind: str) -> list[float]:
    h = HUMAN_HEIGHT_M.get(kind, 1.75)
    return [HUMAN_XY_SCALE, HUMAN_XY_SCALE, h / L_SHAPE_UNIT_Z]


def _sanitize_id(prefix: str, raw: str) -> str:
    s = "".join(c if c.isalnum() or c == "_" else "_" for c in raw)
    return f"{prefix}_{s}"


def _camera_keyframes(shot: dict) -> list[dict]:
    """우리 kf → 스킬 kf. 필드명만 갈아끼움."""
    out = []
    for kf in shot["camera_keyframes"]:
        item = {
            "t": float(kf["t_sec"]),
            "pos": [float(v) for v in kf["pos_world"]],
            "look_at": [float(v) for v in kf["look_at_world"]],
            "easing": kf.get("easing", "EASE_IN_OUT"),
        }
        if kf.get("easing_curve"):
            item["easing_curve"] = kf["easing_curve"]
        if kf.get("hold"):
            item["hold"] = True
        out.append(item)
    return out


def _pick_representative_focal(shot: dict, scene_meta: dict) -> float:
    """스킬 카메라는 단일 focal만 지원. 첫 kf 기준."""
    kf = shot["camera_keyframes"][0]
    sensor_w = float(scene_meta.get("sensor_width_mm", DEFAULT_SENSOR_WIDTH_MM))
    thr = float(scene_meta.get("fov_confidence_threshold", 0.3))
    focal, _ = resolve_focal_mm(kf, sensor_w, thr)
    return round(focal, 2)


def _panels_for_shot(scene: dict, shot: dict) -> list[dict]:
    panels_by_id = _index_by_id(scene["panels"], "panel_id")
    return [panels_by_id[pid] for pid in shot["panel_ids"]]


def build_spec(scene: dict, shot_id: str) -> dict:
    """scene(dict) + shot_id → blender-previz 스펙 dict."""
    shots_by_id = _index_by_id(scene["shots"], "shot_id")
    if shot_id not in shots_by_id:
        raise KeyError(f"shot_id '{shot_id}' not in scene")
    shot = shots_by_id[shot_id]
    panels = _panels_for_shot(scene, shot)
    scene_meta = scene["scene_meta"]
    aspect_str = scene.get("story_meta", {}).get("aspect_ratio")
    aspect = parse_aspect(aspect_str)
    res = ASPECT_TO_RES.get(aspect_str or "16:9", [1280, 720])

    char_reg = _index_by_id(scene["characters"], "character_id")
    keys = shot["camera_keyframes"]

    subjects: list[dict] = []
    anchors: list[dict] = []

    # 캐릭터 (등장 순서 안정화를 위해 정렬)
    char_last = _last_appearance_index(panels, "characters_in_frame", "character_id")
    for ci, cid in enumerate(sorted(char_last.keys())):
        pi, item = char_last[cid]
        panel = panels[pi]
        pos = _resolve_world_pos_from_panel(panel, item, keys, pi, len(panels), scene_meta, aspect)
        kind = char_reg[cid]["kind"]
        yaw = (item.get("estimated_transform") or {}).get("yaw_deg", 0.0)
        subjects.append({
            "id": _sanitize_id("char", cid),
            "role": "rotation_readable",
            "shape": "l_shape",
            "pos": list(pos),
            "rot_deg": [0.0, 0.0, float(yaw)],
            "scale": _human_scale(kind),
            "color": CHAR_PALETTE[ci % len(CHAR_PALETTE)],
            "final_role": item["final_role"],
        })

    # 소품: grid_plane → anchor, 그 외 → subject
    prop_last = _last_prop_appearances(panels)
    prop_i = 0
    for pname in sorted(prop_last.keys()):
        pi, item = prop_last[pname]
        panel = panels[pi]
        et = item.get("estimated_transform") or {}
        shape = item["shape"]
        if shape == "grid_plane":
            # 바닥은 원점 고정. 스킬 prim_grid_plane 이 10x10 유닛이라 미터 → 스케일 나눔.
            sm = et.get("scale_m", [10, 10, 1])
            anchors.append({
                "id": _sanitize_id("anchor", pname),
                "shape": "grid_plane",
                "pos": [0.0, 0.0, 0.0],
                "scale": [float(sm[0]) / 10.0, float(sm[1]) / 10.0, 1.0],
                "color": GROUND_NEON,
                "final_role": item["final_role"],
            })
        else:
            pos = _resolve_world_pos_from_panel(panel, item, keys, pi, len(panels), scene_meta, aspect)
            sm = et.get("scale_m", [1, 1, 1])
            subjects.append({
                "id": _sanitize_id("prop", pname),
                "role": "position_only",
                "shape": shape,
                "pos": list(pos),
                "rot_deg": [0.0, 0.0, float(et.get("yaw_deg", 0.0))],
                "scale": [float(s) for s in sm],
                "color": PROP_PALETTE[prop_i % len(PROP_PALETTE)],
                "final_role": item["final_role"],
            })
            prop_i += 1

    return {
        "scene": {
            "duration_sec": float(shot["duration_sec"]),
            "fps": int(scene_meta.get("fps", 24)),
            "resolution": res,
            "world_color": "#101010",
            "min_distance": float(scene_meta.get("min_distance_m", 0.4)),
        },
        "camera": {
            "focal_mm": _pick_representative_focal(shot, scene_meta),
            "sensor_mm": float(scene_meta.get("sensor_width_mm", 36.0)),
            "hold_frames": 6,
            "keyframes": _camera_keyframes(shot),
        },
        "subjects": subjects,
        "anchors": anchors,
    }


# ---- CLI -----------------------------------------------------------------

def _parse_argv() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="preview_adapter")
    p.add_argument("--scene", required=True, help="스토리보드 씬 JSON 경로")
    p.add_argument("--shot", required=True, help="렌더할 shot_id")
    p.add_argument("--out-spec", required=True, help="변환된 스킬 스펙 JSON 경로")
    p.add_argument("--render", metavar="MP4",
                   help="바로 blender-previz로 렌더. 지정한 경로에 MP4 저장.")
    p.add_argument("--blender", default=BLENDER_EXE, help=f"Blender exe (기본: {BLENDER_EXE})")
    return p.parse_args()


def _render_via_skill(spec_path: Path, out_mp4: Path, blender: str) -> int:
    if not Path(blender).exists():
        print(f"[error] blender not found: {blender}", file=sys.stderr)
        return 1
    if SKILL_PREVIZ_PY.exists():
        previz_py = SKILL_PREVIZ_PY
    elif FALLBACK_PREVIZ_PY.exists():
        print(f"[info] blender-previz 스킬 없음 - 내장 {FALLBACK_PREVIZ_PY.name}로 대체")
        previz_py = FALLBACK_PREVIZ_PY
    else:
        print(f"[error] skill previz.py not found: {SKILL_PREVIZ_PY}", file=sys.stderr)
        return 1
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        blender, "--background", "--python", str(previz_py),
        "--", "--spec", str(spec_path), "--out", str(out_mp4),
    ]
    print("[render]", " ".join(cmd))
    return subprocess.call(cmd)


def main() -> int:
    args = _parse_argv()
    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    spec = build_spec(scene, args.shot)
    out_spec = Path(args.out_spec)
    out_spec.parent.mkdir(parents=True, exist_ok=True)
    out_spec.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[spec] {out_spec}  subjects={len(spec['subjects'])} anchors={len(spec['anchors'])} focal={spec['camera']['focal_mm']}mm")
    if args.render:
        rc = _render_via_skill(out_spec, Path(args.render), args.blender)
        if rc != 0:
            print(f"[error] render exited {rc}", file=sys.stderr)
            return rc
        print(f"[done] preview mp4: {args.render}")
    return 0


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    scene = json.loads((_HERE / "storyboard_scene_example.json").read_text(encoding="utf-8"))
    spec = build_spec(scene, "s001")

    # 스킬 규칙 강제 확인
    for kf in spec["camera"]["keyframes"]:
        assert kf["easing"] not in {"BACK", "BOUNCE", "ELASTIC"}, kf
    for s in spec["subjects"] + spec["anchors"]:
        assert s.get("final_role"), f"Rule 3 위반: {s['id']}"
    for s in spec["subjects"]:
        if s["role"] == "rotation_readable":
            assert s["shape"] in {"asymmetric_wedge", "l_shape"}, f"Rule 1 위반: {s}"

    # 컴포지션
    assert spec["scene"]["duration_sec"] == 8.0
    assert spec["scene"]["resolution"] == [1280, 720]
    assert spec["camera"]["focal_mm"] > 0
    assert len(spec["camera"]["keyframes"]) == 3
    assert spec["camera"]["keyframes"][2].get("hold") is True

    ids = {s["id"] for s in spec["subjects"]}
    assert ids == {"char_minsu", "char_yuna", "prop_beach_umbrella_far"}, ids
    anchor_ids = {a["id"] for a in spec["anchors"]}
    assert anchor_ids == {"anchor_sand_ground"}, anchor_ids

    # 캐릭터 좌우 분포 (assembly._demo 와 동일 규칙)
    yuna = next(s for s in spec["subjects"] if s["id"] == "char_yuna")
    minsu = next(s for s in spec["subjects"] if s["id"] == "char_minsu")
    assert yuna["pos"][0] < minsu["pos"][0], (yuna["pos"], minsu["pos"])

    # 앵커 색 침범 금지 (팔레트 순환에서 형광그린 배제 확인)
    for s in spec["subjects"]:
        assert s["color"] != GROUND_NEON, f"{s['id']} 이 앵커 색 침범"

    # 인체 스케일 근사: 성인이면 Z 방향 스케일 ~1.75/3
    assert 0.55 < yuna["scale"][2] < 0.60, yuna["scale"]

    # sand_ground scale_m [20,20,1] (마지막 패널) → grid_plane 스케일 [2,2,1]
    a = spec["anchors"][0]
    assert a["scale"] == [2.0, 2.0, 1.0], a["scale"]
    assert a["pos"] == [0.0, 0.0, 0.0]

    print("preview_adapter.py: OK")


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
