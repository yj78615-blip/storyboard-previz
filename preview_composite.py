"""FBX 임포트 → 인식 가능한 조합 도형으로 교체 → 4방향 스틸 + 애니메이션 렌더.
씬 JSON/FBX/Seedance payload는 스킬 3대 원칙(단순 도형) 준수, 이 스크립트는 사람용 시각화 전용.

사용:
  blender.exe --background --python preview_composite.py -- \\
      --fbx out/s001.fbx --out out --shot-id s001 --frames 144

교체 규칙:
  driver_seat / passenger_seat → 캡틴 체어 5조각
  steering_wheel → 토러스+허브+스포크
  dashboard → 본체 큐브 + LCD + 계기판
  driver_male_* (adult 매니큰) → 앉은 자세 인체 10조각
  windshield / cabin_floor / ceiling / walls → 색상만 적용
"""
import bpy
import os
import sys
import mathutils

# --- CLI ---
def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--fbx", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--shot-id", default="s001")
    p.add_argument("--frames", type=int, default=144)
    p.add_argument("--scene", default=None, help="scene JSON, look_at 값 참조용")
    return p.parse_args(argv)

_ARGS = _parse_args()
FBX = _ARGS.fbx
OUT_DIR = _ARGS.out
SHOT_ID = _ARGS.shot_id
N_FRAMES = _ARGS.frames
SCENE_JSON = _ARGS.scene

PALETTE = {
    "driver_male_173": (0.90, 0.20, 0.20, 1.0),
    "standing_person": (0.90, 0.35, 0.30, 1.0),   # 서있는 사람 (살구빛 붉음)
    "driver_seat":     (1.00, 0.55, 0.10, 1.0),
    "passenger_seat":  (1.00, 0.85, 0.15, 1.0),
    "dashboard":       (0.10, 0.80, 0.90, 1.0),
    "steering_wheel":  (1.00, 0.20, 0.80, 1.0),
    "windshield":      (0.35, 0.60, 1.00, 1.0),
    "cabin_floor":     (0.20, 0.50, 0.30, 1.0),
    "tree_a_trunk":    (0.35, 0.20, 0.10, 1.0),   # 갈색
    "tree_b_trunk":    (0.35, 0.20, 0.10, 1.0),
    "tree_c_trunk":    (0.35, 0.20, 0.10, 1.0),
    "tree_d_trunk":    (0.35, 0.20, 0.10, 1.0),
    "tree_e_trunk":    (0.35, 0.20, 0.10, 1.0),
    "tree_f_trunk":    (0.35, 0.20, 0.10, 1.0),
    "_canopy":         (0.20, 0.55, 0.22, 1.0),   # 진초록 (나무 잎)
    "forest_ground":   (0.30, 0.22, 0.15, 1.0),   # 흙 갈색
}

OCCLUDERS = {"ceiling", "left_wall", "rear_partition"}

def clean_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

def find_obj(tag):
    for obj in bpy.data.objects:
        if tag in obj.name.lower():
            return obj
    return None

def add_cube(name, center, size, color):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size  # size는 half-extent 아님, dimensions로 조정
    obj.dimensions = size
    obj.color = color
    return obj

def add_torus(name, center, major, minor, color, axis='Z'):
    bpy.ops.mesh.primitive_torus_add(
        location=center, major_radius=major, minor_radius=minor, major_segments=32, minor_segments=12)
    obj = bpy.context.active_object
    obj.name = name
    obj.color = color
    if axis == 'Y':
        obj.rotation_euler = (1.5708, 0, 0)  # 세로
    return obj

def add_cylinder(name, center, radius, depth, color, axis='Z'):
    bpy.ops.mesh.primitive_cylinder_add(location=center, radius=radius, depth=depth, vertices=24)
    obj = bpy.context.active_object
    obj.name = name
    obj.color = color
    if axis == 'X':
        obj.rotation_euler = (0, 1.5708, 0)
    return obj

