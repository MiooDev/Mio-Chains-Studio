"""Tests de bout en bout dans Blender (module bpy) avec Sollumz réellement installé et le dossier Teef.

Usage :
    python -I tests/run_tests.py -- <dossier_de_travail> <dossier_Teef>

Prérequis : bpy 5.2.x, Sollumz et Mio Chain Studio installés dans le dépôt d'extensions « user_default ».
Le SVG, la chaîne OBJ et le display sont SYNTHÉTIQUES ; les références Teef sont les vraies.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import traceback

import bpy
import bmesh
import numpy as np
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WORK = os.path.abspath(ARGS[0] if ARGS else "mcs_test_work")
TEEF = os.path.abspath(ARGS[1]) if len(ARGS) > 1 else ""
ADDON = "bl_ext.user_default.mio_chain_studio"
SOLLUMZ = "bl_ext.user_default.sollumz"
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), str(detail)))
    print(("  OK  " if cond else "  ÉCHEC ") + name + (f" — {detail}" if detail and not cond else ""))
    return cond


def run(op, **kw):
    try:
        return getattr(bpy.ops.mio_chain, op)(**kw)
    except RuntimeError as exc:
        return {"ERROR: " + str(exc).splitlines()[0]}


def proj():
    return bpy.data.scenes["Scene"].mio_chain


def select_only(*objs, active=None):
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def edit_select_faces(obj, predicate):
    """Passe en Edit Mode sur obj et sélectionne les faces vérifiant predicate(face bmesh)."""
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    for f in bm.faces:
        f.select_set(False)
    n = 0
    for f in bm.faces:
        if predicate(f):
            f.select_set(True)
            n += 1
    bmesh.update_edit_mesh(obj.data)
    return n


def heights_along(obj, d=(0, 0, 1)):
    co = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    m = np.array(obj.matrix_world)
    w = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
    h = w @ np.array(d)
    return float(h.min()), float(h.max())


# ---------------------------------------------------------------------------
# Faux layout : exécute le code de dessin des panneaux et valide propriétés et opérateurs
# ---------------------------------------------------------------------------

class FakeLayout:
    def __getattr__(self, name):
        def fn(*args, **kw):
            if name in ("prop", "prop_search") and len(args) >= 2:
                data, prop = args[0], args[1]
                if prop not in data.bl_rna.properties:
                    raise AttributeError(f"Propriété inconnue {type(data).__name__}.{prop}")
            if name == "operator":
                mod, opn = args[0].split(".")
                if not hasattr(getattr(bpy.ops, mod), opn):
                    raise AttributeError(f"Opérateur inconnu {args[0]}")
            return FakeLayout()
        return fn

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)


def draw_all_panels():
    from bl_ext.user_default.mio_chain_studio import ui
    errors = []
    for cls in ui.CLASSES:
        class Fake(ui._Base):
            pass
        fake = Fake()
        fake.layout = FakeLayout()
        fake.step = getattr(cls, "step", None)
        try:
            cls.draw(fake, bpy.context)
            if fake.step:
                cls.draw_header(fake, bpy.context)
        except Exception:
            errors.append(f"{cls.__name__}: {traceback.format_exc().splitlines()[-1]}")
    return errors


# ---------------------------------------------------------------------------
# Données synthétiques
# ---------------------------------------------------------------------------

SVG_COMPLEXE = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120" viewBox="0 0 200 120">
  <path id="cadre" fill="#c0c0c0" d="M0 0 L20 0 L40 0 L60 0 L80 0 L100 0 L100 20 L100 40 L100 60 L80 60 L60 60 L40 60 L20 60 L0 60 L0 40 L0 20 Z M10 10 L30 10 L50 10 L50 30 L50 50 L30 50 L10 50 L10 30 Z"/>
  <path id="goutte" fill="#ffd700" d="M120 10 C150 0 180 20 170 50 C160 80 130 90 120 60 L120 40 L120 20 Z M135 30 C145 25 155 35 150 45 C145 55 135 50 135 40 Z"/>
  <path id="lettre_e" fill="#000000" d="M10 70 L60 70 L60 80 L20 80 L20 90 L50 90 L50 100 L20 100 L20 110 L60 110 L60 118 L10 118 Z"/>
</svg>"""

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60" viewBox="0 0 100 60">
  <rect id="fond" x="0" y="0" width="100" height="60" fill="#c0c0c0"/>
  <path id="lettre" d="M10 10 H40 V50 H10 Z M20 20 V40 H30 V20 Z" fill="#000000"/>
  <circle id="medaille" cx="70" cy="30" r="15" fill="#ffd700"/>
  <rect id="detail" x="62" y="26" width="16" height="8" fill="#000"/>
