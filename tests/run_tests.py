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
          and p.final_obj.name == "MCS_Bijou_Final")
    final = p.final_obj
    check("Weight Paint", run("weight_paint") == {"FINISHED"} and bpy.context.mode == "PAINT_WEIGHT")
    bpy.ops.object.mode_set(mode="OBJECT")

    # 8. Export ----------------------------------------------------------------------------
    print("\n[8] Modèle d'export")
    final_world = final.matrix_world.copy()
    check("Préparer le modèle d'export", run("export_prepare") == {"FINISHED"})
    er, ed = p.export_root, p.export_drawable
    target = p.export_target
    check("Copie d'export : armature > drawable > mesh de référence", er.type == "ARMATURE" and er.name == "teef_000_u"
          and ed.parent == er and exp.strip_suffix(ed.name) == "teef_000_u" and target.parent == ed and target.type == "MESH",
          (er.name, ed.name, target.name))
    target_name = target.name
    check("Armature d'export : mêmes os (128, SKEL_ROOT, SKEL_Spine3)", er.data == p.ref_root.data and len(er.data.bones) == 128)
    p.export_target = None
    p.export_target = target
    check("Mesh cible identifié dans la nouvelle hiérarchie (pas par nom)", p.export_target == target and target != p.ref_model)
    ref_lods = {k: m.name for k, m in szb.lod_meshes(p.ref_model).items() if m}
    check("Remplacer le mesh de référence par mon bijou", run("export_replace") == {"FINISHED"})
    check("Mesh final sous le drawable d'export", final.parent == ed and final.sollum_type == szb.MODEL)
    check("Position monde conservée (pas de double transformation)",
          max(abs(a - b) for ra, rb in zip(final.matrix_world, final_world) for a, b in zip(ra, rb)) < 1e-6)
    lods = szb.lod_meshes(final)
    check("LOD : High = bijou, Medium et Low vides", lods["sollumz_high"] == final.data and lods["sollumz_medium"] is None
          and lods["sollumz_low"] is None)
    check("Mesh de référence retiré de la copie seulement", target_name not in bpy.data.objects
          and p.ref_model.name == "SKEL_ROOT")
    _, models = teef.find_structure(er)
    check("Un seul mesh sous le drawable", models == [final])
    check("Références intactes (SKEL_ROOT os et mesh, LOD)", p.ref_model.name == "SKEL_ROOT" and "SKEL_ROOT" in er.data.bones
          and {k: m.name for k, m in szb.lod_meshes(p.ref_model).items() if m} == ref_lods)
    mods = [m for m in final.modifiers if m.type == "ARMATURE"]
    check("Liaison à l'armature d'export", len(mods) == 1 and mods[0].object == er)
    check("Remplacement répété refusé proprement", run("export_replace") != {"FINISHED"} and final.parent == ed)
    run("export_check")
    errors = [i.message for i in p.report if i.severity == "ERROR"]
    check("Vérification avant export : aucune erreur bloquante", not errors, errors)
    p.export_dir = os.path.join(WORK, "export")
    check("Exporter avec Sollumz", run("export") == {"FINISHED"} and p.last_export_ok, json.loads(p.last_export or "{}").get("errors"))
    xml_path = os.path.join(p.export_dir, "teef_000_u.ydd.xml")
    xml = open(xml_path, encoding="utf-8").read() if os.path.isfile(xml_path) else ""
    check("YDD : drawable teef_000_u (pas teef_012_u)", "<Name>teef_000_u</Name>" in xml and "teef_012_u" not in xml)
    check("YDD : LOD High seulement", "DrawableModelsHigh" in xml and "DrawableModelsMedium" not in xml and "DrawableModelsLow" not in xml)
    check("YDD : 100 % des sommets sur l'os 38", any("100 % sur l'os 38" in line or "à 100 %" in line
                                                     for line in json.loads(p.last_export)["lines"]))
    check("YDD : Bump et Spec DDS intégrés", os.path.isfile(os.path.join(p.export_dir, "teef_000_u", "teef_normal_001.dds"))
          and os.path.isfile(os.path.join(p.export_dir, "teef_000_u", "teef_spec_000.dds")))
    check("YDD : ancienne chaîne absente", xml.count("<VertexBuffer>") >= 1 and "teef_diff_012_a_uni" not in xml)
    check("YDD : Colour0 255 128 0 255 et glow 255 186 255 255", "255 128 0 255" in xml and "255 186 255 255" in xml)
    check("Statut 8 terminé", status.step8(bpy.context, p)[0] == "Terminé", status.step8(bpy.context, p)[1])
    p.lod_mode = "DUPLICATE"
    run("export_prepare")
    check("Nouvelle préparation : bijou ressorti, pas supprimé", final.name in bpy.data.objects and final.parent is None)
    run("export_replace")
    run("export")
    xml = open(xml_path, encoding="utf-8").read()
    check("LOD High copié en Medium et Low (affiché comme non optimisé)", "DrawableModelsMedium" in xml and "DrawableModelsLow" in xml
          and "non optimisée" in " ".join(i.message for i in p.report))
    p.lod_mode = "HIGH_ONLY"
    run("export_prepare")
    run("export_replace")
    run("export")

    # Display -----------------------------------------------------------------------------
    print("\n[A] Display")
    display_path = os.path.join(WORK, "display.blend")
    make_display(display_path)
    p.display_path = os.path.join(WORK, "absent.blend")
    check("Display manquant : erreur", run("display_load") != {"FINISHED"})
    p.display_path = display_path
    run("display_analyse")
    check("Charger le display", run("display_load") == {"FINISHED"} and p.preview_scene is not None)
    ps = p.preview_scene
    check("Caméra et réglages du display repris", p.render_camera and ps.cycles.samples == 128)
    mk = [o for o in ps.objects if o.name.startswith("Repere_Cou")][0]
    with bpy.context.temp_override(scene=ps, view_layer=ps.view_layers[0], active_object=mk):
        check("Repère réglable (objet actif)", run("marker_set", source="ACTIVE") == {"FINISHED"})
    check("Placer le bijou", run("preview_refresh") == {"FINISHED"})
    n = len(display.preview_objects(p, "copy"))
    n_mesh = len(bpy.data.meshes)
    run("preview_refresh")
    run("preview_refresh")
    check("Actualiser : pas de doublon", len(display.preview_objects(p, "copy")) == n and len(bpy.data.meshes) == n_mesh)
    copy = display.preview_objects(p, "copy")[0]
    src = bpy.data.objects[copy["mcs_preview_src"]]
    check("Copie indépendante (maillage et matériaux)", copy.data != src.data
          and not set(copy.data.materials) & set(src.data.materials))
    p.render_res_x, p.render_res_y, p.quick_samples = 64, 48, 1
    p.render_dir = os.path.join(WORK, "rendus")
    check("Lancer un rendu", run("render") == {"FINISHED"} and any(f.endswith(".png") for f in os.listdir(p.render_dir)))
    check("Réglages du display restaurés", ps.cycles.samples == 128)
    run("export_check")
    excl = [i.message for i in p.report if i.category == "Exclusion" and i.severity == "ERROR"]
    check("Display exclu de l'export", not excl, excl)
    run("export")
    xml = open(xml_path, encoding="utf-8").read()
    check("YDD sans objet du display", "Buste" not in xml and "CamPresentation" not in xml)

    errs = draw_all_panels()
    check("Dessin de tous les panneaux", not errs, errs)

    # Sauvegarde et réouverture -----------------------------------------------------------
    print("\n[S] Sauvegarde et réouverture")
    names = {k: getattr(p, k).name for k in ("ref_root", "ref_model", "final_obj", "export_root", "export_drawable",
                                             "preview_scene")}
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
    run("preview_refresh")
    check("Actualisation après réouverture sans doublon", len(bpy.data.objects) == n_obj)
    errs = draw_all_panels()
    check("Panneaux après réouverture", not errs, errs)

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
