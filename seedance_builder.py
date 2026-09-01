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

# 블록아웃을 어떤 형태로 모델에 넘기느냐. 프롬프트의 지시 방식이 달라진다.
BLOCKOUT_MODES = ("fbx", "video")

DEFAULT_AUDIO = "natural ambient sound matching the location, no dialogue, no music"

NEGATIVE_CONSTRAINTS = (
    "No subtitles or on-screen text. No background music unless explicitly "
    "described in Audio above."
)


def _shot_type_label(shot_type: str | None) -> str:
    if not shot_type:
        return ""
    return shot_type.replace("_", " ") + " shot"


def _index_by_id(items: list[dict], key: str) -> dict[str, dict]:
    return {it[key]: it for it in items}


def _panel_t_range(panel_index: int, panel_count: int, duration_sec: float) -> tuple[float, float]:
    """패널이 차지하는 등분 구간 [start, end)를 초 단위로 반환."""
    if panel_count <= 1:
        return 0.0, duration_sec
    start = round((panel_index / panel_count) * duration_sec, 2)
    end = round(((panel_index + 1) / panel_count) * duration_sec, 2)
    return start, end


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


def _collect_audio(panels: list[dict]) -> str:
    """패널별 sound_notes를 하나의 Audio 절로 병합. 없으면 빈 문자열."""
    notes = []
    for p in panels:
        n = p.get("sound_notes")
        if n and n not in notes:
            notes.append(n)
    return "; ".join(notes)


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


def _subject_dictionary(
    panels: list[dict],
    characters: list[dict],
    ref_tag_by_char: dict[str, str] | None = None,
) -> list[str]:
    """블록아웃의 화이트 오브젝트 ->최종 치환 대상 매핑 문장 리스트."""
    char_reg = _index_by_id(characters, "character_id")
    ref_tag_by_char = ref_tag_by_char or {}
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
            tag = ref_tag_by_char.get(cid)
            role = f"{tag} {c['final_role']}" if tag else c["final_role"]
            lines.append(f"- mannequin `{cid}` ({kind}, {pose}) ->{role}")

        for pr in panel.get("props_in_frame", []):
            name = pr["name"]
            if name in seen_props:
                continue
            seen_props.add(name)
            lines.append(f"- {pr['shape']} `{name}` ->{pr['final_role']}")
    return lines


def _frame_zone(sx: float, sy: float) -> str:
    """screen_position → 화면 위치 서술. 영상 레퍼런스에서 어느 덩어리인지 짚어주는 단서."""
    h = "left" if sx < 0.30 else ("right" if sx > 0.70 else "centre")
    v = "upper " if sy < 0.35 else ("lower " if sy > 0.65 else "")
    return f"{v}{h} of frame"


def _subject_dictionary_video(
    panels: list[dict],
    characters: list[dict],
    ref_tag_by_char: dict[str, str] | None = None,
) -> list[str]:
    """영상 레퍼런스용 매핑. 오브젝트 '이름'이 아니라 '보이는 덩어리'로 지시한다.

    FBX 는 이름 붙은 오브젝트가 그대로 전달되지만, 렌더된 영상에는 이름이 존재하지
    않는다. 그래서 같은 shape + 같은 final_role 을 한 줄로 묶고 개수와 화면 위치를
    붙여, 모델이 화면에서 실제로 집어낼 수 있는 형태로 만든다.
    (예: 기둥 5개가 각각 한 줄 → "cylinder x5 (right of frame)" 한 줄)
    """
    char_reg = _index_by_id(characters, "character_id")
    ref_tag_by_char = ref_tag_by_char or {}
    lines: list[str] = []

    seen_chars: set[str] = set()
    for panel in panels:
        for c in panel.get("characters_in_frame", []):
            cid = c["character_id"]
            if cid in seen_chars:
                continue
            seen_chars.add(cid)
            kind = char_reg.get(cid, {}).get("kind", "adult")
            pose = c.get("pose_category", "standing")
            sp = c.get("screen_position") or {}
            zone = _frame_zone(sp.get("x", 0.5), sp.get("y", 0.5))
            tag = ref_tag_by_char.get(cid)
            role = f"{tag} {c['final_role']}" if tag else c["final_role"]
            lines.append(f"- the {kind} figure ({pose}, {zone}) ->{role}")

    # 소품: (shape, final_role) 로 묶고 화면 위치는 평균으로 대표
    groups: dict[tuple[str, str], list[dict]] = {}
    seen_props: set[str] = set()
    for panel in panels:
        for pr in panel.get("props_in_frame", []):
            if pr["name"] in seen_props:
                continue
            seen_props.add(pr["name"])
            groups.setdefault((pr["shape"], pr["final_role"]), []).append(pr)

    for (shape, role), items in groups.items():
        xs = [(it.get("screen_position") or {}).get("x", 0.5) for it in items]
        ys = [(it.get("screen_position") or {}).get("y", 0.5) for it in items]
        zone = _frame_zone(sum(xs) / len(xs), sum(ys) / len(ys))
        count = f" x{len(items)}" if len(items) > 1 else ""
        lines.append(f"- {shape}{count} ({zone}) ->{role}")
    return lines


