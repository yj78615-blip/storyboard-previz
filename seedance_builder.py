"""Seedance 2.5 White-Model Control 제출 페이로드 빌더.

책임:
  1. 씬 JSON + shot_id ->텍스트 프롬프트 합성
  2. 블록아웃 파일 경로(FBX/OBJ) + 카메라 트랙 JSON + 캐릭터 레퍼런스 이미지 취합
  3. 페이로드 dict를 JSON으로 저장

실제 HTTP 호출은 이 스크립트가 하지 않음 — API 스펙 확정 전 페이로드만 남기고 별도 얇은 래퍼가
POST 하도록 의도적으로 분리. 페이로드 dict의 필드명은 관행적 슬롯이며 API 실제 스펙과 다를 수
있으므로 최종 호출 직전에 맞춰야 함.

bpy 불필요, 순수 파이썬. jsonschema만 선택 의존.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


TIME_OF_DAY_DESC = {
    "dawn":         "cool dawn light with soft blue-to-orange gradient",
    "morning":      "clear morning light, mid-warm tones",
    "midday":       "bright midday sun, high contrast",
    "afternoon":    "warm afternoon light, moderate shadows",
    "golden_hour":  "golden hour, low warm sun with long shadows",
    "dusk":         "dusk light, magenta-to-blue sky, ambient",
    "night":        "night, low key with practical light sources",
    "unknown":      "",
}

# 최대 레퍼런스 이미지 수. Seedance 2.5는 50까지 지원한다고 알려짐(2026-08 시점).
MAX_REFERENCE_IMAGES = 50


def _index_by_id(items: list[dict], key: str) -> dict[str, dict]:
    return {it[key]: it for it in items}


def _panel_t_estimate(panel_index: int, panel_count: int, duration_sec: float) -> float:
    if panel_count <= 1:
        return 0.0
    return round((panel_index / (panel_count - 1)) * duration_sec, 2)


def _collect_lighting(panels: list[dict]) -> str:
    """패널별 lighting 정보를 하나의 문장으로 병합."""
    times = []
    notes = []
    for p in panels:
        lg = p.get("lighting") or {}
        t = lg.get("time_of_day")
        if t and t not in times:
            times.append(t)
        n = lg.get("notes")
        if n and n not in notes:
            notes.append(n)
    parts = []
    if times:
        descs = [TIME_OF_DAY_DESC.get(t, t) for t in times]
        descs = [d for d in descs if d]
        if descs:
            parts.append(" transitioning to ".join(descs) if len(descs) > 1 else descs[0])
    if notes:
        parts.append("; ".join(notes))
    return ". ".join(parts)


def _collect_location_line(panels: list[dict], locations: list[dict]) -> str:
    loc_by_id = _index_by_id(locations, "location_id")
    seen = []
    for p in panels:
        lid = p.get("location_id")
        if lid and lid not in seen and lid in loc_by_id:
            seen.append(lid)
    if not seen:
        return ""
    descs = [loc_by_id[lid]["description"] for lid in seen]
    return " ->".join(descs) if len(descs) > 1 else descs[0]


def _subject_dictionary(panels: list[dict], characters: list[dict]) -> list[str]:
    """블록아웃의 화이트 오브젝트 ->최종 치환 대상 매핑 문장 리스트."""
    char_reg = _index_by_id(characters, "character_id")
    lines: list[str] = []
    seen_chars: set[str] = set()
    seen_props: set[str] = set()

    for panel in panels:
        for c in panel.get("characters_in_frame", []):
            cid = c["character_id"]
            if cid in seen_chars:
                continue
            seen_chars.add(cid)
            kind = char_reg.get(cid, {}).get("kind", "adult")
            pose = c.get("pose_category", "standing")
            lines.append(f"- mannequin `{cid}` ({kind}, {pose}) ->{c['final_role']}")

        for pr in panel.get("props_in_frame", []):
            name = pr["name"]
            if name in seen_props:
                continue
            seen_props.add(name)
            lines.append(f"- {pr['shape']} `{name}` ->{pr['final_role']}")
    return lines


def _panel_timeline(panels: list[dict], duration_sec: float) -> list[str]:
    n = len(panels)
    out: list[str] = []
    for i, p in enumerate(panels):
        frag = p.get("seedance_prompt_fragment")
        if not frag:
            continue
        t = _panel_t_estimate(i, n, duration_sec)
        out.append(f"- t~{t:.1f}s: {frag}")
    return out


def _reference_images(scene: dict, panels: list[dict]) -> list[dict]:
    """이 샷에 등장하는 캐릭터의 reference_image_path 취합. 최대 50개."""
    used_chars: list[str] = []
    for p in panels:
        for c in p.get("characters_in_frame", []):
            cid = c["character_id"]
            if cid not in used_chars:
                used_chars.append(cid)

    char_reg = _index_by_id(scene["characters"], "character_id")
    refs: list[dict] = []
    for cid in used_chars:
        path = char_reg.get(cid, {}).get("reference_image_path")
        if path:
            refs.append({"character_id": cid, "path": path})
    if len(refs) > MAX_REFERENCE_IMAGES:
        # 스킬 규약: silent truncation 금지. 잘리면 알린다.
        print(f"[warn] reference images {len(refs)} > {MAX_REFERENCE_IMAGES}, truncating",
              file=sys.stderr)
        refs = refs[:MAX_REFERENCE_IMAGES]
    return refs


def build_prompt(scene: dict, shot_id: str) -> str:
    shots_by_id = _index_by_id(scene["shots"], "shot_id")
    shot = shots_by_id[shot_id]
    panels_by_id = _index_by_id(scene["panels"], "panel_id")
    panels = [panels_by_id[pid] for pid in shot["panel_ids"]]

    aspect = scene.get("story_meta", {}).get("aspect_ratio", "16:9")
    duration = float(shot["duration_sec"])

    lines = [
        f"Cinematic {aspect} shot, {duration:.1f} seconds, single continuous take.",
    ]

    location_line = _collect_location_line(panels, scene["locations"])
    if location_line:
        lines.append(f"Location: {location_line}.")

    lighting_line = _collect_lighting(panels)
    if lighting_line:
        lines.append(f"Lighting: {lighting_line}.")

    timeline = _panel_timeline(panels, duration)
    if timeline:
        lines.append("")
        lines.append("Scene description across the shot timeline:")
        lines.extend(timeline)

    subj = _subject_dictionary(panels, scene["characters"])
    if subj:
        lines.append("")
        lines.append("White-model objects in the uploaded 3D blockout must be interpreted as:")
        lines.extend(subj)

    lines.append("")
    lines.append(
        "Follow the camera motion, framing, and subject blocking exactly as defined by the "
        "uploaded FBX blockout. Do not modify camera positions, focal length, or subject "
        "placements. Replace white-model surfaces only with the styles described above."
    )

    # 사용자가 shot_level_seedance_prompt를 명시했으면 우선 사용 (덮어쓰기)
    override = shot.get("shot_level_seedance_prompt")
    if override:
        return override

    return "\n".join(lines)


def build_payload(
    scene: dict,
    shot_id: str,
    blockout_dir: str | Path,
) -> dict:
    """API 페이로드 초안. 필드명은 관행적 슬롯 — 실제 스펙에 맞춰 rename 필요할 수 있음."""
    shot = _index_by_id(scene["shots"], "shot_id")[shot_id]
    blockout_dir = Path(blockout_dir)
    panels = [_index_by_id(scene["panels"], "panel_id")[pid] for pid in shot["panel_ids"]]

    return {
        "shot_id": shot_id,
        "duration_sec": float(shot["duration_sec"]),
        "aspect_ratio": scene.get("story_meta", {}).get("aspect_ratio", "16:9"),
        "fps": int(scene["scene_meta"].get("fps", 24)),
        "prompt": build_prompt(scene, shot_id),
        "blockout": {
            "fbx":          str(blockout_dir / f"{shot_id}.fbx"),
            "obj":          str(blockout_dir / f"{shot_id}.obj"),
            "camera_track": str(blockout_dir / f"{shot_id}_camera.json"),
        },
        "reference_images": _reference_images(scene, panels),
        "_meta": {
            "generator": "storyboard_previz.seedance_builder",
            "schema_version": scene.get("schema_version"),
            "note": "API 필드명은 실제 Seedance 2.5 스펙에 맞춰 최종 rename 필요.",
        },
    }


# ---- CLI -----------------------------------------------------------------

def _main() -> int:
    p = argparse.ArgumentParser(prog="seedance_builder")
    p.add_argument("--scene", required=True, help="storyboard_scene JSON")
    p.add_argument("--shot",  required=True, help="빌드할 shot_id")
    p.add_argument("--blockout-dir", required=True,
                   help="{shot_id}.fbx / .obj / _camera.json이 있는 디렉터리")
    p.add_argument("--out", required=True, help="페이로드 JSON 출력 경로")
    p.add_argument("--print-prompt", action="store_true",
                   help="stdout에 프롬프트만 출력 (디버깅용)")
    args = p.parse_args()

    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    if args.shot not in {s["shot_id"] for s in scene["shots"]}:
        print(f"[error] shot_id '{args.shot}' not in scene", file=sys.stderr)
        return 1

    if args.print_prompt:
        print(build_prompt(scene, args.shot))
        return 0

    payload = build_payload(scene, args.shot, args.blockout_dir)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] payload ->{args.out} (prompt: {len(payload['prompt'])} chars, "
          f"refs: {len(payload['reference_images'])})")
    return 0


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    scene = json.loads(
        (Path(__file__).resolve().parent / "storyboard_scene_example.json").read_text(encoding="utf-8")
    )
    prompt = build_prompt(scene, "s001")
    # 기본 요소 존재
    assert "Cinematic 16:9" in prompt, prompt
    assert "8.0 seconds" in prompt
    assert "golden hour" in prompt.lower()
    # location
    assert "beach" in prompt.lower()
    # subject dictionary가 final_role을 정확히 인용
    assert "young woman in red dress" in prompt
    assert "man in white shirt" in prompt.lower()
    # 소품도 매핑됨
    assert "sand_ground" in prompt
    assert "beach_umbrella_far" in prompt
    # 캐릭터 shape 정보
    assert "mannequin `yuna`" in prompt
    assert "grid_plane `sand_ground`" in prompt
    # 카메라 지시
    assert "Follow the camera motion" in prompt

    # override 우선순위
    scene_override = json.loads(json.dumps(scene))
    scene_override["shots"][0]["shot_level_seedance_prompt"] = "OVERRIDDEN"
    assert build_prompt(scene_override, "s001") == "OVERRIDDEN"

    # 패널 타임라인: 2패널이면 [0.0s, 8.0s]에 배치
    prompt_lines = prompt.split("\n")
    timeline = [l for l in prompt_lines if l.startswith("- t~")]
    assert len(timeline) == 2
    assert "t~0.0s" in timeline[0]
    assert "t~8.0s" in timeline[1]

    # payload 형태
    payload = build_payload(scene, "s001", "/tmp/out")
    assert payload["shot_id"] == "s001"
    assert payload["duration_sec"] == 8.0
    assert payload["aspect_ratio"] == "16:9"
    assert payload["fps"] == 24
    assert payload["blockout"]["fbx"].endswith("s001.fbx")
    assert payload["blockout"]["camera_track"].endswith("s001_camera.json")
    # example에는 reference_image_path=null이라 refs 비어있음
    assert payload["reference_images"] == []

    # reference 이미지 있으면 취합
    scene_with_ref = json.loads(json.dumps(scene))
    scene_with_ref["characters"][0]["reference_image_path"] = "refs/yuna.png"
    scene_with_ref["characters"][1]["reference_image_path"] = "refs/minsu.png"
    payload2 = build_payload(scene_with_ref, "s001", "/tmp/out")
    assert len(payload2["reference_images"]) == 2
    ids = {r["character_id"] for r in payload2["reference_images"]}
    assert ids == {"yuna", "minsu"}

    # dedup: 같은 캐릭터가 두 패널 모두 등장해도 한 번만
    scene_dup = json.loads(json.dumps(scene_with_ref))
    payload3 = build_payload(scene_dup, "s001", "/tmp/out")
    yuna_refs = [r for r in payload3["reference_images"] if r["character_id"] == "yuna"]
    assert len(yuna_refs) == 1

    print("seedance_builder.py: OK")


if __name__ == "__main__":
    # argv에 --scene 등이 있으면 CLI, 없으면 self-check
    if any(a.startswith("--") for a in sys.argv[1:]):
        sys.exit(_main())
    else:
        _demo()
