"""Render a Primeva terrain export (.glb) with Blender Cycles (CPU, headless).

Usage:
  blender -b --factory-startup -P tools/blender/render_glb.py -- in.glb out.png [--samples 48] [--res 1600x900]
         [--sun-elev 28] [--sun-az 135] [--cam-elev 32] [--cam-az 220] [--cam-dist 1.15]

The terrain mesh carries per-vertex material albedo in COLOR_0 (written by
primeva_cli export); here it drives a physically based material with a
micro-normal bump so the 0.125 m voxel surface reads as natural ground.
Water gets a transmissive, refractive surface with depth absorption.
"""

import math
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("usage: blender -b -P render_glb.py -- in.glb out.png [options]")
    opts = {"samples": 48, "res": "1600x900", "sun-elev": 28.0, "sun-az": 135.0,
            "cam-elev": 32.0, "cam-az": 220.0, "cam-dist": 1.15}
    i = 2
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key in opts and i + 1 < len(argv):
            opts[key] = type(opts[key])(argv[i + 1]) if not isinstance(opts[key], str) else argv[i + 1]
            i += 2
        else:
            i += 1
    return argv[0], argv[1], opts


def terrain_material():
    mat = bpy.data.materials.new("PrimevaTerrain")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "Color"
    # Break up flat per-material albedo with low-amplitude multi-scale variation.
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.9
    noise.inputs["Detail"].default_value = 8.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.35
    nt.links.new(attr.outputs["Color"], mix.inputs[6])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.75, 0.75, 0.75, 1)
    ramp.color_ramp.elements[1].color = (1.15, 1.15, 1.15, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.92
    # micro relief
    bump_noise = nt.nodes.new("ShaderNodeTexNoise")
    bump_noise.inputs["Scale"].default_value = 14.0
    bump_noise.inputs["Detail"].default_value = 6.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.03
    nt.links.new(bump_noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def water_material():
    mat = bpy.data.materials.new("PrimevaWater")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.75, 0.9, 0.95, 1)
    bsdf.inputs["Roughness"].default_value = 0.04
    bsdf.inputs["IOR"].default_value = 1.333
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    waves = nt.nodes.new("ShaderNodeTexNoise")
    waves.inputs["Scale"].default_value = 3.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(waves.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    absorb = nt.nodes.new("ShaderNodeVolumeAbsorption")
    absorb.inputs["Color"].default_value = (0.25, 0.55, 0.6, 1)
    absorb.inputs["Density"].default_value = 0.35
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    nt.links.new(absorb.outputs["Volume"], out.inputs["Volume"])
    return mat


def main():
    src, dst, o = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)

    meshes = [ob for ob in bpy.context.scene.objects if ob.type == "MESH"]
    tmat, wmat = terrain_material(), water_material()
    lo = Vector((1e30, 1e30, 1e30))
    hi = Vector((-1e30, -1e30, -1e30))
    for ob in meshes:
        ob.data.materials.clear()
        is_water = "water" in ob.name.lower()
        ob.data.materials.append(wmat if is_water else tmat)
        for p in ob.data.polygons:
            p.use_smooth = True
        for v in ob.bound_box:
            w = ob.matrix_world @ Vector(v)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    if not meshes:
        raise SystemExit("no meshes in " + src)
    centre = (lo + hi) * 0.5
    extent = max(hi.x - lo.x, hi.y - lo.y, 1.0)

    scene = bpy.context.scene
    # World: physical sky (Nishita) matching the sun direction.
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    wn = world.node_tree
    sky = wn.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(o["sun-elev"])
    sky.sun_rotation = math.radians(o["sun-az"])
    sky.altitude = 300.0
    sky.air_density = 1.0
    sky.dust_density = 1.5
    sky.sun_disc = False  # direct light comes from the Sun lamp only (no double sun)
    bg = wn.nodes["Background"]
    bg.inputs["Strength"].default_value = 1.0
    wn.links.new(sky.outputs["Color"], bg.inputs["Color"])

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(0.53)
    sun = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(90 - o["sun-elev"]), 0.0, math.radians(o["sun-az"]))

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 30
    cam_data.clip_start = 0.1
    cam_data.clip_end = extent * 20
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    el, az = math.radians(o["cam-elev"]), math.radians(o["cam-az"])
    d = extent * o["cam-dist"]
    cam.location = centre + Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))) * d
    direction = centre - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    w, h = (int(v) for v in o["res"].split("x"))
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(o["samples"])
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.view_settings.exposure = -0.4
    scene.render.filepath = dst
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print("PRIMEVA_RENDER_OK", dst)


if __name__ == "__main__":
    main()
