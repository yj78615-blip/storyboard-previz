"""CLI 엔트리포인트 (Blender 헤드리스 실행).

용법:
  blender --background --python main.py -- \
      --scene <path/storyboard_scene.json> \
      --shot  <shot_id> \
      --blend <path/proxy_library.blend> \
      --out   <path/out_dir> \
      [--skip-validate]

--out 아래에 <shot_id>.fbx / .obj / _camera.json 이 생성됨.

--dry-run은 bpy 없이 스키마 검증 + assembly 순수 함수까지만 검사 (개발용).
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Blender --python 실행 시 스크립트 디렉터리가 sys.path에 없어 sibling 임포트 실패. 여기서 주입.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _parse_argv() -> argparse.Namespace:
    """Blender는 스크립트 앞부분의 sys.argv를 소비하므로 -- 뒤만 취함."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(prog="blender_previz")
    p.add_argument("--scene", required=True, help="스토리보드 씬 JSON 경로")
    p.add_argument("--shot",  required=True, help="빌드할 shot_id")
    p.add_argument("--blend", required=True, help="proxy_library.blend 경로")
    p.add_argument("--out",   required=True, help="출력 디렉터리")
    p.add_argument("--skip-validate", action="store_true", help="스키마 검증 스킵")
    p.add_argument("--dry-run", action="store_true", help="bpy 호출 없이 pre-flight만 실행")
    return p.parse_args(argv)


def validate_scene(scene: dict, schema_path: Path) -> None:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        print("[warn] jsonschema not installed — skipping validation. `pip install jsonschema`", file=sys.stderr)
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(scene, schema)


def _preflight(args: argparse.Namespace) -> dict:
    """bpy 없이 실행 가능한 사전 점검. 실패는 예외로."""
    scene_path = Path(args.scene)
    if not scene_path.exists():
        raise FileNotFoundError(f"scene not found: {scene_path}")
    scene = json.loads(scene_path.read_text(encoding="utf-8"))

    if not args.skip_validate:
        schema_path = scene_path.parent / "storyboard_scene_schema.json"
        # 상위 디렉터리에도 시도
        if not schema_path.exists():
            schema_path = scene_path.parent.parent / "storyboard_scene_schema.json"
        if schema_path.exists():
            validate_scene(scene, schema_path)
        else:
            print(f"[warn] schema not found near {scene_path} — skipping", file=sys.stderr)

    shot_ids = [s["shot_id"] for s in scene["shots"]]
    if args.shot not in shot_ids:
        raise KeyError(f"--shot '{args.shot}' not in scene ({shot_ids})")

    blend_path = Path(args.blend)
    if not blend_path.exists():
        raise FileNotFoundError(f"proxy_library.blend not found: {blend_path}")

    return scene


def main() -> int:
    args = _parse_argv()
    scene = _preflight(args)

    if args.dry_run:
        print(f"[dry-run] scene OK, shot '{args.shot}' exists, blend at {args.blend}")
        return 0

    # bpy 필요 지점부터
    from assembly import build_shot
    from export_blockout import export_all
    from placement import parse_aspect

    result = build_shot(scene, args.shot, args.blend)
    print(f"[build] shot={result['shot_id']} "
          f"chars={len(result['placed']['characters'])} "
          f"props={len(result['placed']['props'])}")

    import bpy  # type: ignore
    shot = next(s for s in scene["shots"] if s["shot_id"] == args.shot)
    cam_obj = bpy.data.objects[result["cam_obj_name"]]
    aspect = parse_aspect(scene.get("story_meta", {}).get("aspect_ratio"))

    outputs = export_all(cam_obj, shot, scene["scene_meta"], aspect, args.out)
    print("[export]")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
