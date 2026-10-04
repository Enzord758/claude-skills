"""Blender GPU render load for cc.py's `render` scenario: builds a procedural scene (no downloads)
and renders it with Cycles on the GPU in a loop until killed. Nothing is written to disk.
Run: blender -b --factory-startup --python blender_load.py"""
import bpy
import random

random.seed(4)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == backend
            break
    except TypeError:
        continue
scene.cycles.device = "GPU"
scene.cycles.samples = 2048
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 24
scene.render.resolution_x, scene.render.resolution_y = 2560, 1440

glass = bpy.data.materials.new("glass"); glass.use_nodes = True
g = glass.node_tree.nodes["Principled BSDF"]; g.inputs["Transmission Weight"].default_value = 1.0; g.inputs["Roughness"].default_value = 0.05
metal = bpy.data.materials.new("metal"); metal.use_nodes = True
m = metal.node_tree.nodes["Principled BSDF"]; m.inputs["Metallic"].default_value = 1.0; m.inputs["Roughness"].default_value = 0.2
for i in range(400):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=random.uniform(0.2, 0.8),
                                         location=(random.uniform(-8, 8), random.uniform(-8, 8), random.uniform(0, 6)))
    bpy.context.object.data.materials.append(glass if i % 2 else metal)
bpy.ops.mesh.primitive_plane_add(size=60)
bpy.ops.object.light_add(type="AREA", location=(0, 0, 12)); bpy.context.object.data.energy = 5000
bpy.ops.object.camera_add(location=(0, -18, 8), rotation=(1.2, 0, 0)); scene.camera = bpy.context.object
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5

print("cc render load: device", prefs.compute_device_type, flush=True)
while True:
    bpy.ops.render.render(write_still=False)