def build_captain_chair(base_name, pos, color):
    """캡틴 체어 5조각 (좌면·등받이·헤드레스트·좌우 팔걸이). 시트 얼굴 방향 +Y(전방)."""
    cx, cy, cz = pos.x, pos.y, 0.0
    # 좌면 (0.42m 높이 12cm)
    add_cube(f"{base_name}_seat",     (cx, cy,        0.42), (0.5, 0.5, 0.12), color)
    # 등받이 (뒤쪽 = -Y, 상단 1.05m)
    add_cube(f"{base_name}_back",     (cx, cy - 0.22, 0.85), (0.5, 0.1, 0.7),  color)
    # 헤드레스트 (등받이 위)
    add_cube(f"{base_name}_headrest", (cx, cy - 0.22, 1.28), (0.3, 0.12, 0.2), color)
    # 팔걸이 좌우
    add_cube(f"{base_name}_armL",     (cx - 0.28, cy - 0.05, 0.62), (0.06, 0.4, 0.06), color)
    add_cube(f"{base_name}_armR",     (cx + 0.28, cy - 0.05, 0.62), (0.06, 0.4, 0.06), color)

def build_steering(pos, color):
    """토러스 핸들 + 허브 + 세 스포크."""
    cx, cy, cz = pos.x, pos.y, pos.z
    # 링 (Y축을 향해 세워짐 = 운전자 정면)
    add_torus("steering_ring", (cx, cy, cz), 0.19, 0.015, color, axis='Y')
    # 허브
    add_cylinder("steering_hub", (cx, cy, cz), 0.04, 0.05, color, axis='Y')
    # 3 스포크 (얇은 큐브)
    add_cube("steering_spoke_h", (cx, cy, cz), (0.38, 0.02, 0.02), color)  # 수평
    add_cube("steering_spoke_v1", (cx, cy, cz - 0.11), (0.02, 0.02, 0.16), color)  # 하단

def add_sphere(name, center, radius, color):
    bpy.ops.mesh.primitive_uv_sphere_add(location=center, radius=radius, segments=24, ring_count=16)
    obj = bpy.context.active_object
    obj.name = name; obj.color = color
    return obj

def build_human_sitting(base_name, pos, color):
    """앉은 자세의 173cm 남성. pos = 시트 발밑 원점 (X, Y=시트 중심, Z=0). +Y 방향으로 얼굴·다리 향함.

    좌표 규약: 이 씬에서 운전자 정면 = +Y. 다리는 +Y로 뻗어 페달로. 손은 +Y·+Z로 스티어링으로.
    앉은 자세 dims:
      좌면 위 엉덩이 Z=0.45, 어깨 Z=1.10, 앉은 정수리 Z=1.32
      대퇴부 수평 → 무릎 (Y+0.30, Z=0.45)
      하퇴 수직 → 발 (Y+0.30, Z=0)
    """
    cx, cy, _ = pos.x, pos.y, 0.0
    HIP_Z = 0.45
    SHOULDER_Z = 1.10
    HEAD_CENTER_Z = 1.24
    NECK_Z = 1.14
    KNEE_Y = cy + 0.30; KNEE_Z = 0.45
    FOOT_Y = cy + 0.30; FOOT_Z = 0.04

    # 몸통 (엉덩이~어깨)
    add_cube(f"{base_name}_torso",
             (cx, cy, (HIP_Z + SHOULDER_Z) / 2),
             (0.40, 0.25, SHOULDER_Z - HIP_Z), color)
    # 목
    add_cylinder(f"{base_name}_neck", (cx, cy, NECK_Z), 0.05, 0.08, color, axis='Z')
    # 머리 (구)
    add_sphere(f"{base_name}_head", (cx, cy, HEAD_CENTER_Z), 0.11, color)

    # 대퇴 (엉덩이 → 무릎). 두 다리 좌우로 벌림 x±0.10
    for side, x_off in [('L', -0.10), ('R', +0.10)]:
        add_cube(f"{base_name}_thigh_{side}",
                 (cx + x_off, (cy + KNEE_Y) / 2, HIP_Z - 0.02),
                 (0.15, KNEE_Y - cy, 0.14), color)
        # 하퇴 (무릎 → 발)
        add_cube(f"{base_name}_shin_{side}",
                 (cx + x_off, KNEE_Y, KNEE_Z / 2),
                 (0.14, 0.14, KNEE_Z), color)
        # 발
        add_cube(f"{base_name}_foot_{side}",
                 (cx + x_off, FOOT_Y + 0.08, FOOT_Z),
                 (0.12, 0.24, 0.08), (0.15, 0.15, 0.15, 1.0))

    # 팔 (어깨 → 스티어링). 스티어링이 앞 상방 (Y+0.8, Z=0.85)
    STEER_Y = cy + 0.80; STEER_Z = 0.85
    for side, x_off in [('L', -0.20), ('R', +0.20)]:
        shoulder = (cx + x_off, cy, SHOULDER_Z - 0.05)
        hand     = (cx + x_off, STEER_Y, STEER_Z)
        mid = ((shoulder[0]+hand[0])/2, (shoulder[1]+hand[1])/2, (shoulder[2]+hand[2])/2)
        # 팔 전체를 하나의 얇은 큐브로 (기울여서). 간이화.
        add_cube(f"{base_name}_arm_{side}", mid,
                 (0.10, ((STEER_Y-cy)**2 + (STEER_Z-SHOULDER_Z+0.05)**2)**0.5, 0.10), color)
        # rotation to align y-axis toward hand
        arm = bpy.context.active_object
        dv = mathutils.Vector((0, STEER_Y - cy, STEER_Z - SHOULDER_Z + 0.05))
        # rotation around X axis so that local +Y points along dv
        import math
        angle = math.atan2(dv.z, dv.y)
        arm.rotation_euler = (angle, 0, 0)

