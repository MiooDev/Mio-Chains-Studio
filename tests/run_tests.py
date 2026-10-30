"""Tests de bout en bout dans Blender (module bpy) avec Sollumz réellement installé.

Usage :
    python -I tests/run_tests.py -- <dossier_de_travail> [chemin/vers/teef_000_u.ydd.xml]

Prérequis : Blender (bpy) 5.2.x, Sollumz installé dans le dépôt d'extensions « user_default »,
Mio Chain Studio installé dans ce même dépôt (dossier mio_chain_studio). ImageMagick facultatif (DDS).
Les données de test (chaîne, armature, display) sont SYNTHÉTIQUES : elles ne remplacent pas vos fichiers.
"""

import json
import math
import os
import shutil
import sys
import traceback

import bpy
import numpy as np
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WORK = os.path.abspath(ARGS[0] if ARGS else "mcs_test_work")
REF_YDD = ARGS[1] if len(ARGS) > 1 else ""
ADDON = "bl_ext.user_default.mio_chain_studio"
SOLLUMZ = "bl_ext.user_default.sollumz"

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  OK  " if cond else "  ÉCHEC ") + name + (f" — {detail}" if detail and not cond else ""))
    return cond


def run(op, **kw):
    try:
        return getattr(bpy.ops.mio_chain, op)(**kw)
    except RuntimeError as exc:  # opérateur ayant rapporté une erreur
        return {"ERROR: " + str(exc).splitlines()[0]}


def proj():
    return bpy.data.scenes["Scene"].mio_chain


def count_role(role):
    return sum(1 for o in bpy.data.objects if o.get("mcs_role") == role and o.get("mcs_generated")
               and o.get("mcs_project") == proj().project_id and not o.get("mcs_export") and not o.get("mcs_preview"))


# ---------------------------------------------------------------------------
# Faux layout pour exécuter le code de dessin des panneaux et valider les noms de propriétés
# ---------------------------------------------------------------------------

class FakeLayout:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def fn(*args, **kw):
            self.calls += 1
            if name in ("prop", "prop_search", "prop_enum") and len(args) >= 2:
                data, prop = args[0], args[1]
                if prop not in data.bl_rna.properties:
                    raise AttributeError(f"Propriété inconnue {type(data).__name__}.{prop}")
            if name == "operator":
                idname = args[0]
                mod, opn = idname.split(".")
                if not hasattr(getattr(bpy.ops, mod), opn):
                    raise AttributeError(f"Opérateur inconnu {idname}")
            return FakeLayout()
        return fn

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)


def draw_all_panels():
    from bl_ext.user_default.mio_chain_studio import ui
    errors = []
    for cls in ui.CLASSES:
        if not issubclass(cls, bpy.types.Panel):
            continue

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

def make_png(path, color, size=256):
    img = bpy.data.images.new(os.path.basename(path), size, size, alpha=True)
    px = np.tile(np.array(color, dtype=np.float32), size * size)
    img.pixels.foreach_set(px)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def make_chain_obj(path):
    """Chaîne synthétique : anneaux disposés en U autour du cou (ordre de grandeur : votre référence)."""
    import bmesh
    me = bpy.data.meshes.new("chaine_test")
    bm = bmesh.new()
    n = 24
    for i in range(n):
        t = math.pi * (i / (n - 1))           # demi-boucle avant
        x = 0.1 * math.cos(t)
        y = -0.12 * math.sin(t)
        z = 0.55 - 0.2 * math.sin(t)
        res = bmesh.ops.create_circle(bm, cap_ends=False, radius=0.006, segments=8)
        for v in res["verts"]:
            v.co = Vector((v.co.x + x, v.co.y + y, v.co.z + z)) if i % 2 else Vector((v.co.x + x, v.co.z + y, v.co.y + z))
    bmesh.ops.extrude_edge_only(bm, edges=bm.edges[:])
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new("chaine_test", me)
    bpy.context.scene.collection.objects.link(obj)
    for o in bpy.context.view_layer.objects.selected:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, export_materials=False)
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(me)


