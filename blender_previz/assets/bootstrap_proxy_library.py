"""proxy_library.blend 부트스트랩 (임시 애셋).

verify_proxy_library.py 스펙을 만족하는 매니큰 3종을 l_shape 프리미티브로 자동 생성.
정식 애셋은 리깅·재질 붙은 매니큰. 이 부트스트랩은 파이프라인 무결성 검증용.

용법:
  blender --background --python bootstrap_proxy_library.py -- --out <path/proxy_library.blend>

기본 출력: 이 스크립트와 같은 디렉터리의 proxy_library.blend.
"""
import bpy
import sys
from pathlib import Path

# proxy_library.py::l_shape_verts_faces 그대로. base(0..0.2) + riser(0.2..1.8) = z 최대 1.8.
L_VERTS = [
    (-0.5, -0.5, 0.0), ( 0.5, -0.5, 0.0), ( 0.5,  0.5, 0.0), (-0.5,  0.5, 0.0),
    (-0.5, -0.5, 0.2), ( 0.5, -0.5, 0.2), ( 0.5,  0.5, 0.2), (-0.5,  0.5, 0.2),
    (-0.2,  0.1, 0.2), ( 0.2,  0.1, 0.2), ( 0.2,  0.5, 0.2), (-0.2,  0.5, 0.2),
    (-0.2,  0.1, 1.8), ( 0.2,  0.1, 1.8), ( 0.2,  0.5, 1.8), (-0.2,  0.5, 1.8),
]
L_FACES = [
    (0, 1, 2, 3), (4, 5, 6, 7),
    (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    (8, 9, 10, 11), (12, 13, 14, 15),
    (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15),
]
L_UNIT_Z = 1.8

CATALOG = [
    ("ProxyAdultMannequin",    1.75),
    ("ProxyChildMannequin",    1.20),
    ("ProxyGenericSilhouette", 1.75),
]


def _parse_argv() -> str:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            return argv[i + 1]
    return str(Path(__file__).resolve().parent / "proxy_library.blend")


def clear_all():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def make_one(coll_name: str, height_m: float):
    """verts z만 사전 스케일해서 굽는다 → obj.dimensions.z == height, obj.scale == (1,1,1), origin 그대로."""
    sz = height_m / L_UNIT_Z
    scaled = [(x, y, z * sz) for (x, y, z) in L_VERTS]
    mesh = bpy.data.meshes.new(coll_name + "_mesh")
    mesh.from_pydata(scaled, [], L_FACES)
    mesh.update()
    obj = bpy.data.objects.new(coll_name, mesh)
    obj.location = (0.0, 0.0, 0.0)
    coll = bpy.data.collections.new(coll_name)
    bpy.context.scene.collection.children.link(coll)
    coll.objects.link(obj)


def main():
    out = _parse_argv()
    clear_all()
    for name, h in CATALOG:
        make_one(name, h)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"[bootstrap] saved {out} — {len(CATALOG)} collections")


if __name__ == "__main__":
    main()