def build_human_standing(base_name, pos, color):
    """서있는 자세의 175cm 성인. pos = 발밑 원점 (X, Y, Z=0)."""
    cx, cy, _ = pos.x, pos.y, 0.0
    HIP_Z = 0.95; SHOULDER_Z = 1.45; NECK_Z = 1.51; HEAD_Z = 1.63
    KNEE_Z = 0.50
    add_cube(f"{base_name}_torso", (cx, cy, (HIP_Z + SHOULDER_Z) / 2), (0.40, 0.25, SHOULDER_Z - HIP_Z), color)
    add_cylinder(f"{base_name}_neck", (cx, cy, NECK_Z), 0.05, 0.08, color, axis='Z')
    add_sphere(f"{base_name}_head", (cx, cy, HEAD_Z), 0.12, color)
    for side, x_off in [('L', -0.10), ('R', +0.10)]:
        # 대퇴 (엉덩이 → 무릎)
        add_cylinder(f"{base_name}_thigh_{side}", (cx + x_off, cy, (HIP_Z + KNEE_Z) / 2), 0.09, HIP_Z - KNEE_Z, color, axis='Z')
        # 하퇴 (무릎 → 발)
        add_cylinder(f"{base_name}_shin_{side}",  (cx + x_off, cy, KNEE_Z / 2), 0.075, KNEE_Z, color, axis='Z')
        # 발
        add_cube(f"{base_name}_foot_{side}", (cx + x_off, cy + 0.06, 0.04), (0.12, 0.24, 0.08), (0.15, 0.15, 0.15, 1.0))
        # 팔 (어깨 → 손, 자연스럽게 살짝 앞으로)
        add_cylinder(f"{base_name}_arm_{side}", (cx + 0.22 * (1 if side == 'R' else -1), cy, (SHOULDER_Z - 0.02 + HIP_Z - 0.05) / 2), 0.06, SHOULDER_Z - HIP_Z + 0.1, color, axis='Z')

def build_dashboard(pos, size, color):
    """대시보드 본체 + LCD 화면 + 계기판 클러스터."""
    cx, cy, cz = pos.x, pos.y, pos.z
    sx, sy, sz = size.x, size.y, size.z
    # 본체 (기존과 유사)
    add_cube("dash_body", (cx, cy, cz), (sx, sy, sz), color)
    # 12.3" LCD (윗면 중앙 살짝 뒤로 튀어나옴)
    add_cube("dash_lcd",  (cx, cy - sy/2 - 0.03, cz + sz/2 + 0.08),
             (0.32, 0.02, 0.16), (0.02, 0.02, 0.05, 1.0))  # 화면 검은색
    # 계기판 클러스터 (운전자 쪽)
    add_cube("dash_cluster", (cx - 0.55, cy - sy/2 - 0.02, cz + sz/2 + 0.05),
             (0.28, 0.02, 0.14), (0.05, 0.05, 0.05, 1.0))

def compute_bbox(exclude_floor=True):
    mn = mathutils.Vector((1e9, 1e9, 1e9))
    mx = mathutils.Vector((-1e9, -1e9, -1e9))
    for obj in bpy.data.objects:
        if obj.type != 'MESH': continue
        if exclude_floor and 'floor' in obj.name.lower(): continue
        for corner in obj.bound_box:
            wp = obj.matrix_world @ mathutils.Vector(corner)
            mn.x = min(mn.x, wp.x); mn.y = min(mn.y, wp.y); mn.z = min(mn.z, wp.z)
            mx.x = max(mx.x, wp.x); mx.y = max(mx.y, wp.y); mx.z = max(mx.z, wp.z)
    return mn, mx