</svg>"""


def make_png(path, color, size=64):
    img = bpy.data.images.new(os.path.basename(path), size, size, alpha=True)
    img.pixels.foreach_set(np.tile(np.array(color, dtype=np.float32), size * size))
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def make_chain_obj(path):
    me = bpy.data.meshes.new("chaine_test")
    bm = bmesh.new()
    for i in range(12):
        t = math.pi * i / 11
        res = bmesh.ops.create_circle(bm, cap_ends=True, radius=0.006, segments=8)
        for v in res["verts"]:
            v.co = Vector((v.co.x + 0.1 * math.cos(t), -0.12 * math.sin(t), v.co.y + 0.55 - 0.2 * math.sin(t)))
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.new(name="UVMap")
    for i, d in enumerate(uv.data):
        d.uv = ((i % 7) / 7, (i % 5) / 5)
    mat = bpy.data.materials.new("Or_Chaine")
    mat.diffuse_color = (1.0, 0.7, 0.1, 1.0)
    me.materials.append(mat)
    obj = bpy.data.objects.new("chaine_test", me)
    bpy.context.scene.collection.objects.link(obj)
    select_only(obj)
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, export_materials=True, export_uv=True)
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(me)


def make_display(path):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_display.py")
    subprocess.run([sys.executable, "-I", script, "--", path, os.path.join(WORK, "absent")], check=True,
                   capture_output=True, timeout=300)


# ---------------------------------------------------------------------------

def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    print(f"Blender {bpy.app.version_string}")
    bpy.ops.preferences.addon_enable(module=SOLLUMZ)
    bpy.ops.preferences.addon_enable(module=ADDON)
    from bl_ext.user_default.mio_chain_studio import (sollumz_bridge as szb, teef, svg, rigging, export as exp,
                                                     colors, presets, materials, display, status)
    prefs = bpy.context.preferences.addons[ADDON].preferences
    prefs.presets_dir = os.path.join(WORK, "presets")
    check("Addon et Sollumz actifs", hasattr(bpy.ops.mio_chain, "svg_prepare") and szb.detect(refresh=True).ok,
          szb.detect().errors)
    check("Version Sollumz vérifiée (2.9.0)", szb.detect().version == (2, 9, 0), szb.detect().version)
    external = {o.name for o in bpy.data.objects}
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(WORK, "projet.blend"))

    # Teef ---------------------------------------------------------------------
    print("\n[Teef]")
    broken = os.path.join(WORK, "Teef_incomplet")
    shutil.copytree(TEEF, broken)
    os.remove(os.path.join(broken, "teef_000_u", "teef_spec_000.dds"))
    prefs.teef_dir = broken
    check("Dossier incomplet refusé", run("teef_check") != {"FINISHED"})
    prefs.teef_dir = os.path.join(WORK, "inexistant")
    check("Dossier absent refusé", run("teef_check") != {"FINISHED"})
    prefs.teef_dir = TEEF
    check("Dossier Teef vérifié", run("teef_check") == {"FINISHED"})
    ok, info, issues = teef.check_folder(TEEF)
    check("YFT : 128 os, SKEL_ROOT 0, SKEL_Spine3 38 tag 24818", ok and info["yft"]["bones"] == 128, issues)
    check("YDD : teef_012_u, LOD High/Medium/Low, sans squelette",
          info["ydd"]["drawables"] == ["teef_012_u"] and info["ydd"]["lods"] == ["High", "Medium", "Low"]
          and not info["ydd"]["skeleton"])
    check("Charger les références Teef", run("teef_load") == {"FINISHED"})
    p = proj()
    root = p.ref_root
    check("Squelette importé par Sollumz (squelette externe)", root and root.type == "ARMATURE"
          and len(root.data.bones) == 128 and root.data.bones[0].name == "SKEL_ROOT"
          and root.data.bones.find("SKEL_Spine3") == 38 and root.data.bones["SKEL_Spine3"].bone_properties.tag == 24818)
    check("Mesh de référence « SKEL_ROOT » sous le drawable", p.ref_model and p.ref_model.name == "SKEL_ROOT"
          and p.ref_model.type == "MESH" and p.ref_model.parent == p.ref_drawable)
    check("Références : LOD High, Medium, Low", all(szb.lod_meshes(p.ref_model)[l] for l in
                                                     ("sollumz_high", "sollumz_medium", "sollumz_low")))
    check("Second chargement refusé sans « Recharger »", run("teef_load") != {"FINISHED"})
    n_ref = len(teef.reference_objects(p))
    scene = bpy.data.scenes["Scene"]
    check("Structure teef_000_u > teef_012_u > SKEL_ROOT dans la Scene Collection",
          p.ref_root.name == "teef_000_u" and p.ref_drawable.name == "teef_012_u" and p.ref_drawable.parent == p.ref_root
          and p.ref_root.name in scene.collection.objects and p.ref_drawable.name in scene.collection.objects
          and p.ref_root.data.name.startswith("teef_000_u.skel"), (p.ref_root.name, p.ref_drawable.name))
    check("Recharger sans doublon", run("teef_load", force=True) == {"FINISHED"} and len(teef.reference_objects(p)) == n_ref)
    check("Nom d'origine rétabli après rechargement", p.ref_model.name == "SKEL_ROOT")

    # 1. SVG -------------------------------------------------------------------------
    print("\n[1] SVG")
    svg_path = os.path.join(WORK, "pendentif.svg")
    open(svg_path, "w").write(SVG)
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=svg_path)
    by_name = {o.name: o for o in bpy.data.objects if o not in before}
    check("SVG importé en 4 courbes", len(by_name) == 4 and all(o.type == "CURVE" for o in by_name.values()), list(by_name))
    fond, lettre, medaille, detail = (by_name[n] for n in ("fond", "lettre", "medaille", "detail"))
    curves = [fond, lettre, medaille, detail]
    black_mat = lettre.data.materials[0]
    check("Matériau noir partagé détecté", svg.is_black(black_mat, p.black_threshold)
          and black_mat == detail.data.materials[0] and not svg.is_black(fond.data.materials[0], p.black_threshold))
    select_only(*curves)
    res = run("svg_detect")
    check("Même hauteur : pas d'ordre deviné", res == {"FINISHED"} and all(c.mio_svg_layer == 0 for c in curves))
    check("Préparation refusée tant que les couches ne sont pas affectées", run("svg_prepare") != {"FINISHED"})
    for obj, layer in ((fond, 1), (lettre, 2), (medaille, 2), (detail, 3)):
        select_only(obj)
        run("svg_assign", layer=layer)
    select_only(*curves)
    flat_faces = {c.name: len(bpy.data.meshes.new_from_object(c).polygons) for c in curves}
    check("Préparer les SVG sélectionnés", run("svg_prepare") == {"FINISHED"})
    res_objs = {o["mcs_svg_src"]: o for o in svg.results(p)}
    check("4 maillages produits", len(res_objs) == 4 and all(o.type == "MESH" for o in res_objs.values()))
    e = {k: heights_along(o) for k, o in res_objs.items()}
    check("Épaisseurs par défaut 0,02 / 0,01 / 0,005 m, espace 0",
          np.allclose([p.thickness_1, p.thickness_2, p.thickness_3, p.layer_gap], [0.02, 0.01, 0.005, 0.0], atol=1e-7))
    check("Couche 1 : 0,02 m, de 0 à 0,02", abs(e[fond.name][0]) < 1e-6 and abs(e[fond.name][1] - 0.02) < 1e-6, e[fond.name])
    check("Couche 2 : 0,01 m, posée sur la couche 1", abs(e[lettre.name][0] - 0.02) < 1e-6
          and abs(e[lettre.name][1] - 0.03) < 1e-6 and abs(e[medaille.name][0] - 0.02) < 1e-6, e[lettre.name])
    check("Couche 3 : 0,005 m, posée sur la couche 2", abs(e[detail.name][0] - 0.03) < 1e-6
          and abs(e[detail.name][1] - 0.035) < 1e-6, e[detail.name])
    lm = res_objs[lettre.name]
    check("Forme noire conservée (faces et trou)", lm.get("mcs_flat_faces") == flat_faces[lettre.name]
          and len(lm.data.polygons) > 2 * flat_faces[lettre.name])
    check("Matériau noir retiré de la lettre", all(m is None or not svg.is_black(m, p.black_threshold) for m in lm.data.materials))
    check("Matériaux non noirs conservés", list(res_objs[fond.name].data.materials) == list(fond.data.materials)
          and list(res_objs[medaille.name].data.materials) == list(medaille.data.materials))
    check("Forme uniquement noire : plus aucun matériau, géométrie gardée", len(res_objs[detail.name].data.materials) == 0
          and res_objs[detail.name].get("mcs_flat_faces") == flat_faces[detail.name])
    check("Plan du dessin conservé (XY)", np.allclose(np.array(res_objs[fond.name].dimensions[:2]),
                                                     np.array(fond.dimensions[:2]), atol=1e-6))
    check("Courbes sources conservées et masquées", all(c.name in bpy.data.objects and c.hide_get() for c in curves)
          and lettre.data.materials[0] == black_mat)
    check("Vérification interne sans erreur", not [i for i in svg.verify(p) if i[0] == "ERROR"])
    select_only(*res_objs.values())
    run("svg_prepare")
    select_only(*svg.results(p))
    run("svg_prepare")
    e2 = {o["mcs_svg_src"]: heights_along(o) for o in svg.results(p)}
    check("Deux clics de plus : ni doublon ni épaisseur cumulée", len(svg.results(p)) == 4 and e2 == e, e2)
    p.thickness_1 = 0.03
    select_only(*svg.results(p))
    run("svg_prepare")
    e3 = {o["mcs_svg_src"]: heights_along(o) for o in svg.results(p)}
    check("Épaisseur modifiée : couches recalculées", abs(e3[fond.name][1] - 0.03) < 1e-6 and abs(e3[lettre.name][0] - 0.03) < 1e-6)
    p.thickness_1 = 0.02
    p.stack_axis = "NEG_Z"
    select_only(*svg.results(p))
    run("svg_prepare")
    e4 = {o["mcs_svg_src"]: heights_along(o) for o in svg.results(p)}
    check("Direction −Z respectée", abs(e4[fond.name][0] + 0.02) < 1e-6 and abs(e4[fond.name][1]) < 1e-6, e4[fond.name])
    p.stack_axis = "POS_Z"
    select_only(*svg.results(p))
    run("svg_prepare")
    for c, z in ((fond, 0.0), (lettre, 0.01), (medaille, 0.01), (detail, 0.02)):
        c.hide_set(False)
        c.location.z = z
        c.mio_svg_layer = 0
    bpy.context.view_layer.update()
    select_only(*curves)
    run("svg_detect")
    check("Hauteurs distinctes : ordre détecté", [c.mio_svg_layer for c in curves] == [1, 2, 2, 3],
          [c.mio_svg_layer for c in curves])
    for c in curves:
        c.location.z = 0.0
    select_only(*curves)
    run("svg_prepare")
    check("Pendentif désigné automatiquement", sum(1 for x in p.parts if x.role == "PENDANT") == 4)

    # SVG réaliste : points alignés (faces de surface nulle), trous, courbes de Bézier.
    cpath = os.path.join(WORK, "complexe.svg")
    open(cpath, "w").write(SVG_COMPLEXE)
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=cpath)
    cx = {o.name: o for o in bpy.data.objects if o not in before}
    for name, layer in (("cadre", 1), ("goutte", 2), ("lettre_e", 3)):
        cx[name].mio_svg_layer = layer
    select_only(*cx.values())
    check("SVG réaliste (points alignés, trous) préparé", run("svg_prepare") == {"FINISHED"}, p.svg_report[-300:])
    check("Faces de surface nulle signalées et conservées", "surface nulle" in p.svg_report)
    ok_vol = True
    for obj in [o for o in svg.results(p) if o["mcs_svg_src"] in cx]:
        hmin, hmax, n_back, back_area, n_front, wrong = svg.plane_faces(obj.data, obj.matrix_world, (0, 0, 1))
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        vol = bm.calc_volume(signed=True)
        closed = all(e.is_manifold for e in bm.edges)
        bm.free()
        ok_vol &= (wrong == 0 and closed and n_back == n_front == obj["mcs_flat_faces"]
                   and abs(vol - back_area * (hmax - hmin)) < 1e-9 + 1e-4 * abs(vol))
    check("Solides fermés, bien orientés, volume = surface × épaisseur", ok_vol)
    sigs = {o.name: (len(o.data.vertices), heights_along(o)) for o in svg.results(p)}
    cx["goutte"].hide_set(False)
    cx["goutte"].rotation_euler.x = 0.5
    bpy.context.view_layer.update()
    select_only(cx["goutte"])
    check("Courbe non plane : préparation refusée", run("svg_prepare") != {"FINISHED"})
    check("Échec : rien n'a été modifié", {o.name: (len(o.data.vertices), heights_along(o)) for o in svg.results(p)} == sigs
          and not any(o.get("mcs_svg_pending") for o in bpy.data.objects))
    cx["goutte"].rotation_euler.x = 0.0
    bpy.context.view_layer.update()
    real_verify = svg.verify
    svg.verify = lambda proj, objs=None: [("ERROR", "échec simulé après construction", "")]
    n_obj, n_mesh = len(bpy.data.objects), len(bpy.data.meshes)
    select_only(*[o for o in svg.results(p) if o["mcs_svg_src"] in cx])
    try:
        res = run("svg_prepare")
    finally:
        svg.verify = real_verify
    check("Échec après construction : nouveaux maillages retirés, anciens gardés", res != {"FINISHED"}
          and len(bpy.data.objects) == n_obj and len(bpy.data.meshes) == n_mesh
          and {o.name: (len(o.data.vertices), heights_along(o)) for o in svg.results(p)} == sigs)
    for obj in [o for o in svg.results(p) if o["mcs_svg_src"] in cx]:
        for i in reversed(range(len(p.parts))):
            if p.parts[i].obj == obj:
                p.parts.remove(i)
        bpy.data.objects.remove(obj)
    for c in cx.values():
        bpy.data.objects.remove(c)
    check("Retour aux 4 maillages du premier SVG", len(svg.results(p)) == 4)

    # 2. Chaîne -----------------------------------------------------------------------
    print("\n[2] Chaîne")
    obj_path = os.path.join(WORK, "chaine.obj")
    make_chain_obj(obj_path)
    p.chain_path = obj_path
    check("Importer ma chaîne", run("chain_import") == {"FINISHED"})
    chain = [x.obj for x in p.parts if x.role == "CHAIN"][0]
    check("Matériau et UV importés conservés", chain.data.materials and chain.data.materials[0].name.startswith("Or_Chaine")
          and len(chain.data.uv_layers) == 1)
    uv_chain = np.array([d.uv[:] for d in chain.data.uv_layers[0].data])
    n_obj = len(bpy.data.objects)
    run("chain_import")
    check("Ré-import : remplacement sans doublon", len(bpy.data.objects) == n_obj
          and sum(1 for x in p.parts if x.role == "CHAIN") == 1)
    chain = [x.obj for x in p.parts if x.role == "CHAIN"][0]
    p.chain_path = os.path.join(WORK, "absente.obj")
    check("Import échoué : chaîne précédente conservée", run("chain_import") != {"FINISHED"}
          and [x.obj for x in p.parts if x.role == "CHAIN"] == [chain])
    bad = os.path.join(WORK, "vide.obj")
    open(bad, "w").write("# rien\n")
    p.chain_path = bad
    check("OBJ sans maillage : chaîne précédente conservée", run("chain_import") != {"FINISHED"}
          and chain.name in bpy.data.objects)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.02, minor_radius=0.003, location=(0.2, 0, 0.4))
    extra = bpy.context.active_object
    extra.name = "Chaine_Scene"
    select_only(extra)
    check("Chaîne de la scène ajoutée", run("part_add", role="CHAIN") == {"FINISHED"} and any(x.obj == extra for x in p.parts))
    idx = [i for i, x in enumerate(p.parts) if x.obj == extra][0]
    run("part_remove", index=idx)
    check("Retirer un composant ne supprime pas l'objet", "Chaine_Scene" in bpy.data.objects and not any(x.obj == extra for x in p.parts))

    # 3. Matériaux ---------------------------------------------------------------------
    print("\n[3] Matériaux")
    tex_dir = os.path.join(WORK, "tex")
    os.makedirs(tex_dir)
    diff = os.path.join(tex_dir, "argent_diff.png")
    make_png(diff, (0.8, 0.8, 0.85, 1))
    foreign = bpy.data.materials.new("Materiau_Utilisateur")
    fnode = foreign.node_tree.nodes.new("ShaderNodeTexImage")
    fnode.image = bpy.data.images.load(teef.path_of("bump"), check_existing=True)
    fnode.image.colorspace_settings.name = "sRGB"
    shared_before = fnode.image.colorspace_settings.name
    fond_mesh = [o for o in svg.results(p) if o["mcs_svg_src"] == fond.name][0]
    n_sel = edit_select_faces(fond_mesh, lambda f: f.normal.z > 0.9)
    check("Taille du cube par défaut : 0,2", abs(p.cube_size - 0.2) < 1e-7, p.cube_size)
    p.mat_kind, p.mat_mode, p.diffuse_path = "PED", "CUSTOM", diff
    me = fond_mesh.data
    bpy.ops.object.mode_set(mode="OBJECT")
    mi_before = np.array([q.material_index for q in me.polygons])
    sel = np.array([q.select for q in me.polygons])
    uv_before = np.array([d.uv[:] for d in me.uv_layers[0].data]) if me.uv_layers else None
    bpy.ops.object.mode_set(mode="EDIT")
    check("Appliquer aux faces sélectionnées (Ped)", run("apply_faces") == {"FINISHED"})
    bpy.ops.object.mode_set(mode="OBJECT")
    mat = me.materials[me.polygons[int(np.nonzero(sel)[0][0])].material_index]
    mi_after = np.array([q.material_index for q in me.polygons])
    check("Shader ped.sps", szb.material_shader(mat) == "ped.sps", szb.material_shader(mat))
    vals = {n.name: [round(o.default_value, 5) for o in n.outputs] for n in mat.node_tree.nodes
            if n.bl_idname == "SOLLUMZ_NT_SHADER_Parameter"}
    check("Value Parameters de base posés (Ped)", vals.get("specularIntensityMult") == [1997.0]
          and vals.get("specularFalloffMult") == [1997.0] and vals.get("specularFresnel") == [0.45]
          and vals.get("bumpiness") == [1.3] and vals.get("umGlobalParams") == [0.0025, 0.0025, 7.0, 7.0]
          and vals.get("detailSettings") == [0.0, 0.0, 24.0] and vals.get("StubbleControl") == [2.0, 0.6]
          and "emissiveMultiplier" not in vals, vals)
    check("Matériau sur les seules faces sélectionnées", (mi_after[~sel] == mi_before[~sel]).all()
          and all(me.materials[i] == mat for i in mi_after[sel]), n_sel)
    nodes = mat.node_tree.nodes
    check("Textures : Diffuse, Bump Teef, Spec Teef", nodes["DiffuseSampler"].image.filepath.endswith("argent_diff.png")
          and szb.texture_name_of_image(nodes["BumpSampler"].image) == "teef_normal_001"
          and szb.texture_name_of_image(nodes["SpecSampler"].image) == "teef_spec_000")
    check("Embedded : Bump et Spec oui, Diffuse non", nodes["BumpSampler"].texture_properties.embedded
          and nodes["SpecSampler"].texture_properties.embedded and not nodes["DiffuseSampler"].texture_properties.embedded)
    check("BumpSampler en Non-Color", nodes["BumpSampler"].image.colorspace_settings.name == "Non-Color")
    check("Image partagée non modifiée (autre matériau)", fnode.image.colorspace_settings.name == shared_before
          and fnode.image != nodes["BumpSampler"].image)
    uv0 = np.array([d.uv[:] for d in me.uv_layers["UVMap 0"].data])
    loops_sel = materials.selected_loops(me, sel)
    check("Cube Projection : UV des autres faces intactes", uv_before is None or np.allclose(uv0[~loops_sel], uv_before[~loops_sel]))
    check("Cube Projection : UV des faces choisies recalculées", uv_before is None or not np.allclose(uv0[loops_sel], uv_before[loops_sel]))
    n_mats = len(bpy.data.materials)
    edit_select_faces(fond_mesh, lambda f: f.normal.z < -0.9)
    run("apply_faces")
    check("Mêmes réglages : matériau réutilisé", len(bpy.data.materials) == n_mats)
    p.mat_kind = "EMISSIVE"
    med = [o for o in svg.results(p) if o["mcs_svg_src"] == medaille.name][0]
    edit_select_faces(med, lambda f: True)
    check("Appliquer (Ped Emissive)", run("apply_faces") == {"FINISHED"})
    bpy.ops.object.mode_set(mode="OBJECT")
    emat = med.data.materials[med.data.polygons[0].material_index]
    evals = {n.name: [round(o.default_value, 5) for o in n.outputs] for n in emat.node_tree.nodes
             if n.bl_idname == "SOLLUMZ_NT_SHADER_Parameter"}
    check("Value Parameters de base posés (Ped Emissive)", evals.get("emissiveMultiplier") == [1.0]
          and evals.get("specularIntensityMult") == [1997.0] and evals.get("bumpiness") == [1.3], evals)
    check("Shader ped_emissive.sps + emissiveMultiplier + UVMap 1", szb.material_shader(emat) == "ped_emissive.sps"
          and szb.param_node(emat, "emissiveMultiplier") is not None and "UVMap 1" in med.data.uv_layers)
    p.mat_kind = "PED"
    for o, r in [(o, r) for o, r in __import__("bl_ext.user_default.mio_chain_studio.utils", fromlist=["x"]).part_meshes(p)]:
        if o == med:
            continue
        edit_select_faces(o, lambda f: True)
        run("apply_faces")
    bpy.ops.object.mode_set(mode="OBJECT")
    check("Statut 3 terminé (toutes les faces couvertes)", status.step3(bpy.context, p)[0] == "Terminé",
          status.step3(bpy.context, p)[1])
    p.diffuse_path = os.path.join(tex_dir, "absente.png")
    edit_select_faces(fond_mesh, lambda f: True)
    check("Texture manquante : refus explicite", run("apply_faces") != {"FINISHED"})
    bpy.ops.object.mode_set(mode="OBJECT")
    p.diffuse_path = diff

    # 4. Presets ----------------------------------------------------------------------
    print("\n[4] Value Parameters et presets")
    select_only(fond_mesh)
    fond_mesh.active_material_index = list(fond_mesh.data.materials).index(mat)
    params = dict(materials.value_parameters(mat))
    check("Value Parameters du shader affichés", "specularIntensityMult" in params and "emissiveMultiplier" not in params)
    check("emissiveMultiplier pour le shader émissif", "emissiveMultiplier" in dict(materials.value_parameters(emat)))
    params["specularIntensityMult"].outputs[0].default_value = 0.42
    p.new_preset_name = "argent"
    check("Enregistrer comme preset", run("preset_save") == {"FINISHED"} and "argent" in presets.names())
    data = presets.load("argent")
    check("Preset : shader, textures, Embedded, espaces, paramètres", data["shader"] == "ped.sps"
          and data["textures"]["BumpSampler"]["embedded"] and data["textures"]["BumpSampler"]["colorspace"] == "Non-Color"
          and abs(data["params"]["specularIntensityMult"][0] - 0.42) < 1e-6 and presets.status(data)[0])
    p.preset_name = "argent"
    p.new_preset_name = "or"
    check("Dupliquer un preset", run("preset_duplicate") == {"FINISHED"} and "or" in presets.names())
    p.preset_name = "or"
    d2 = presets.load("or")
    d2["textures"]["DiffuseSampler"]["path"] = os.path.join(tex_dir, "deplacee.png")
    presets.save("or", d2)
    check("Preset incomplet signalé", not presets.status(presets.load("or"))[0])
    check("Preset incomplet non appliqué", run("preset_apply") != {"FINISHED"})
    presets.relocate("or", "DiffuseSampler", diff)
    check("Relocaliser rend le preset complet", presets.status(presets.load("or"))[0])
    params["specularIntensityMult"].outputs[0].default_value = 5.0
    check("Réappliquer les Value Parameters de base", run("params_base") == {"FINISHED"}
          and params["specularIntensityMult"].outputs[0].default_value == 1997.0)
    params["specularIntensityMult"].outputs[0].default_value = 0.1
    p.preset_name = "argent"
    check("Appliquer un preset", run("preset_apply") == {"FINISHED"}
          and abs(params["specularIntensityMult"].outputs[0].default_value - 0.42) < 1e-6)
    p.mat_mode, p.preset_name = "PRESET", "argent"
    edit_select_faces(fond_mesh, lambda f: True)
    check("Mode Preset appliqué aux faces", run("apply_faces") == {"FINISHED"})
    bpy.ops.object.mode_set(mode="OBJECT")
    p.mat_mode = "CUSTOM"
    p.preset_name = "or"
    check("Supprimer un preset", run("preset_delete") == {"FINISHED"} and "or" not in presets.names())
    check("Presets dans un dossier persistant", os.path.isfile(os.path.join(WORK, "presets", "argent.json")))

    # 4b. Normal map par défaut -------------------------------------------------------------
    print("\n[4b] Normal map par défaut")
    prefs.default_bump = ""
    check("Sans réglage : teef_normal_001.dds reste la normal map par défaut",
          os.path.basename(materials.default_bump()[0]) == "teef_normal_001.dds" and not materials.default_bump()[1])
    teef_users = materials.project_teef_bump_materials(p)
    check("Matériaux du projet sur teef_normal_001.dds repérés", len(teef_users) >= 2, [m.name for m in teef_users])
    check("Choisir un fichier qui n'est pas un DDS : refus", run("default_bump_choose", filepath=diff) != {"FINISHED"}
          and not prefs.default_bump)
    src_dds = os.path.join(WORK, "a_deplacer", "diamants_test.dds")
    os.makedirs(os.path.dirname(src_dds))
    shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(szb.__file__)), "sollumz", "tests", "assets", "cwxml",
                                 "txd", "test_image.dds"), src_dds)
    check("Choisir ma normal map par défaut (.dds)", run("default_bump_choose", filepath=src_dds) == {"FINISHED"})
    kept = bpy.path.abspath(prefs.default_bump)
    check("Copiée dans le dossier de configuration (l'original peut être déplacé)",
          os.path.isfile(kept) and not os.path.samefile(kept, src_dds) and os.path.basename(kept) == "diamants_test.dds")
    shutil.rmtree(os.path.dirname(src_dds))
    check("Original supprimé : la normal map par défaut reste disponible", materials.default_bump() == (kept, True))
    p.mat_kind, p.mat_mode, p.bump_path = "PED", "CUSTOM", ""
    spec = materials.spec_from_ui(p)
    check("Mode Personnalisé sans Bump : votre normal map, en Non-Color et Embedded",
          os.path.samefile(spec["textures"]["BumpSampler"]["path"], kept)
          and spec["textures"]["BumpSampler"]["colorspace"] == "Non-Color" and spec["textures"]["BumpSampler"]["embedded"])
    p.mat_mode, p.preset_name = "PRESET", "argent"
    check("Preset qui utilise teef_normal_001.dds : votre normal map à la place (fichier du preset inchangé)",
          os.path.samefile(materials.spec_from_ui(p)["textures"]["BumpSampler"]["path"], kept)
          and materials.is_teef_bump(presets.load("argent")["textures"]["BumpSampler"]["path"]))
    p.mat_mode = "CUSTOM"
    check("Mettre ma normal map sur le projet", run("default_bump_apply") == {"FINISHED"})
    bumps = {m.name: m.node_tree.nodes["BumpSampler"] for m in teef_users}
    check("Matériaux du projet : BumpSampler = votre normal map, Non-Color, Embedded, plus aucun Teef",
          all(os.path.samefile(bpy.path.abspath(n.image.filepath), kept) and n.image.colorspace_settings.name == "Non-Color"
              and n.texture_properties.embedded for n in bumps.values())
          and not materials.project_teef_bump_materials(p), {k: n.image.filepath for k, n in bumps.items()})
    check("Image partagée d'un autre matériau toujours intacte", fnode.image.colorspace_settings.name == shared_before)
    errs = draw_all_panels()
    check("Panneaux dessinés avec la normal map par défaut", not errs, errs)

    # 5. Color Attributes ------------------------------------------------------------------
    print("\n[5] Color Attributes")
    chain.data.color_attributes.new("Color 1", "FLOAT_COLOR", "POINT")
    chain.data.attributes.new("mon_attribut", "FLOAT", "POINT")
    p.color_targets = "PARTS"
    check("Configurer les Color Attributes", run("colors_configure") == {"FINISHED"})
    from bl_ext.user_default.mio_chain_studio.utils import part_meshes
    objs = [o for o, r in part_meshes(p)]
    ok5 = True
    for o in objs:
        c1, c2 = o.data.color_attributes.get("Color 1"), o.data.color_attributes.get("Color 2")
        ok5 &= bool(c1 and c2 and c1.domain == c2.domain == "CORNER" and c1.data_type == c2.data_type == "BYTE_COLOR")
        ok5 &= bool((colors.read_bytes(c1) == [255, 128, 0, 255]).all() and (colors.read_bytes(c2) == [0, 0, 0, 0]).all())
    check("Color 1 #FF8000 α1 et Color 2 #000000 α0, Face Corner / Byte Color", ok5)
    c1 = chain.data.color_attributes["Color 1"]
    check("Conversion : valeur linéaire de 0x80 ≈ 0,2158", abs(c1.data[0].color[1] - 0.2158605) < 1e-3, c1.data[0].color[:])
    check("Mauvais type remplacé, autres attributs conservés", "mon_attribut" in chain.data.attributes
          and len([a for a in chain.data.color_attributes if a.name.startswith("Color 1")]) == 1)
    n_attr = sum(len(o.data.attributes) for o in objs)
    run("colors_configure")
    check("Clic répété : pas de doublon d'attribut", sum(len(o.data.attributes) for o in objs) == n_attr)
    c1.data[0].color_srgb = (1.0, 0xBA / 255, 1.0, 1.0)
    check("Peinture existante : refus sans confirmation", run("colors_configure") != {"FINISHED"}
          and colors.read_bytes(c1)[0].tolist() == [255, 186, 255, 255])

    # 6. Glow -----------------------------------------------------------------------------
    print("\n[6] Glow")
    select_only(chain)
    check("Activer Color 1 et passer en Vertex Paint", run("glow_paint_mode") == {"FINISHED"}
          and bpy.context.mode == "PAINT_VERTEX" and chain.data.color_attributes.active_color.name == "Color 1")
    bpy.ops.object.mode_set(mode="OBJECT")
    painted = int((colors.read_bytes(c1) == [255, 186, 255, 255]).all(axis=1).sum())
    check("Note glow affichée en mode émissif", status.uses_glow(p) and "#FFBAFF" in colors.GLOW_NOTE)

    # 7. Rigging --------------------------------------------------------------------------
    print("\n[7] Rigging")
    g = chain.vertex_groups.new(name="SKEL_Neck_1")
    g.add([0, 1, 2], 0.7, "REPLACE")
    src_sig = [(o.name, len(o.data.vertices), len(o.vertex_groups)) for o in objs]
    check("Rigger sur SKEL_Spine3", run("rig_spine3") == {"FINISHED"})
    final = p.final_obj
    weights_ok = all(len(v.groups) == 1 and v.groups[0].weight == 1.0 for v in final.data.vertices)
    check("Un seul mesh final, groupe SKEL_Spine3 uniquement", final and [x.name for x in final.vertex_groups] == ["SKEL_Spine3"])
    check("Poids 1 sur SKEL_Spine3 pour tous les sommets", weights_ok and len(final.data.vertices) == sum(len(o.data.vertices) for o in objs))
    mod = [m for m in final.modifiers if m.type == "ARMATURE"]
    check("Liaison au squelette masculin", len(mod) == 1 and mod[0].object == p.ref_root)
    check("Sources intactes (poids résiduels seulement sur la source)", src_sig == [(o.name, len(o.data.vertices), len(o.vertex_groups)) for o in objs])
    from bl_ext.user_default.mio_chain_studio.utils import world_bounds
    b1, b2 = world_bounds(objs), world_bounds([final])
    check("Placement visuel conservé", np.allclose(b1[0], b2[0], atol=1e-6) and np.allclose(b1[1], b2[1], atol=1e-6))
    fc1 = final.data.color_attributes.get("Color 1")
    check("Peinture du glow conservée (étape 5 non relancée)", fc1 is not None and
          int((colors.read_bytes(fc1) == [255, 186, 255, 255]).all(axis=1).sum()) == painted)
    check("Matériaux et UV conservés", {m.name for o in objs for m in o.data.materials if m} <= {m.name for m in final.data.materials if m}
          and "UVMap 0" in final.data.uv_layers)
    n_final = sum(1 for o in bpy.data.objects if o.get("mcs_final"))
    run("rig_spine3")
    check("Clic répété : toujours un seul mesh final", sum(1 for o in bpy.data.objects if o.get("mcs_final")) == n_final == 1
          and p.final_obj.name == "mio_chain")
    final = p.final_obj
    check("Weight Paint", run("weight_paint") == {"FINISHED"} and bpy.context.mode == "PAINT_WEIGHT")
    bpy.ops.object.mode_set(mode="OBJECT")

    # 8. Structure et export ------------------------------------------------------------
    print("\n[8] Structure d'export")
    root, drawable = p.ref_root, p.ref_drawable
    check("Structure de la capture : teef_000_u > teef_012_u > mio_chain",
          root.name == "teef_000_u" and drawable.name == "teef_012_u" and final.name == "mio_chain"
          and final.parent == drawable and [c.name for c in drawable.children] == ["mio_chain"],
          (root.name, drawable.name, [c.name for c in drawable.children]))
    check("SKEL_ROOT (mesh) retiré, os SKEL_ROOT et armature intacts", "SKEL_ROOT" not in bpy.data.objects
          and root.data.bones[0].name == "SKEL_ROOT" and len(root.data.bones) == 128)
    check("mio_chain dans la Scene Collection, type Sollumz Drawable Model", final.name in scene.collection.objects
          and final.sollum_type == szb.MODEL)
    mods = [m for m in final.modifiers if m.type == "ARMATURE"]
    check("mio_chain lié à l'armature teef_000_u", len(mods) == 1 and mods[0].object == root)
    lods = szb.lod_meshes(final)
    check("LOD : High = mio_chain, Medium et Low vides", lods["sollumz_high"] == final.data and lods["sollumz_medium"] is None
          and lods["sollumz_low"] is None)
    ref_lods = set(json.loads(p.ref_lod_names))
    check("Aucune ancienne géométrie dans les LOD", ref_lods and not ({m.name for m in lods.values() if m} & ref_lods), ref_lods)
    final_world = final.matrix_world.copy()
    check("Placer à nouveau : LOD réappliqués, pas de doublon", run("export_place") == {"FINISHED"}
          and [c.name for c in drawable.children] == ["mio_chain"])
    n_ref = len(teef.reference_objects(p))
    check("Recharger les références : mio_chain replacé dans la nouvelle structure",
          run("teef_load", force=True) == {"FINISHED"} and p.final_obj.parent == p.ref_drawable
          and p.ref_root.name == "teef_000_u" and p.ref_drawable.name == "teef_012_u"
          and [c.name for c in p.ref_drawable.children] == ["mio_chain"] and len(teef.reference_objects(p)) == n_ref
          and "SKEL_ROOT" not in bpy.data.objects and p.ref_root.data.name == "teef_000_u.skel",
          ([o.name for o in teef.reference_objects(p)], p.ref_root.data.name))
    root, drawable = p.ref_root, p.ref_drawable
    check("Position monde conservée (pas de double transformation)",
          max(abs(a - b) for ra, rb in zip(final.matrix_world, final_world) for a, b in zip(ra, rb)) < 1e-6)
    run("export_check")
    errors = [i.message for i in p.report if i.severity == "ERROR"]
    check("Vérification avant export : aucune erreur bloquante", not errors, errors)
    p.export_dir = os.path.join(WORK, "export")
    check("Exporter avec Sollumz", run("export") == {"FINISHED"} and p.last_export_ok, json.loads(p.last_export or "{}").get("errors"))
    xml_path = os.path.join(p.export_dir, "teef_000_u.ydd.xml")
    xml = open(xml_path, encoding="utf-8").read() if os.path.isfile(xml_path) else ""
    check("YDD teef_000_u avec drawable teef_012_u", "<Name>teef_012_u</Name>" in xml)
    check("YDD : LOD High seulement", "DrawableModelsHigh" in xml and "DrawableModelsMedium" not in xml and "DrawableModelsLow" not in xml)
    check("YDD : 100 % des sommets sur l'os 38", any("à 100 % sur l'os 38" in line for line in json.loads(p.last_export)["lines"]))
    check("YDD : Bump (votre normal map par défaut) et Spec DDS intégrés",
          os.path.isfile(os.path.join(p.export_dir, "teef_000_u", "diamants_test.dds"))
          and "<Name>diamants_test</Name>" in xml and "teef_normal_001" not in xml
          and os.path.isfile(os.path.join(p.export_dir, "teef_000_u", "teef_spec_000.dds")))
    check("YDD : ancienne chaîne absente", xml.count("<VertexBuffer>") >= 1 and "teef_diff_012_a_uni" not in xml)
    check("YDD : Colour0 255 128 0 255 et glow 255 186 255 255", "255 128 0 255" in xml and "255 186 255 255" in xml)
    check("Statut 8 terminé", status.step8(bpy.context, p)[0] == "Terminé", status.step8(bpy.context, p)[1])
    p.lod_mode = "DUPLICATE"
    run("export")
    xml = open(xml_path, encoding="utf-8").read()
    check("LOD High copié en Medium et Low (affiché comme non optimisé)", "DrawableModelsMedium" in xml and "DrawableModelsLow" in xml
          and "non optimisée" in " ".join(i.message for i in p.report))
    p.lod_mode = "HIGH_ONLY"
    run("export")
    check("Retour au High seul", "DrawableModelsMedium" not in open(xml_path, encoding="utf-8").read())

    # Display -----------------------------------------------------------------------------
    print("\n[A] Display")
    os.makedirs(os.path.join(WORK, "Textures"))
    make_png(os.path.join(WORK, "Textures", "kria_texture.png"), (0.5, 0.1, 0.1, 1))
    os.makedirs(os.path.join(WORK, "displays", "v1"))
    display_path = os.path.join(WORK, "displays", "v1", "display.blend")
    make_display(display_path)
    p.display_path = os.path.join(WORK, "absent.blend")
    check("Display manquant : erreur", run("display_load") != {"FINISHED"})
    # Texture présente dans le projet UNIQUEMENT sous forme intégrée (packed) : le display doit la réutiliser.
    tmp_spec = os.path.join(WORK, "tmp_spec", "spec_blanc.png")
    os.makedirs(os.path.dirname(tmp_spec))
    make_png(tmp_spec, (0.9, 0.9, 0.9, 1))
    packed_spec = bpy.data.images.load(tmp_spec)
    packed_spec.pack()
    packed_spec.use_fake_user = True
    shutil.rmtree(os.path.dirname(tmp_spec))
    p.display_path = display_path
    check("1. Charger le display (un seul clic)", run("display_load") == {"FINISHED"} and p.preview_scene is not None)
    ps = p.preview_scene
    mk = [o for o in ps.objects if o.name.startswith("Repere_Cou")][0]
    check("Bijou placé automatiquement sur le vide « Repere_Cou » du display",
          len(display.preview_objects(p, "copy")) == len(part_meshes(p))
          and (p.preview_marker.matrix_world.translation - mk.matrix_world.translation).length < 1e-6)
    check("Caméra et réglages du display repris", p.render_camera and ps.cycles.samples == 128)
    kria = [i for i in bpy.data.images if i.name.startswith("kria_texture")][0]
    check("Texture en chemin relatif au display retrouvée", os.path.samefile(bpy.path.abspath(kria.filepath),
          os.path.join(WORK, "Textures", "kria_texture.png")), kria.filepath)
    argent = [i for i in bpy.data.images if i.name.startswith("argent_diff") and "Ailleurs" not in i.filepath
              and i.users and any(n.image == i for m in bpy.data.materials if m.name.startswith("Bijou_Ancien")
                                  for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage")]
    check("Texture introuvable reprise de votre projet (même fichier)", argent and os.path.samefile(
          bpy.path.abspath(argent[0].filepath), os.path.join(WORK, "tex", "argent_diff.png")))
    spec_users = [n for m in bpy.data.materials if m.name.startswith("Bijou_Ancien")
                  for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image
                  and n.image.name.startswith("spec_blanc")]
    check("Texture introuvable reprise de votre projet même si elle y est intégrée (packed)",
          spec_users and all(n.image == packed_spec for n in spec_users), [n.image.name for n in spec_users])
    missing = json.loads(p.display_missing)
    check("Seule la texture vraiment absente est signalée", len(missing) == 1 and "velours" in missing[0], missing)
    find_rna = bpy.ops.mio_chain.display_find_textures.get_rna_type().properties
    relink_rna = bpy.ops.mio_chain.display_relink_texture.get_rna_type().properties
    check("Sélecteurs de textures : fichiers DDS affichés (filtre images + *.dds), dossiers aussi",
          ".dds" in bpy.path.extensions_image
          and all(r["filter_image"].default and r["filter_folder"].default and "*.dds" in r["filter_glob"].default
                  for r in (find_rna, relink_rna)))
    velours = [i for i in bpy.data.images if i.name.startswith("velours")][0]
    autre_nom = os.path.join(WORK, "autres_noms", "velours_v2.png")
    os.makedirs(os.path.dirname(autre_nom))
    make_png(autre_nom, (0.3, 0, 0.3, 1))
    check("« Choisir… » : fichier refusé s'il n'est pas une image", run("display_relink_texture", image_name=velours.name,
          filepath=os.path.join(WORK, "projet.blend")) != {"FINISHED"})
    check("« Choisir… » : texture reliée à un fichier d'un autre nom", run("display_relink_texture", image_name=velours.name,
          filepath=autre_nom) == {"FINISHED"} and json.loads(p.display_missing) == []
          and os.path.samefile(bpy.path.abspath(velours.filepath), autre_nom) and velours.size[0] == 64)
    if TEEF:
        dds_img = bpy.data.images.new("essai_dds", 4, 4)
        dds_img.source = "FILE"
        dds_img.filepath = os.path.join(WORK, "absent", "spec.dds")
        mat_dds = bpy.data.materials.new("Essai_DDS")
        mat_dds.use_nodes = True
        mat_dds.node_tree.nodes.new("ShaderNodeTexImage").image = dds_img
        p.display_image_names = json.dumps(json.loads(p.display_image_names) + [dds_img.name])
        check("« Choisir… » : un vrai DDS de Teef est relié et lu par Blender", run("display_relink_texture",
              image_name=dds_img.name, filepath=os.path.join(TEEF, "teef_000_u", "teef_spec_000.dds")) == {"FINISHED"}
              and dds_img.size[0] > 0, tuple(dds_img.size))
        bpy.data.materials.remove(mat_dds)
        bpy.data.images.remove(dds_img)
    velours.filepath = os.path.join(WORK, "absent", "velours.png")
    p.display_missing = json.dumps(display.missing_display_images(p))
    os.makedirs(os.path.join(WORK, "autres", "sous_dossier"))
    make_png(os.path.join(WORK, "autres", "sous_dossier", "velours.png"), (0.2, 0, 0.3, 1))
    check("Rechercher les textures manquantes (dossier choisi)", run("display_find_textures",
          directory=os.path.join(WORK, "autres")) == {"FINISHED"} and json.loads(p.display_missing) == [],
          p.display_missing)
    check("2. Déplacer le bijou : repère sélectionné dans le display", run("preview_move") == {"FINISHED"}
          and bpy.context.window.scene == ps and ps.view_layers[0].objects.active == p.preview_marker)
    p.preview_marker.location.x += 0.1
    check("Mémoriser cette position", run("marker_save") == {"FINISHED"})
    check("Revenir au projet", run("back_to_project") == {"FINISHED"} and bpy.context.window.scene.name == "Scene")
    with bpy.context.temp_override(scene=ps, view_layer=ps.view_layers[0], active_object=mk):
        check("Option : repère sur l'objet actif", run("marker_set", source="ACTIVE") == {"FINISHED"})
    check("Actualiser la chaîne sur le display", run("preview_refresh", show=False) == {"FINISHED"})
    n = len(display.preview_objects(p, "copy"))
    n_mesh = len(bpy.data.meshes)
    run("preview_refresh", show=False)
    run("preview_refresh", show=False)
    check("Actualiser : pas de doublon", len(display.preview_objects(p, "copy")) == n and len(bpy.data.meshes) == n_mesh)

    # « Mettre la chaîne sur le display » sans bijou désigné : la sélection du projet est posée.
    saved_parts = [(pt.obj, pt.role) for pt in p.parts]
    chain_obj = [o for o, r in part_meshes(p) if r == "CHAIN"][0]
    p.parts.clear()
    p.preview_parts.clear()
    select_only()
    check("Rien de sélectionné ni désigné : refus clair", run("preview_refresh") != {"FINISHED"}
          and display.preview_sources(p) == [])
    select_only(chain_obj)
    ok = run("preview_refresh") == {"FINISHED"}
    copies = display.preview_objects(p, "copy")
    check("Mettre la chaîne sur le display : la chaîne sélectionnée y est posée",
          ok and [c["mcs_preview_src"] for c in copies] == [chain_obj.name], [c.get("mcs_preview_src") for c in copies])
    check("… dans la scène du display, qui s'affiche", bpy.context.window.scene == ps
          and all(c.name in ps.objects for c in copies))
    status.invalidate()
    check("Statut de l'aperçu : chaîne posée", status.step_display(bpy.context, p)[0] == "Terminé",
          status.step_display(bpy.context, p)[1])
    check("Revenir au projet (après la pose)", run("back_to_project") == {"FINISHED"}
          and bpy.context.window.scene.name == "Scene")
    select_only()
    check("Actualiser sans sélection : la chaîne mémorisée reste posée", run("preview_refresh", show=False) == {"FINISHED"}
          and [c["mcs_preview_src"] for c in display.preview_objects(p, "copy")] == [chain_obj.name])
    for obj, role in saved_parts:
        item = p.parts.add()
        item.obj, item.role = obj, role
    run("preview_refresh", show=False)
    check("Bijou désigné à l'étape 2 : il redevient la source (chaîne + pendentif)",
          len(display.preview_objects(p, "copy")) == n)
    copy = display.preview_objects(p, "copy")[0]
    src = bpy.data.objects[copy["mcs_preview_src"]]
    check("Copie indépendante (maillage et matériaux)", copy.data != src.data
          and not set(copy.data.materials) & set(src.data.materials))

    # Matériaux de l'aperçu : une retouche est gardée, mais la copie est refaite dès que le matériau du projet change.
    def copy_of(src_name):
        return next(c for c in display.preview_objects(p, "copy") if c["mcs_preview_src"] == src_name)
    pair = next((c["mcs_preview_src"], i, sm) for c in display.preview_objects(p, "copy")
                for i, sm in enumerate(bpy.data.objects[c["mcs_preview_src"]].data.materials)
                if sm is not None and szb.param_node(sm, "bumpiness") is not None)
    src_name, slot, src_mat = pair
    cm = copy_of(src_name).data.materials[slot]
    cm.diffuse_color = (0.1, 0.2, 0.3, 1.0)
    run("preview_refresh", show=False)
    cm2 = copy_of(src_name).data.materials[slot]
    check("Matériau d'aperçu retouché gardé tant que le matériau du projet ne change pas",
          cm2 == cm and abs(cm2.diffuse_color[2] - 0.3) < 1e-6)
    bump_node = szb.param_node(src_mat, "bumpiness")
    old_bump = bump_node.outputs[0].default_value
    bump_node.outputs[0].default_value = 2.5
    status.invalidate()
    check("Matériau du projet modifié (bumpiness) : aperçu signalé à actualiser",
          any("changé" in m for sv, m, f in status.step_display(bpy.context, p)[1]), status.step_display(bpy.context, p)[1])
    run("preview_refresh", show=False)
    cm3 = copy_of(src_name).data.materials[slot]
    check("Actualiser : l'aperçu reprend le matériau modifié (bumpiness, textures)",
          abs(szb.param_node(cm3, "bumpiness").outputs[0].default_value - 2.5) < 1e-6
          and cm3.node_tree.nodes["BumpSampler"].image == src_mat.node_tree.nodes["BumpSampler"].image)
    def strength_feed(mat):
        nm_node = next(nd for nd in mat.node_tree.nodes if nd.bl_idname == "ShaderNodeNormalMap")
        return [l.from_node for l in mat.node_tree.links if l.to_socket == nm_node.inputs["Strength"]]
    feed = strength_feed(cm3)
    check("Copie d'aperçu lisible par Cycles : aucun lien depuis un nœud Python, bumpiness figée dans un nœud Valeur",
          not [l for l in cm3.node_tree.links if l.from_node.type == "CUSTOM"]
          and len(feed) == 1 and feed[0].bl_idname == "ShaderNodeValue" and abs(feed[0].outputs[0].default_value - 2.5) < 1e-6,
          [(f.bl_idname, f.outputs[0].default_value) for f in feed])
    rough_src = [l.from_node for l in cm3.node_tree.links
                 if l.to_node.bl_idname == "ShaderNodeMapRange" and l.to_socket == l.to_node.inputs[0]]
    check("Rugosité et intensité spéculaire figées aussi (specularFalloffMult, specularIntensityMult)",
          rough_src and all(n.bl_idname == "ShaderNodeValue" for n in rough_src), [n.bl_idname for n in rough_src])
    check("Matériau du projet (FiveM) intact : ses Value Parameters restent reliés",
          strength_feed(src_mat)[0].bl_idname == "SOLLUMZ_NT_SHADER_Parameter")
    check("Ancienne copie de matériau retirée, nom « Apercu_… » propre",
          not [m for m in bpy.data.materials if m.get("mcs_preview") and m.users == 0]
          and cm3.name == f"Apercu_{src_mat.name}", cm3.name)
    bump_node.outputs[0].default_value = old_bump
    run("preview_refresh", show=False)
    p.render_res_x, p.render_res_y, p.quick_samples = 64, 48, 1
    p.render_dir = os.path.join(WORK, "rendus")
    check("Rendu rapide", run("render", mode="QUICK") == {"FINISHED"} and any(f.endswith(".png") for f in os.listdir(p.render_dir)))
    check("Réglages du display restaurés", ps.cycles.samples == 128)
    last = max((f for f in os.listdir(p.render_dir) if f.endswith(".png")),
               key=lambda f: os.path.getmtime(os.path.join(p.render_dir, f)))
    shot = bpy.data.images.load(os.path.join(p.render_dir, last))
    check("Rendu rapide à la résolution complète (petits détails conservés)", tuple(shot.size) == (64, 48),
          tuple(shot.size))
    bpy.data.images.remove(shot)
    base_cam = p.render_camera
    base_matrix = base_cam.matrix_world.copy()
    est_display = display.detail_estimate(p, base_cam)
    check("Taille de la chaîne sur l'image estimée (px et px/cm) et notée après le rendu",
          est_display is not None and est_display[2] > 0 and "px par cm" in p.render_note, (est_display, p.render_note))
    # Chaîne réduite à l'écran (comme sur un buste entier) : le gros plan doit la recadrer en grand.
    p.render_res_x, p.render_res_y = 160, 120
    p.preview_scale = 0.2
    ps.view_layers[0].update()
    est_display = display.detail_estimate(p, base_cam)
    fill_display = max(est_display[0] / 160, est_display[1] / 120)
    p.render_closeup = True
    check("Rendu en gros plan sur la chaîne", run("render", mode="QUICK") == {"FINISHED"})
    closeups = display.preview_objects(p, "closeup")
    cu = closeups[0] if closeups else None
    est_close = display.detail_estimate(p, cu) if cu else None
    fill = max(est_close[0] / 160, est_close[1] / 120) if est_close else 0
    check("Gros plan : une seule caméra, dans la scène d'aperçu, même angle que la caméra du display",
          len(closeups) == 1 and cu.name in ps.objects and cu.get("mcs_preview")
          and cu.matrix_world.to_quaternion().rotation_difference(base_matrix.to_quaternion()).angle < 1e-4)
    check("Gros plan : la chaîne remplit le cadre sans en sortir (et bien plus de px par cm)", 0.6 < fill <= 0.95
          and fill > 2 * fill_display and est_close[2] > 2 * est_display[2], (fill, fill_display, est_close, est_display))
    check("Gros plan : caméra du display intacte et rétablie", base_cam.matrix_world == base_matrix
          and ps.camera == base_cam and p.render_camera == base_cam)
    from bl_ext.user_default.mio_chain_studio.props import _poll_camera
    check("La caméra du gros plan n'est pas proposée comme caméra du display", not _poll_camera(p, cu)
          and _poll_camera(p, base_cam))
    n_png = len([f for f in os.listdir(p.render_dir) if f.endswith(".png")])
    run("render", mode="QUICK")
    check("Deux rendus de suite : aucune image écrasée, nom « gros_plan »",
          len([f for f in os.listdir(p.render_dir) if f.endswith(".png")]) == n_png + 1
          and all("gros_plan" in f for f in sorted(os.listdir(p.render_dir), key=lambda f: os.path.getmtime(
              os.path.join(p.render_dir, f)))[-2:]))
    check("Gros plan recadré sans doublon", len(display.preview_objects(p, "closeup")) == 1
          and len([c for c in bpy.data.cameras if c.name.startswith("MCS_Gros_Plan")]) == 1)
    ps.render.use_simplify = True
    ps.cycles.texture_limit_render = "256"
    run("render", mode="QUICK")
    check("Limite de textures du display (Simplify) signalée", "256 px" in p.render_note, p.render_note)
    ps.render.use_simplify = False
    p.render_closeup = False
    p.preview_scale = 1.0
    p.render_res_x, p.render_res_y = 64, 48
    run("export_check")
    excl = [i.message for i in p.report if i.category == "Exclusion" and i.severity == "ERROR"]
    check("Display exclu de l'export", not excl, excl)
    run("export")
    xml = open(xml_path, encoding="utf-8").read()
    check("YDD sans objet du display", "Buste" not in xml and "CamPresentation" not in xml)

    errs = draw_all_panels()
    check("Dessin de tous les panneaux", not errs, errs)
    real_step2 = status.STEPS[1]
    status.STEPS = tuple((k, l, (lambda c, pr: 1 / 0) if k == "2" else f) for k, l, f in status.STEPS)
    status.invalidate()
    try:
        st2, issues2 = status.compute(bpy.context, p, "2")
        errs = draw_all_panels()
    finally:
        status.STEPS = tuple(real_step2 if k == "2" else (k, l, f) for k, l, f in status.STEPS)
        status.invalidate()
    check("Statut en erreur : panneaux toujours dessinés, erreur affichée", not errs and st2 == "À vérifier"
          and "Erreur interne" in issues2[0][1], (errs, issues2))

    # Sauvegarde et réouverture -----------------------------------------------------------
    print("\n[S] Sauvegarde et réouverture")
    names = {k: getattr(p, k).name for k in ("ref_root", "ref_drawable", "final_obj", "preview_scene")}
    n_parts = len(p.parts)
    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=os.path.join(WORK, "projet.blend"))
    p = proj()
    check("Références conservées", all(getattr(p, k) is not None and getattr(p, k).name == v for k, v in names.items()),
          {k: getattr(p, k).name if getattr(p, k) else None for k in names})
    check("Composants et réglages conservés", len(p.parts) == n_parts and abs(p.thickness_2 - 0.01) < 1e-6)
    check("Presets toujours disponibles", "argent" in presets.names())
    check("Statut 8 après réouverture", status.step8(bpy.context, p)[0] == "Terminé", status.step8(bpy.context, p)[1])
    n_obj = len(bpy.data.objects)
    run("preview_refresh", show=False)
    check("Actualisation après réouverture sans doublon", len(bpy.data.objects) == n_obj)
    errs = draw_all_panels()
    check("Panneaux après réouverture", not errs, errs)

    print("\n[C] Cohabitation avec un autre addon")
    import importlib
    pkg = importlib.import_module("bl_ext.user_default.mio_chain_studio")
    from bl_ext.user_default.mio_chain_studio import ui as ui_mod
    check("Aucun conflit en temps normal", pkg.check_conflicts() == [], pkg.check_conflicts())
    foreign = []

    class MIO_PG_step(bpy.types.PropertyGroup):
        pass
    foreign.append(MIO_PG_step)
    for ident in ["MIO_PT_main"] + [f"MIO_PT_step{i}" for i in range(1, 7)]:
        foreign.append(type(ident, (bpy.types.Panel,), {"bl_idname": ident, "bl_label": ident, "bl_space_type": "VIEW_3D",
                                                       "bl_region_type": "UI", "bl_category": "Autre",
                                                       "draw": lambda self, context: None}))
    for cls in foreign:
        bpy.utils.register_class(cls)
    ours = all(getattr(bpy.types, c.bl_idname if hasattr(c, "bl_idname") else c.__name__, None) is c
               for c in ui_mod.CLASSES)
    check("Autre addon en MIO_PT_* / MIO_PG_step : panneaux Mio Chain intacts", ours and pkg.check_conflicts() == [])
    clash = type("MCS_PT_step1", (bpy.types.Panel,), {"bl_idname": "MCS_PT_step1", "bl_label": "x", "bl_space_type": "VIEW_3D",
                                                     "bl_region_type": "UI", "draw": lambda self, context: None})
    bpy.utils.register_class(clash)
    found = pkg.check_conflicts()
    check("Conflit réel détecté et signalé", any(c.startswith("MCS_PT_step1") for c in found), found)
    errs = draw_all_panels()
    check("Panneau principal dessiné avec l'alerte de conflit", not errs, errs)
    bpy.utils.unregister_class(clash)
    bpy.utils.register_class(ui_mod.MCS_PT_step1)
    for cls in reversed(foreign):
        bpy.utils.unregister_class(cls)
    check("Retour à la normale", pkg.check_conflicts() == [], pkg.check_conflicts())

    print("\n[D] Dépendances")
    bpy.ops.preferences.addon_disable(module=SOLLUMZ)
    szb.detect(refresh=True)
    check("Sollumz désactivé : export refusé", run("export") != {"FINISHED"})
    errs = draw_all_panels()
    check("Panneaux sans Sollumz", not errs, errs)
    bpy.ops.preferences.addon_enable(module=SOLLUMZ)
    check("Sollumz réactivé", szb.detect(refresh=True).ok)
    check("Objets extérieurs jamais supprimés", external <= {o.name for o in bpy.data.objects})

    ok = sum(1 for r in RESULTS if r[1])
    print(f"\nRÉSULTAT : {ok}/{len(RESULTS)} vérifications réussies")
    with open(os.path.join(WORK, "resultats.json"), "w", encoding="utf-8") as f:
        json.dump([{"test": n, "ok": o, "detail": d} for n, o, d in RESULTS], f, ensure_ascii=False, indent=1)
    return ok == len(RESULTS)


if __name__ == "__main__":
    try:
        success = main()
    except Exception:
        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