def _panel_timeline(panels: list[dict], duration_sec: float) -> list[str]:
    n = len(panels)
    out: list[str] = []
    for i, p in enumerate(panels):
        frag = p.get("seedance_prompt_fragment")
        if not frag:
            continue
        start, end = _panel_t_range(i, n, duration_sec)
        label = _shot_type_label(p.get("camera_state", {}).get("shot_type"))
        tag = f" ({label})" if label else ""
        out.append(f"- [{start:.1f}-{end:.1f}s]{tag}: {frag}")
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


def build_prompt(
    scene: dict,
    shot_id: str,
    reference_images: list[dict] | None = None,
    blockout_mode: str = "fbx",
) -> str:
    """blockout_mode: 블록아웃을 어떤 형태로 넘기느냐.

    'fbx'   — 이름 붙은 오브젝트가 그대로 전달된다고 보고 오브젝트별로 지시.
    'video' — 렌더된 프리뷰 영상을 레퍼런스로 넘길 때. 영상에는 오브젝트 이름이
              없으므로 보이는 덩어리 단위로 묶어 지시한다.
    """
    if blockout_mode not in BLOCKOUT_MODES:
        raise ValueError(f"blockout_mode must be one of {BLOCKOUT_MODES}: {blockout_mode!r}")
    shots_by_id = _index_by_id(scene["shots"], "shot_id")
    shot = shots_by_id[shot_id]
    panels_by_id = _index_by_id(scene["panels"], "panel_id")
    panels = [panels_by_id[pid] for pid in shot["panel_ids"]]

    # 사용자가 shot_level_seedance_prompt를 명시했으면 우선 사용 (조립 스킵)
    override = shot.get("shot_level_seedance_prompt")
    if override:
        return override

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

    if reference_images is None:
        reference_images = _reference_images(scene, panels)
    ref_tag_by_char = {
        r["character_id"]: f"@Image{i + 1}" for i, r in enumerate(reference_images)
    }

    if blockout_mode == "video":
        subj = _subject_dictionary_video(panels, scene["characters"], ref_tag_by_char)
        header = ("The reference video is a white-model 3D blockout. Its coloured primitives "
                  "must be interpreted as:")
        source = "reference blockout video"
    else:
        subj = _subject_dictionary(panels, scene["characters"], ref_tag_by_char)
        header = "White-model objects in the uploaded 3D blockout must be interpreted as:"
        source = "uploaded FBX blockout"

    if subj:
        lines.append("")
        lines.append(header)
        lines.extend(subj)

    lines.append("")
    lines.append(
        f"Follow the camera motion, framing, and subject blocking exactly as defined by the "
        f"{source}. Do not modify camera positions, focal length, or subject "
        f"placements. Replace white-model surfaces only with the styles described above."
    )

    audio_line = _collect_audio(panels)
    lines.append("")
    lines.append(f"Audio: {audio_line if audio_line else DEFAULT_AUDIO}.")
    lines.append(NEGATIVE_CONSTRAINTS)

    return "\n".join(lines)


