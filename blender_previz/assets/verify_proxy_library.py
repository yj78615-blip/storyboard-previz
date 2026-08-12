"""proxy_library.blend 스펙 검증. 손으로 만든 애셋이 파이프라인 계약을 만족하는지 확인.

용법:
  blender --background --python verify_proxy_library.py \
      [-- --blend path/to/proxy_library.blend]
  기본 경로는 이 스크립트와 같은 디렉터리의 proxy_library.blend.

체크 항목 (기획 H항):
  1. 3개 Collection 존재
  2. 각 Collection에 mesh 오브젝트 1개
  3. 원점 (0, 0, 0)
  4. 높이(Z dimension) 스펙 범위 내
  5. 폴리곤 예산 초과 안 함 (성인/아동 <=10k tri, 실루엣 <=2k tri)

exit 0 = 통과, 1 = 위반.
"""

from __future__ import annotations
import sys
from pathlib import Path

# 스펙: (height_min, height_max, max_tri)
EXPECTED = {
    "ProxyAdultMannequin":    (1.70, 1.80, 10_000),
    "ProxyChildMannequin":    (1.15, 1.25, 10_000),
    "ProxyGenericSilhouette": (1.70, 1.80,  2_000),
}


def _parse_argv() -> str:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    for i, a in enumerate(argv):
        if a == "--blend" and i + 1 < len(argv):
            return argv[i + 1]
    # 기본: 같은 디렉터리의 proxy_library.blend
    return str(Path(__file__).resolve().parent / "proxy_library.blend")


def _tri_count(mesh) -> int:
    """quad는 tri 2개로 계산. n-gon도 대략 n-2로 근사."""
    total = 0
    for poly in mesh.polygons:
        n = len(poly.vertices)
        total += max(1, n - 2)
    return total


def main() -> int:
    import bpy  # type: ignore

    blend_path = _parse_argv()
    p = Path(blend_path)
    if not p.exists():
        print(f"[fail] blend not found: {blend_path}", file=sys.stderr)
        return 1

    bpy.ops.wm.open_mainfile(filepath=str(p))

    failures: list[str] = []

    for name, (h_lo, h_hi, tri_max) in EXPECTED.items():
        coll = bpy.data.collections.get(name)
        if coll is None:
            failures.append(f"{name}: collection missing")
            continue

        meshes = [o for o in coll.objects if o.type == "MESH"]
        if len(meshes) != 1:
            failures.append(f"{name}: expected 1 mesh, got {len(meshes)}")
            continue
        obj = meshes[0]

        loc = tuple(round(v, 4) for v in obj.location)
        if loc != (0.0, 0.0, 0.0):
            failures.append(f"{name}: origin at {loc}, expected (0,0,0)")

        z = obj.dimensions.z
        if not (h_lo <= z <= h_hi):
            failures.append(f"{name}: height {z:.3f}m outside [{h_lo}, {h_hi}]")

        tris = _tri_count(obj.data)
        if tris > tri_max:
            failures.append(f"{name}: {tris} tri exceeds max {tri_max}")

        print(f"[ok] {name}: h={z:.3f}m, tri={tris}, origin={loc}")

    if failures:
        print("\n[fail] " + "; ".join(failures), file=sys.stderr)
        return 1
    print("\n[pass] proxy_library.blend 스펙 준수")
    return 0


if __name__ == "__main__":
    sys.exit(main())
