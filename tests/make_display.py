"""Crée un display SYNTHÉTIQUE de test (buste, caméra, lumière, monde, texture manquante).

Usage : python -I tests/make_display.py -- <chemin.blend> <dossier_absent>
"""

import math
import os
import sys

import bpy
import bmesh  # après bpy

path, missing_dir = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "Display"
scene.render.engine = "CYCLES"
scene.cycles.samples = 128
scene.render.resolution_x, scene.render.resolution_y = 800, 600
scene.world = bpy.data.worlds.new("Monde_Display")
me = bpy.data.meshes.new("Buste")
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.3)
bm.to_mesh(me)
bm.free()
mat = bpy.data.materials.new("Velours")
tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(os.path.join(missing_dir, "velours.png"), check_existing=False) \
    if os.path.isfile(os.path.join(missing_dir, "velours.png")) else bpy.data.images.new("velours", 4, 4)
tex.image.source = "FILE"
tex.image.filepath = os.path.join(missing_dir, "velours.png")
me.materials.append(mat)
bust = bpy.data.objects.new("Buste", me)
bust.location = (0, 0, 1.2)
cam = bpy.data.objects.new("CamPresentation", bpy.data.cameras.new("CamPresentation"))
cam.location = (0, -1.5, 1.4)
cam.rotation_euler = (math.radians(85), 0, 0)
light = bpy.data.objects.new("Spot", bpy.data.lights.new("Spot", "SPOT"))
light.location = (0.5, -1, 2)
marker = bpy.data.objects.new("Repere_Cou", None)
marker.location = (0, -0.25, 1.35)
presentoir = bpy.data.collections.new("Presentoir")
scene.collection.children.link(presentoir)
presentoir.objects.link(bust)
for o in (cam, light, marker):
    scene.collection.objects.link(o)
scene.camera = cam
# Ancien bijou du display : textures en chemins RELATIFS au fichier du display (cas réel).
mat2 = bpy.data.materials.new("Bijou_Ancien")
relative = []
for name, rel in (("kria_texture.png", "//../../Textures/kria_texture.png"),
                  ("argent_diff.png", "//../../Ailleurs/argent_diff.png"),
                  ("spec_blanc.png", "//../../../Textures/6-Maps/spec_blanc.png")):
    node = mat2.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.new(name, 4, 4)
    node.image.source = "FILE"
    relative.append((node.image, rel))
me2 = bpy.data.meshes.new("Ancien_Bijou")
me2.from_pydata([(0, 0, 0), (0.01, 0, 0), (0, 0.01, 0)], [], [(0, 1, 2)])
me2.materials.append(mat2)
old = bpy.data.objects.new("Ancien_Bijou", me2)
old.location = (0.3, 0, 1.2)
scene.collection.objects.link(old)
bpy.ops.wm.save_as_mainfile(filepath=path)
for img, rel in relative:
    img.filepath = rel
bpy.ops.wm.save_mainfile()
print("display écrit", path)