def make_cam(name, pos, target, lens_mm=35.0):
    cam_data = bpy.data.cameras.new(name); cam_data.lens = lens_mm
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = pos
    direction = mathutils.Vector(target) - mathutils.Vector(pos)
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()
    return cam_obj

def add_sun():
    light_data = bpy.data.lights.new("sun", type='SUN'); light_data.energy = 3.0
    light_obj = bpy.data.objects.new("sun", light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = (5.0, 5.0, 8.0); light_obj.rotation_euler = (0.6, 0.3, 0.0)

def main():
    clean_scene()
    bpy.ops.import_scene.fbx(filepath=FBX)

    # 시트·스티어링·대시보드·캐릭터를 조합 도형으로 교체
    # (교체 전에 위치·스케일 수집)
    replacements = []
    for obj in list(bpy.data.objects):
        n = obj.name.lower()
        if 'driver_seat' in n or 'passenger_seat' in n:
            is_driver = 'driver_seat' in n
            replacements.append(('chair', obj, obj.location.copy(),
                                 PALETTE["driver_seat"] if is_driver else PALETTE["passenger_seat"],
                                 "driver" if is_driver else "passenger"))
        elif 'steering' in n:
            replacements.append(('steering', obj, obj.location.copy(), PALETTE["steering_wheel"], None))
        elif 'dashboard' in n:
            replacements.append(('dash', obj, obj.location.copy(), PALETTE["dashboard"], None,
                                 mathutils.Vector(obj.dimensions)))
        elif 'standing_person' in n or ('standing' in n and ('adult' in n or 'proxy' in n or 'mannequin' in n)):
            replacements.append(('human_standing', obj, obj.location.copy(), PALETTE["standing_person"], "standing_person"))
        elif 'driver_male' in n or 'adultmannequin' in n or ('proxy' in n and 'adult' in n):
            replacements.append(('human', obj, obj.location.copy(), PALETTE["driver_male_173"], "driver_male_173"))

    # 삭제
    for r in replacements:
        bpy.data.objects.remove(r[1], do_unlink=True)

    # 재빌드
    for r in replacements:
        kind = r[0]
        if kind == 'chair':
            build_captain_chair(f"{r[4]}_chair", r[2], r[3])
        elif kind == 'steering':
            build_steering(r[2], r[3])
        elif kind == 'dash':
            build_dashboard(r[2], r[5], r[3])
        elif kind == 'human':
            build_human_sitting(f"{r[4]}_body", r[2], r[3])
        elif kind == 'human_standing':
            build_human_standing(f"{r[4]}_body", r[2], r[3])

    # 나머지 (character, windshield, floor 등) 색상 강제 지정
    # 새로 만든 조합도형(chair, dash, steering)은 함수에서 색을 이미 세팅했으므로 스킵.
    NEW_TAGS = ("chair_", "dash_", "steering_", "_body_", "_torso", "_head", "_neck", "_thigh", "_shin", "_foot", "_arm")
    for obj in bpy.data.objects:
        if obj.type != 'MESH': continue
        n = obj.name.lower()
        if any(t in n for t in NEW_TAGS): continue
        for tag, col in PALETTE.items():
            if tag in n:
                obj.color = col; break

    # 오클루더 제거
    for obj in list(bpy.data.objects):
        n = obj.name.lower()
        for tag in OCCLUDERS:
            if tag in n:
                bpy.data.objects.remove(obj, do_unlink=True); break

    mn, mx = compute_bbox(exclude_floor=True)
    cx = (mn.x + mx.x) / 2; cy = (mn.y + mx.y) / 2; cz = (mn.z + mx.z) / 2
    dx = mx.x - mn.x; dy = mx.y - mn.y; dz = mx.z - mn.z
    print(f"[bbox] center=({cx:.2f},{cy:.2f},{cz:.2f}) size=({dx:.2f},{dy:.2f},{dz:.2f})")

    dist = max(dx, dy, dz) * 1.6
    target = (cx, cy, cz)
    VIEWS = [
        ("left",  (cx - dist, cy,        cz + 0.4), target, 35.0),
        ("right", (cx + dist, cy,        cz + 0.4), target, 35.0),
        ("front", (cx,        cy + dist, cz + 0.4), target, 35.0),
        ("rear",  (cx,        cy - dist, cz + 0.4), target, 35.0),
    ]

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 1280; scene.render.resolution_y = 720
    scene.render.image_settings.file_format = 'PNG'; scene.render.film_transparent = False

    shading = scene.display.shading
    shading.light = 'STUDIO'; shading.color_type = 'OBJECT'
    shading.show_shadows = True; shading.show_cavity = True; shading.cavity_type = 'WORLD'
    shading.show_object_outline = True; shading.object_outline_color = (0.0, 0.0, 0.0)
    scene.display.viewport_aa = 'FXAA'

    world = bpy.data.worlds.new("w") if not len(bpy.data.worlds) else bpy.data.worlds[0]
    scene.world = world; world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg: bg.inputs[0].default_value = (0.10, 0.11, 0.13, 1.0)

    add_sun()

    for name, pos, target_pt, lens_mm in VIEWS:
        cam = make_cam(f"cam_{name}", pos, target_pt, lens_mm=lens_mm)
        scene.camera = cam
        out_path = os.path.join(OUT_DIR, f"{SHOT_ID}_view_{name}.png")
        scene.render.filepath = out_path
        bpy.ops.render.render(write_still=True)
        print(f"[view] {name} -> {out_path}")

    # 애니메이션: camera.json 위치 + 씬 JSON look_at 을 to_track_quat 으로 조합
    # (FBX 임포트 카메라의 rotation_euler는 Y-up 변환으로 부호가 반전되어 있어 신뢰 불가)
    import json
    cam_json_path = os.path.join(os.path.dirname(FBX), f"{SHOT_ID}_camera.json")
    if not os.path.isfile(cam_json_path) or not SCENE_JSON:
        print(f"[warn] camera.json 또는 --scene 없음 — 애니메이션 스킵")
    else:
        with open(cam_json_path, "r", encoding="utf-8") as f:
            cam_data = json.load(f)
        with open(SCENE_JSON, "r", encoding="utf-8") as f:
            scene_data = json.load(f)
        cam_frames = cam_data.get("frames", [])
        # 씬 JSON에서 해당 shot의 keyframes (pos_world, look_at_world, t_sec)
        shot = next((s for s in scene_data["shots"] if s["shot_id"] == SHOT_ID), None)
        if shot is None or not cam_frames:
            print("[warn] shot 또는 frames 비어있음 — 스킵")
        else:
            kfs = shot["camera_keyframes"]
            duration = float(shot.get("duration_sec", 6.0))
            def interp_look_at(t):
                # 인접 keyframe 사이 선형 보간
                for i in range(len(kfs) - 1):
                    a, b = kfs[i], kfs[i+1]
                    if a["t_sec"] <= t <= b["t_sec"]:
                        span = b["t_sec"] - a["t_sec"]
                        u = (t - a["t_sec"]) / span if span > 1e-6 else 0.0
                        la_a = a["look_at_world"]; la_b = b["look_at_world"]
                        return tuple(la_a[k] + u * (la_b[k] - la_a[k]) for k in range(3))
                return tuple(kfs[-1]["look_at_world"])

            anim_cam_data = bpy.data.cameras.new("anim_cam"); anim_cam_data.lens = 35.0
            anim_cam = bpy.data.objects.new("anim_cam", anim_cam_data)
            bpy.context.scene.collection.objects.link(anim_cam)
            scene.camera = anim_cam
            frames_dir = os.path.join(OUT_DIR, f"{SHOT_ID}_anim_frames")
            os.makedirs(frames_dir, exist_ok=True)
            for i, kf in enumerate(cam_frames[:N_FRAMES]):
                t = float(kf.get("t_sec", i * (duration / max(1, N_FRAMES - 1))))
                pos = tuple(kf["location"])
                la  = interp_look_at(t)
                anim_cam.location = pos
                direction = mathutils.Vector(la) - mathutils.Vector(pos)
                rot_quat = direction.to_track_quat('-Z', 'Y')
                anim_cam.rotation_euler = rot_quat.to_euler()
                anim_cam.data.lens = float(kf.get("focal_mm", 35.0))
                scene.render.filepath = os.path.join(frames_dir, f"frame_{i+1:04d}.png")
                bpy.ops.render.render(write_still=True)
            print(f"[anim] {len(cam_frames[:N_FRAMES])} frames -> {frames_dir}")

    print("[done]")

main()