def make_armature():
    """Armature de TEST (pas le squelette du ped) et maillage pondéré servant de source de poids."""
    arm_data = bpy.data.armatures.new("ARM_test")
    arm = bpy.data.objects.new("Squelette_Test", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in (("SKEL_ROOT", (0, 0, 0), (0, 0, 0.1), None),
                                     ("SKEL_Spine3", (0, 0, 0.25), (0, 0, 0.45), "SKEL_ROOT"),
                                     ("SKEL_Neck_1", (0, 0, 0.45), (0, 0, 0.6), "SKEL_Spine3")):
        b = arm_data.edit_bones.new(name)
        b.head, b.tail = head, tail
        if parent:
            b.parent = arm_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cylinder_add(radius=0.13, depth=0.5, location=(0, 0, 0.45), vertices=24)
    body = bpy.context.active_object
    body.name = "Corps_Poids_Test"
    neck, spine = body.vertex_groups.new(name="SKEL_Neck_1"), body.vertex_groups.new(name="SKEL_Spine3")
    for v in body.data.vertices:
        z = (body.matrix_world @ v.co).z
        t = max(0.0, min(1.0, (z - 0.25) / 0.4))
        neck.add([v.index], t, "REPLACE")
        spine.add([v.index], 1 - t, "REPLACE")
    return arm, body


def make_display(path):
    """Display synthétique écrit par un processus Blender séparé (voir make_display.py)."""
    import subprocess
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
    check("Addon enregistré", ADDON in bpy.context.preferences.addons and hasattr(bpy.ops.mio_chain, "pendant_create"))
    from bl_ext.user_default.mio_chain_studio import sollumz_bridge as szb, status, export as exp, atlas, effects, rigging, display, dds
    info = szb.detect(refresh=True)
    check("Sollumz détecté", info.ok and info.version == (2, 9, 0), f"{info.version} {info.errors}")
    check("Format CW XML disponible", info.cwxml_available)

    external = {o.name for o in bpy.data.objects}
    display_path = os.path.join(WORK, "display.blend")
    make_display(display_path)
    check("Display synthétique écrit", os.path.isfile(display_path))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(WORK, "projet.blend"))

    # 1. Projet -------------------------------------------------------------
    print("\n[1] Préparer le projet")
    check("Initialiser", run("init_project") == {"FINISHED"})
    p = proj()
    check("Collections créées", p.coll_root and p.coll_sources and p.coll_jewel and p.coll_export)
    check("Checklist CodeWalker initialisée", len(p.cw_checks) == len(exp.CW_ITEMS))
    run("init_project")
    check("Ré-initialisation sans doublon de collections",
          sum(1 for c in bpy.data.collections if c.get("mcs_role") == "bijou") == 1)

    # 2. Pendentif ------------------------------------------------------------
    print("\n[2] Pendentif texte")
    p.text = "NO RULES"
    p.use_plate = True
    check("Créer le pendentif", run("pendant_create") == {"FINISHED"})
    txt = p.pendant_text
    check("Texte, plaque, bélière générés", txt and p.plate and p.bail)
    tris = sum(len(o.data.polygons) for o in (txt, p.plate, p.bail))
    check("Géométrie réelle (faces)", tris > 100, str(tris))
    meshes_before = len(bpy.data.meshes)
    for _ in range(3):
        run("pendant_create")
    check("Clics répétés : un seul texte/plaque/bélière",
          count_role("texte") == 1 and count_role("plaque") == 1 and count_role("beliere") == 1)
    check("Clics répétés : pas de maillages accumulés", len(bpy.data.meshes) == meshes_before,
          f"{meshes_before} → {len(bpy.data.meshes)}")
    manual = bpy.data.objects.new("Gravure_Manuelle", bpy.data.meshes.new("Gravure_Manuelle"))
    p.coll_jewel.objects.link(manual)
    manual.parent = p.pendant_pivot
    nverts = len(txt.data.vertices)
    p.text = "MIO"
    check("Mettre à jour le pendentif", run("pendant_create", update_only=True) == {"FINISHED"})
    check("Même objet, nouveau maillage", p.pendant_text == txt and len(txt.data.vertices) != nverts)
    check("Objet manuel conservé", "Gravure_Manuelle" in bpy.data.objects)
    check("Source du texte modifiable conservée", p.text_source and p.text_source.data.body == "MIO")
    p.use_plate = False
    run("pendant_create", update_only=True)
    check("Plaque désactivée → plaque générée retirée", p.plate is None and count_role("plaque") == 0)
    p.use_plate = True
    run("pendant_create", update_only=True)
    check("Plaque réactivée", p.plate is not None and count_role("plaque") == 1)
    p.font_path = os.path.join(WORK, "police_absente.ttf")
    check("Police manquante → erreur", run("pendant_create", update_only=True) != {"FINISHED"})
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if os.path.isfile(font):
        p.font_path = font
        check("Police chargée depuis un fichier", run("pendant_create", update_only=True) == {"FINISHED"}
              and p.text_source.data.font.filepath.endswith("DejaVuSans-Bold.ttf"))
    else:
        p.font_path = ""
    p.text = "   "
    check("Texte vide → erreur", run("pendant_create", update_only=True) != {"FINISHED"})
    p.text = "NO RULES"
    run("pendant_create", update_only=True)

    # Chaîne -------------------------------------------------------------------
    print("\n[2] Chaîne")
    obj_path = os.path.join(WORK, "chaine_test.obj")
    make_chain_obj(obj_path)
    p.chain_path = os.path.join(WORK, "absente.obj")
    check("OBJ manquant → erreur", run("chain_import") != {"FINISHED"})
    fake = os.path.join(WORK, "chaine.fbx")
    open(fake, "w").close()
    p.chain_path = fake
    check("Format non convenu → erreur", run("chain_import") != {"FINISHED"})
    p.chain_path = obj_path
    p.chain_forward, p.chain_up = "NEGATIVE_Z", "Y"  # axes de l'export OBJ de Blender
    check("Importer la chaîne", run("chain_import") == {"FINISHED"} and p.chain is not None)
    check("Chaîne rattachée à la racine", p.chain.parent == p.jewel_root)
    n_obj = len(bpy.data.objects)
    run("chain_import")
    run("chain_import")
    check("Ré-import : remplacement sans doublon", len(bpy.data.objects) == n_obj, f"{n_obj} → {len(bpy.data.objects)}")
    run("pendant_snap")
    from bl_ext.user_default.mio_chain_studio.assembly import world_bounds
    lo, hi = world_bounds([p.bail])
    low = min((p.chain.matrix_world @ v.co).z for v in p.chain.data.vertices)
    check("Pendentif accroché au bas de la chaîne", abs((lo.z + hi.z) / 2 - low) < 1e-4)
    root_before = [o.matrix_world.copy() for o in (p.chain, txt)]
    rel_before = p.chain.matrix_world.inverted() @ txt.matrix_world
    p.jewel_root.location.x += 0.5
    bpy.context.view_layer.update()
    rel_after = p.chain.matrix_world.inverted() @ txt.matrix_world
    check("Déplacer l'ensemble conserve l'assemblage", all(abs(a - b) < 1e-6 for ra, rb in zip(rel_before, rel_after) for a, b in zip(ra, rb)))
    p.jewel_root.location.x -= 0.5
    bpy.context.view_layer.update()

    # Référence utilisateur (facultatif) -----------------------------------------------------
    if REF_YDD and os.path.isfile(REF_YDD):
        before = set(bpy.data.objects)
        bpy.ops.sollumz.import_assets(directory=os.path.dirname(REF_YDD) + os.sep, files=[{"name": os.path.basename(REF_YDD)}])
        new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        check("Référence teef importée par Sollumz", bool(new))
        if new:
            p.ref_model = new[0]

    # 3. Matériaux --------------------------------------------------------------
    print("\n[3] Matériaux et textures")
    check("Configurer les matériaux", run("materials_setup") == {"FINISHED"})
    from bl_ext.user_default.mio_chain_studio.materials import component_materials, unique_materials
    mats = unique_materials(p)
    check("Un matériau Sollumz ped_default par composant", len(mats) == 4 and all(szb.material_shader(m) == "ped_default.sps" for m, r in mats))
    nmat = len(bpy.data.materials)
    run("materials_setup")
    check("Clics répétés : pas de matériaux en plus", len(bpy.data.materials) == nmat)
    tex_dir = os.path.join(WORK, "src_tex")
    os.makedirs(tex_dir)
    colors = {"chaine": (0.8, 0.6, 0.1, 1), "texte": (0.9, 0.9, 0.9, 1), "plaque": (0.1, 0.1, 0.1, 1), "beliere": (0.8, 0.6, 0.1, 1)}
    for mat, role in mats:
        path = os.path.join(tex_dir, f"tex_{role}.png")
        make_png(path, colors[role], 128 if role == "plaque" else 256)
        run("texture_assign", material=mat.name, sampler="DiffuseSampler", filepath=path)
    check("Textures associées", all(m.node_tree.nodes["DiffuseSampler"].image and m.node_tree.nodes["DiffuseSampler"].image.filepath for m, r in mats))
    run("texture_assign", material=mats[0][0].name, sampler="DiffuseSampler", filepath=os.path.join(tex_dir, "absente.png"))
    check("Texture introuvable refusée", mats[0][0].node_tree.nodes["DiffuseSampler"].image.filepath.endswith(".png"))
    st, issues = status.step3(bpy.context, p)
    check("Statut 3 non terminé sans DDS/YTD", st != "Terminé")
    m0 = mats[0][0]
    p.preset_name = "test_preset"
    node = m0.node_tree.nodes["specularIntensityMult"]
    node.outputs[0].default_value = 0.42
    run("preset_save", material=m0.name)
    node.outputs[0].default_value = 0.1
    run("preset_load", material=m0.name, preset="test_preset")
    check("Préréglage enregistré puis réappliqué", abs(m0.node_tree.nodes["specularIntensityMult"].outputs[0].default_value - 0.42) < 1e-6)
    mat_text = p.pendant_text.data.materials[0]
    p.text = "NO RULES!"
    run("pendant_create", update_only=True)
    check("Mise à jour du texte : matériau conservé", p.pendant_text.data.materials[0] == mat_text)
    p.text = "NO RULES"
    run("pendant_create", update_only=True)
    run("materials_setup")

    # Atlas / DDS / YTD ----------------------------------------------------------------
    print("\n[3] Atlas, DDS, YTD")
    p.use_atlas = True
    p.atlas_size = "512"
    uv_before = np.array([d.uv[:] for d in p.chain.data.uv_layers["UVMap 0"].data])
    check("Préparer l'atlas", run("atlas_build") == {"FINISHED"})
    check("Atlas 512 enregistré", p.atlas_image and tuple(p.atlas_image.size) == (512, 512) and os.path.isfile(bpy.path.abspath(p.atlas_image.filepath)))
    check("Nom de l'atlas = nom de texture", szb.texture_name_of_image(p.atlas_image) == p.texture_name())
    uv_after = np.array([d.uv[:] for d in p.chain.data.uv_layers["UVMap 0"].data])
    check("UV d'origine intactes", np.allclose(uv_before, uv_after))
    check("Vérification de l'atlas sans erreur", not [i for i in atlas.verify(p) if i[0] == "ERROR"])
    check("Atlas à jour", atlas.atlas_state(p)[1])
    p.text = "NO RULES 2"
    run("pendant_create", update_only=True)
    check("Texte modifié → atlas périmé", not atlas.atlas_state(p)[1])
    run("atlas_build")
    check("Atlas reconstruit à jour", atlas.atlas_state(p)[1])
    fake_dds = os.path.join(WORK, "faux.dds")
    shutil.copy(bpy.path.abspath(p.atlas_image.filepath), fake_dds)
    info_f, iss = dds.verify(fake_dds)
    check("PNG renommé en .dds refusé", info_f is None and iss)
    enc = dds.find_encoders()
    if enc:
        check(f"Conversion DDS ({enc[0][0]})", run("dds_convert") == {"FINISHED"})
        hdr = dds.read_header(bpy.path.abspath(p.dds_path))
        check("En-tête DDS vérifié (DXT5 512×512, mipmaps)", hdr["format"] == "DXT5" and hdr["width"] == 512 and hdr["mips"] > 1, str(hdr))
        check("Préparer le YTD", run("ytd_prepare") == {"FINISHED"})
        txd = szb.find_txd(bpy.data.scenes["Scene"], p.ytd_name())
        check("YTD contient la texture", txd and [t.name for t in txd.textures] == [p.texture_name()])
    else:
        check("Sans encodeur : conversion refusée proprement", run("dds_convert") != {"FINISHED"})

    # 4. Effets ------------------------------------------------------------------
    print("\n[4] Effets")
    check("Appliquer les couleurs de sommets", run("vertex_colors_apply") == {"FINISHED"})
    check("Couleurs vérifiées", not effects.colors_issues(p))
    got = effects.read_colors(p.chain.data, 0)
    check("Color 1 = 255 128 0 255", got is not None and (got == [255, 128, 0, 255]).all())
    check("Émissif activé sur le texte", run("emissive_set", role="texte", enable=True) == {"FINISHED"}
          and szb.material_shader(p.pendant_text.data.materials[0]) == "ped_emissive.sps"
          and effects.emissive_value(p.pendant_text.data.materials[0]) == p.emissive_multiplier)
    check("Émissif : UVMap 1 ajoutée", "UVMap 1" in p.pendant_text.data.uv_layers)
    check("Émissif désactivé", run("emissive_set", role="texte", enable=False) == {"FINISHED"}
          and szb.material_shader(p.pendant_text.data.materials[0]) == "ped_default.sps")
    if p.ref_model is not None:
        check("Couleurs lues depuis la référence", run("vertex_colors_from_ref") == {"FINISHED"}
              and tuple(round(c * 255) for c in p.vcol0) == (255, 128, 0, 255))

    # 5. Rigging -----------------------------------------------------------------------
    print("\n[5] Rigging")
    arm, body = make_armature()
    p.ref_armature = arm
    p.ref_weights_mesh = body
    check("Lier à l'armature", run("rig_link") == {"FINISHED"})
    check("Générer les poids (chaîne, transfert)", run("rig_weights", group="CHAIN") == {"FINISHED"})
    check("Générer les poids (pendentif, rigide)", run("rig_weights", group="PENDANT") == {"FINISHED"})
    iss = rigging.analyse(p)
    check("Rigging sans erreur bloquante", not [i for i in iss if i[0] == "ERROR"], str([i[1] for i in iss if i[0] == "ERROR"]))
    w = rigging.read_weights(p.chain)
    check("Chaîne : tous les sommets pondérés, 4 influences max",
          len(w) == len(p.chain.data.vertices) and max(len(d) for d in w.values()) <= 4)
    wt = rigging.read_weights(p.pendant_text)
    check("Pendentif rigide : poids identiques partout", len({tuple(sorted(d.items())) for d in wt.values()}) == 1)
    g = p.chain.vertex_groups.new(name="OS_INEXISTANT")
    g.add([0], 0.5, "REPLACE")
    check("Groupe sans os détecté", any("sans os" in i[1] for i in rigging.analyse(p)))
    p.chain.vertex_groups.remove(g)
    check("Restaurer les poids précédents", run("rig_restore", group="PENDANT") == {"FINISHED"} and not p.pendant_text.vertex_groups)
    run("rig_weights", group="PENDANT")
    dg = bpy.context.evaluated_depsgraph_get()
    rest = [v.co.copy() for v in p.chain.evaluated_get(dg).to_mesh().vertices]
    used = rigging.weight_bones(p)
    check("La chaîne utilise plusieurs os", len(used) >= 2, str(used))
    p.deform_bone = used[0]
    check("Tester la déformation", run("pose_test") == {"FINISHED"})
    dg = bpy.context.evaluated_depsgraph_get()
    posed = [v.co.copy() for v in p.chain.evaluated_get(dg).to_mesh().vertices]
    check("Déformation visible", max((a - b).length for a, b in zip(rest, posed)) > 1e-3)
    run("pose_reset")
    dg = bpy.context.evaluated_depsgraph_get()
    back = [v.co.copy() for v in p.chain.evaluated_get(dg).to_mesh().vertices]
    check("Pose restaurée exactement", max((a - b).length for a, b in zip(rest, back)) < 1e-6)
    run("rig_check")
    run("deform_confirm")
    p.text = "NO RULES"
    run("pendant_create", update_only=True)
    check("Mise à jour du texte : poids réappliqués", len(p.pendant_text.vertex_groups) > 0
          and not [i for i in rigging.analyse(p) if i[0] == "ERROR"])
    run("atlas_build")
    if enc:
        run("dds_convert")
        run("ytd_prepare")
    run("vertex_colors_apply")
    run("rig_check")
    run("deform_confirm")

    # 6. Copie d'export / vérification --------------------------------------------------
    print("\n[6] Vérification")
    src_sig = [(o.name, len(o.data.vertices), o.data.materials[0].name) for o, r in exp.component_objects(p)]
    check("Créer la copie d'export", run("export_copy") == {"FINISHED"} and p.export_root is not None)
    root = p.export_root
    check("Hiérarchie Sollumz (DWD > drawable > modèles)", root.sollum_type == szb.DWD and root.type == "ARMATURE"
          and [c.sollum_type for c in root.children] == [szb.DRAWABLE] and len(exp._models(root)) == 4)
    check("Sources intactes", src_sig == [(o.name, len(o.data.vertices), o.data.materials[0].name) for o, r in exp.component_objects(p)])
    n_exp = len(exp.export_objects(p))
    run("export_copy")
    check("Copie d'export recréée sans doublon", len(exp.export_objects(p)) == n_exp)
    run("check")
    errors = [i.message for i in p.report if i.severity == "ERROR"]
    check("Vérification : aucune erreur bloquante", not errors, " | ".join(errors))

    # Display ---------------------------------------------------------------------
    print("\n[A] Aperçu sur display")
    p.display_path = os.path.join(WORK, "inexistant.blend")
    check("Display manquant → erreur", run("display_load") != {"FINISHED"})
    p.display_path = display_path
    check("Analyser le display", run("display_analyse") == {"FINISHED"} and any(i.kind == "SCENE" for i in p.display_items))
    check("Charger le display", run("display_load") == {"FINISHED"} and p.preview_scene is not None)
    ps = p.preview_scene
    check("Caméra et réglages du display repris", p.render_camera and p.render_camera.name.startswith("CamPresentation")
          and ps.cycles.samples == 128 and p.render_res_x == 800)
    check("Ressource manquante signalée", "velours" in p.display_missing)
    check("Second chargement refusé sans « Recharger »", run("display_load") != {"FINISHED"})
    mk = [o for o in ps.objects if o.name.startswith("Repere_Cou")][0]
    with bpy.context.temp_override(scene=ps, view_layer=ps.view_layers[0], active_object=mk):
        check("Définir le repère (objet actif)", run("marker_set", source="ACTIVE") == {"FINISHED"})
    check("Repère au cou du display", (p.preview_marker.matrix_world.translation - mk.matrix_world.translation).length < 1e-6)
    check("Enregistrer le repère", run("marker_save") == {"FINISHED"})
    check("Placer le bijou sur le display", run("preview_refresh") == {"FINISHED"})
    copies = display.preview_objects(p, "copy")
    check("Une copie par composant", len(copies) == 4)
    n_meshes = len(bpy.data.meshes)
    for _ in range(3):
        run("preview_refresh")
    check("Actualiser ×3 : pas de doublons", len(display.preview_objects(p, "copy")) == 4 and len(bpy.data.meshes) == n_meshes,
          f"{n_meshes} → {len(bpy.data.meshes)}")
    copy_chain = [c for c in display.preview_objects(p, "copy") if c.get("mcs_src_role") == "chaine"][0]
    pm = copy_chain.data.materials[0]
    pm.diffuse_color = (1, 0, 0, 1)
    run("preview_refresh")
    copy_chain = [c for c in display.preview_objects(p, "copy") if c.get("mcs_src_role") == "chaine"][0]
    check("Matériau d'aperçu conservé, source intacte", copy_chain.data.materials[0].diffuse_color[0] == 1
          and p.chain.data.materials[0].diffuse_color[:] != (1, 0, 0, 1))
    copy_chain.data.vertices[0].co.x += 1
    check("Géométrie d'aperçu indépendante", p.chain.data.vertices[0].co.x != copy_chain.data.vertices[0].co.x)
    rel_src = p.chain.matrix_world.inverted() @ p.pendant_text.matrix_world
    copy_text = [c for c in display.preview_objects(p, "copy") if c.get("mcs_src_role") == "texte"][0]
    rel_cp = copy_chain.matrix_world.inverted() @ copy_text.matrix_world
    check("Assemblage conservé sur le display", all(abs(a - b) < 1e-5 for ra, rb in zip(rel_src, rel_cp) for a, b in zip(ra, rb)))
    p.preview_loc = (0.01, 0, 0)
    check("Réglage de position appliqué", abs(p.preview_root.matrix_basis.translation.x - 0.01) < 1e-6)
    p.wrap_target = [o for o in ps.objects if o.name.startswith("Buste")][0]
    check("Épouser la forme (aperçu seulement)", run("wrap") == {"FINISHED"} and "MCS_Epouser" in copy_chain.modifiers
          and "MCS_Epouser" not in p.chain.modifiers)
    run("wrap", remove=True)
    p.render_res_x, p.render_res_y, p.render_percent, p.quick_samples = 64, 48, 100, 1
    p.render_dir = os.path.join(WORK, "rendus")
    check("Lancer le rendu (rapide)", run("render") == {"FINISHED"} and any(f.endswith(".png") for f in os.listdir(p.render_dir)))
    check("Réglages du display restaurés après rendu", ps.cycles.samples == 128 and ps.render.resolution_x == 800)
    check("Voir par la caméra refusé proprement sans fenêtre", run("view_camera") != {"FINISHED"} or bpy.context.window is not None)
    n_scenes = len(bpy.data.scenes)
    check("Recharger le display", run("display_load", force=True) == {"FINISHED"})
    check("Recharger : pas de scène en double", len(bpy.data.scenes) == n_scenes)
    check("Repère enregistré restauré au rechargement", p.preview_marker is not None
          and (p.preview_marker.matrix_world.translation - Vector((0, -0.25, 1.35))).length < 1e-5)
    run("preview_refresh")

    # 7. Export --------------------------------------------------------------------------
    print("\n[7] Export")
    run("export_copy")
    run("check")
    excl = [i.message for i in p.report if i.category == "Exclusion" and i.severity == "ERROR"]
    check("Display exclu de l'export", not excl, str(excl))
    p.export_dir = os.path.join(WORK, "export")
    res = run("export")
    data = json.loads(p.last_export_files or "{}")
    check("Exporter avec Sollumz", res == {"FINISHED"} and p.last_export_ok, str(data.get("errors")))
    ydd_xml = os.path.join(p.export_dir, f"{p.ydd_name()}.ydd.xml")
    check("YDD XML produit", os.path.isfile(ydd_xml))
    if os.path.isfile(ydd_xml):
        content = open(ydd_xml, encoding="utf-8").read()
        check("YDD : drawable et texture référencés", p.drawable_name() in content and p.texture_name() in content)
        check("YDD : aucun élément du display", "Buste" not in content and "CamPresentation" not in content)
        check("YDD : couleurs 255 128 0 255", "255 128 0 255" in content)
    if enc:
        ytd_xml = os.path.join(p.export_dir, f"{p.ytd_name()}.ytd.xml")
        check("YTD XML + DDS produits", os.path.isfile(ytd_xml)
              and os.path.isfile(os.path.join(p.export_dir, p.ytd_name(), f"{p.texture_name()}.dds")))
    check("Statut 7 terminé", status.step7(bpy.context, p)[0] == "Terminé")
    ps = p.preview_scene
    with bpy.context.temp_override(scene=ps, view_layer=ps.view_layers[0]):
        check("Export lancé depuis la scène d'aperçu", run("export") == {"FINISHED"} and p.last_export_ok
              and "Buste" not in open(ydd_xml, encoding="utf-8").read())
    warns = json.loads(p.last_export_files).get("warnings", [])
    check("Écart XML/DDS de szio signalé", any("DXT5" in w for w in warns) if enc else True, str(warns))
    check("Statut 8 à faire (manuel)", status.step8(bpy.context, p)[0] == "À faire")
    for c in p.cw_checks:
        c.done = True
    check("Statut 8 terminé après la checklist", status.step8(bpy.context, p)[0] == "Terminé")
    run("export")
    check("Nouvel export → checklist à revérifier", status.step8(bpy.context, p)[0] != "Terminé")

    errs = draw_all_panels()
    check("Dessin de tous les panneaux sans erreur", not errs, " | ".join(errs))

    # Sauvegarde / réouverture --------------------------------------------------------------
    print("\n[S] Sauvegarde et réouverture")
    names = {k: getattr(p, k).name for k in ("pendant_text", "plate", "bail", "chain", "ref_armature", "preview_scene",
                                             "export_root", "atlas_image", "preview_marker")}
    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=os.path.join(WORK, "projet.blend"))
    p = proj()
    check("Références conservées après réouverture",
          all(getattr(p, k) is not None and getattr(p, k).name == v for k, v in names.items()),
          str({k: (getattr(p, k).name if getattr(p, k) else None) for k in names}))
    check("Réglages conservés", p.text == "NO RULES" and p.use_atlas)
    n_obj = len(bpy.data.objects)
    run("pendant_create", update_only=True)
    run("preview_refresh")
    check("Mise à jour après réouverture sans doublon", len(bpy.data.objects) == n_obj)
    errs = draw_all_panels()
    check("Panneaux après réouverture", not errs, " | ".join(errs))

    # Chemins complémentaires --------------------------------------------------------------
    print("\n[C] Chemins complémentaires")
    old_chain = p.chain.name
    bpy.ops.mesh.primitive_torus_add(major_radius=0.1, minor_radius=0.005, location=(0, -0.05, 0.45))
    mine = bpy.context.active_object
    mine.name = "Ma_Chaine_Scene"
    check("Utiliser une chaîne de la scène", run("role_assign", role="chaine") == {"FINISHED"} and p.chain == mine
          and mine.parent == p.jewel_root)
    check("Ancienne chaîne non supprimée", old_chain in bpy.data.objects)
    multi = os.path.join(WORK, "chaine_multi.obj")
    for o in bpy.context.view_layer.objects.selected:
        o.select_set(False)
    a = bpy.data.objects.new("lien_a", bpy.data.meshes.new("lien_a"))
    b = bpy.data.objects.new("lien_b", bpy.data.meshes.new("lien_b"))
    for o, x in ((a, 0.0), (b, 0.02)):
        o.data.from_pydata([(x, 0, 0), (x + 0.01, 0, 0), (x, 0.01, 0)], [], [(0, 1, 2)])
        bpy.context.scene.collection.objects.link(o)
        o.select_set(True)
    bpy.ops.wm.obj_export(filepath=multi, export_selected_objects=True, export_materials=False)
    for o in (a, b):
        bpy.data.objects.remove(o)
    p.chain_path, p.chain_join = multi, False
    check("Import OBJ multi-objets (vide parent)", run("chain_import") == {"FINISHED"} and p.chain.type == "EMPTY"
          and len([c for c in p.chain.children if c.type == "MESH"]) == 2)
    check("Chaîne sélectionnée manuellement conservée", "Ma_Chaine_Scene" in bpy.data.objects)
    p.chain_join = True
    check("Import OBJ multi-objets (joints)", run("chain_import") == {"FINISHED"} and p.chain.type == "MESH"
          and len(p.chain.data.polygons) == 2)
    p.display_mode = "COLLECTIONS"
    run("display_analyse")
    for it in p.display_items:
        it.use = it.kind == "COLLECTION" and it.name == "Presentoir"
    check("Display en mode collections", run("display_load", force=True) == {"FINISHED"}
          and any(o.name.startswith("Buste") for o in p.preview_scene.objects)
          and not any(o.type == "CAMERA" for o in p.preview_scene.objects))

    # Dépendance manquante ---------------------------------------------------------------
    print("\n[D] Dépendance manquante")
    bpy.ops.preferences.addon_disable(module=SOLLUMZ)
    info = szb.detect(refresh=True)
    check("Sollumz désactivé détecté", not info.ok and info.errors)
    check("Matériaux refusés sans Sollumz", run("materials_setup") != {"FINISHED"})
    check("Export refusé sans Sollumz", run("export") != {"FINISHED"})
    errs = draw_all_panels()
    check("Panneaux sans Sollumz", not errs, " | ".join(errs))
    bpy.ops.preferences.addon_enable(module=SOLLUMZ)
    check("Sollumz réactivé", szb.detect(refresh=True).ok)

    check("Objets extérieurs jamais supprimés", external <= {o.name for o in bpy.data.objects},
          str(external - {o.name for o in bpy.data.objects}))

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