def build_payload(
    scene: dict,
    shot_id: str,
    blockout_dir: str | Path,
    blockout_mode: str = "fbx",
) -> dict:
    """API 페이로드 초안. 필드명은 관행적 슬롯 — 실제 스펙에 맞춰 rename 필요할 수 있음."""
    shot = _index_by_id(scene["shots"], "shot_id")[shot_id]
    blockout_dir = Path(blockout_dir)
    panels = [_index_by_id(scene["panels"], "panel_id")[pid] for pid in shot["panel_ids"]]
    refs = _reference_images(scene, panels)

    if blockout_mode == "video":
        # 영상 레퍼런스를 받는 API(예: Higgsfield 의 Seedance omni_reference)용.
        # preview_adapter 가 만든 프리뷰 MP4 를 레퍼런스로 올린다.
        blockout = {
            "preview_video": str(blockout_dir / f"{shot_id}_preview.mp4"),
            "camera_track":  str(blockout_dir / f"{shot_id}_camera.json"),
        }
    else:
        blockout = {
            "fbx":          str(blockout_dir / f"{shot_id}.fbx"),
            "obj":          str(blockout_dir / f"{shot_id}.obj"),
            "camera_track": str(blockout_dir / f"{shot_id}_camera.json"),
        }

    return {
        "shot_id": shot_id,
        "duration_sec": float(shot["duration_sec"]),
        "aspect_ratio": scene.get("story_meta", {}).get("aspect_ratio", "16:9"),
        "fps": int(scene["scene_meta"].get("fps", 24)),
        "blockout_mode": blockout_mode,
        "prompt": build_prompt(scene, shot_id, reference_images=refs,
                               blockout_mode=blockout_mode),
        "blockout": blockout,
        "reference_images": refs,
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
    p.add_argument("--blockout-mode", choices=BLOCKOUT_MODES, default="fbx",
                   help="블록아웃 전달 형태. fbx=이름 붙은 오브젝트 그대로, "
                        "video=프리뷰 MP4를 레퍼런스로 (기본: fbx)")
    p.add_argument("--print-prompt", action="store_true",
                   help="stdout에 프롬프트만 출력 (디버깅용)")
    args = p.parse_args()

    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    if args.shot not in {s["shot_id"] for s in scene["shots"]}:
        print(f"[error] shot_id '{args.shot}' not in scene", file=sys.stderr)
        return 1

    if args.print_prompt:
        print(build_prompt(scene, args.shot, blockout_mode=args.blockout_mode))
        return 0

    payload = build_payload(scene, args.shot, args.blockout_dir,
                            blockout_mode=args.blockout_mode)
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
    # 오디오 절 (sound_notes 병합)
    assert "Audio:" in prompt
    assert "갈매기" in prompt
    # 네거티브 제약
    assert "No subtitles" in prompt

    # override 우선순위
    scene_override = json.loads(json.dumps(scene))
    scene_override["shots"][0]["shot_level_seedance_prompt"] = "OVERRIDDEN"
    assert build_prompt(scene_override, "s001") == "OVERRIDDEN"

    # 패널 타임라인: 2패널 8초면 [0.0-4.0s], [4.0-8.0s]로 등분
    prompt_lines = prompt.split("\n")
    timeline = [l for l in prompt_lines if l.startswith("- [")]
    assert len(timeline) == 2
    assert "[0.0-4.0s]" in timeline[0]
    assert "(wide shot)" in timeline[0]
    assert "[4.0-8.0s]" in timeline[1]
    assert "(medium shot)" in timeline[1]

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
    # 레퍼런스가 있으면 프롬프트 본문에 @ImageN으로 인라인 바인딩됨
    assert "@Image1 young woman in red dress" in payload2["prompt"]
    assert "@Image2 man in white shirt" in payload2["prompt"]

    # dedup: 같은 캐릭터가 두 패널 모두 등장해도 한 번만
    scene_dup = json.loads(json.dumps(scene_with_ref))
    payload3 = build_payload(scene_dup, "s001", "/tmp/out")
    yuna_refs = [r for r in payload3["reference_images"] if r["character_id"] == "yuna"]
    assert len(yuna_refs) == 1

    # ---- 영상 레퍼런스 모드 ------------------------------------------------
    vid = build_prompt(scene, "s001", blockout_mode="video")
    # 영상에는 오브젝트 이름이 없으므로 백틱 이름 지시가 나오면 안 된다
    assert "`sand_ground`" not in vid, "영상 모드인데 오브젝트 이름으로 지시함"
    assert "`yuna`" not in vid
    assert "uploaded FBX blockout" not in vid
    assert "reference blockout video" in vid
    # 대신 화면 위치로 짚어줘야 한다
    assert "of frame" in vid
    # final_role 자체는 두 모드 모두 살아 있어야 한다
    for mode in ("fbx", "video"):
        pr = build_prompt(scene, "s001", blockout_mode=mode)
        assert "young woman in red dress" in pr, mode
        assert "wet sandy beach ground" in pr, mode

    # 같은 shape + 같은 final_role 은 한 줄로 묶이고 개수가 붙는다
    scene_many = json.loads(json.dumps(scene))
    props = scene_many["panels"][0]["props_in_frame"]
    base = dict(props[0])
    for i in range(3):
        dup = json.loads(json.dumps(base))
        dup["name"] = f"{base['name']}_dup{i}"
        props.append(dup)
    vid_many = build_prompt(scene_many, "s001", blockout_mode="video")
    assert f"{base['shape']} x4 (" in vid_many, vid_many

    # 화면 위치 구간
    assert _frame_zone(0.1, 0.5) == "left of frame"
    assert _frame_zone(0.9, 0.5) == "right of frame"
    assert _frame_zone(0.5, 0.5) == "centre of frame"
    assert _frame_zone(0.1, 0.2) == "upper left of frame"
    assert _frame_zone(0.9, 0.8) == "lower right of frame"

    # 페이로드: 모드에 따라 블록아웃 산출물이 달라진다
    pv = build_payload(scene, "s001", "/tmp/out", blockout_mode="video")
    assert pv["blockout_mode"] == "video"
    assert pv["blockout"]["preview_video"].endswith("s001_preview.mp4")
    assert "fbx" not in pv["blockout"]
    pf = build_payload(scene, "s001", "/tmp/out")
    assert pf["blockout_mode"] == "fbx"
    assert pf["blockout"]["fbx"].endswith("s001.fbx")

    # 잘못된 모드는 거부
    try:
        build_prompt(scene, "s001", blockout_mode="obj")
    except ValueError as e:
        assert "blockout_mode" in str(e)
    else:
        raise AssertionError("unknown blockout_mode should have been rejected")

    print("seedance_builder.py: OK")


if __name__ == "__main__":
    # argv에 --scene 등이 있으면 CLI, 없으면 self-check
    if any(a.startswith("--") for a in sys.argv[1:]):
        sys.exit(_main())
    else:
        _demo()
