"""Références Teef : vérification du dossier extrait de Teef.zip et chargement par Sollumz.

Le squelette masculin vient de mp_m_freemode_01.yft.xml, passé à Sollumz comme squelette externe
(mode « Saved ») lors de l'import de teef_000_u.ydd.xml. Aucun squelette n'est généré par l'addon.
"""

import json
import os
import re
import xml.etree.ElementTree as ET

import bpy

from . import dds
from . import sollumz_bridge as szb
from .prefs import addon_prefs, save_user_prefs
from .utils import (
    McsError,
    TAG_REFERENCE,
    abspath,
    get_project,
    link_only_to,
    project_scene,
    remove_owned_object,
    tag,
)

FILES = {
    "yft": "mp_m_freemode_01.yft.xml",
    "ydd": "teef_000_u.ydd.xml",
    "bump": os.path.join("teef_000_u", "teef_normal_001.dds"),
    "spec": os.path.join("teef_000_u", "teef_spec_000.dds"),
}
EXPECTED_BONES = 128
SPINE3 = ("SKEL_Spine3", 38, 24818)
ROOT_BONE = ("SKEL_ROOT", 0)

_cache = {}


def teef_dir(context=None):
    prefs = addon_prefs(context)
    return abspath(prefs.teef_dir) if prefs and prefs.teef_dir else ""


def path_of(key, folder=None):
    folder = folder or teef_dir()
    return os.path.join(folder, FILES[key]) if folder else ""


def _parse_yft(path, issues):
    root = ET.parse(path).getroot()
    if root.tag != "Fragment":
        issues.append(("ERROR", f"{FILES['yft']} : racine <{root.tag}> au lieu de <Fragment>.", ""))
        return {}
    bones = root.findall("./Drawable/Skeleton/Bones/Item")
    info = {"bones": len(bones)}
    if len(bones) != EXPECTED_BONES:
        issues.append(("ERROR", f"{FILES['yft']} : {len(bones)} os au lieu de {EXPECTED_BONES}.", ""))
    by_name = {b.findtext("Name"): b for b in bones}
    name, idx = ROOT_BONE
    b = by_name.get(name)
    if b is None or b.find("Index").get("value") != str(idx):
        issues.append(("ERROR", f"{FILES['yft']} : {name} absent ou pas à l'index {idx}.", ""))
    name, idx, tag_value = SPINE3
    b = by_name.get(name)
    if b is None or b.find("Index").get("value") != str(idx) or b.find("Tag").get("value") != str(tag_value):
        issues.append(("ERROR", f"{FILES['yft']} : {name} absent ou différent (index {idx}, tag {tag_value} attendus).", ""))
    return info


def _parse_ydd(path, issues):
    root = ET.parse(path).getroot()
    if root.tag != "DrawableDictionary":
        issues.append(("ERROR", f"{FILES['ydd']} : racine <{root.tag}> au lieu de <DrawableDictionary>.", ""))
        return {}
    items = root.findall("./Item")
    info = {"drawables": [i.findtext("Name") for i in items]}
    if not items:
        issues.append(("ERROR", f"{FILES['ydd']} : aucun drawable.", ""))
        return info
    item = items[0]
    info["lods"] = [lvl for lvl in ("High", "Medium", "Low", "Vlow") if item.find(f"DrawableModels{lvl}") is not None]
    info["skeleton"] = item.find("Skeleton") is not None
    return info


def check_folder(folder):
    """Vérifie le dossier Teef. Retourne (ok, infos, problèmes). Résultat mis en cache selon les dates des fichiers."""
    if not folder:
        return False, {}, [("ERROR", "Aucun dossier Teef choisi.", "Sélectionnez le dossier « Teef » extrait de Teef.zip.")]
    if not os.path.isdir(folder):
        return False, {}, [("ERROR", f"Dossier introuvable : {folder}", "Vérifiez le chemin du dossier Teef.")]
    key = (folder,) + tuple(os.path.getmtime(p) if os.path.isfile(p) else 0 for p in
                            (os.path.join(folder, f) for f in FILES.values()))
    if key in _cache:
        return _cache[key]
    issues, info = [], {}
    for k, rel in FILES.items():
        if not os.path.isfile(os.path.join(folder, rel)):
            issues.append(("ERROR", f"Fichier manquant : {rel}", "Extrayez Teef.zip en conservant son arborescence."))
    if not issues:
        try:
            info["yft"] = _parse_yft(path_of("yft", folder), issues)
            info["ydd"] = _parse_ydd(path_of("ydd", folder), issues)
        except ET.ParseError as exc:
            issues.append(("ERROR", f"XML illisible : {exc}", ""))
        for k in ("bump", "spec"):
            hdr, probs = dds.verify(path_of(k, folder))
            if hdr:
                info[k] = hdr
            issues.extend(probs)
    ok = not any(s == "ERROR" for s, m, f in issues)
    if ok:
        ydd = info.get("ydd", {})
        issues.append(("INFO", f"Squelette : {info['yft']['bones']} os, SKEL_ROOT index 0, SKEL_Spine3 index 38 tag 24818.", ""))
        issues.append(("INFO", f"Modèle : drawable interne {', '.join(ydd.get('drawables', []))}, LOD "
                               f"{', '.join(ydd.get('lods', []))}, squelette intégré : {'oui' if ydd.get('skeleton') else 'non'}.", ""))
        issues.append(("INFO", f"DDS : normale {info['bump']['format']} {info['bump']['width']}×{info['bump']['height']}, "
                               f"spéculaire {info['spec']['format']} {info['spec']['width']}×{info['spec']['height']}.", ""))
    result = (ok, info, issues)
    _cache[key] = result
    return result


def reference_objects(proj):
    pid = proj.project_id
    return [o for o in bpy.data.objects if pid and o.get("mcs_project") == pid and o.get(TAG_REFERENCE)]


def verify_armature(arm):
    """Vérifie l'armature importée : 128 os, SKEL_ROOT index 0, SKEL_Spine3 index 38 tag 24818."""
    issues = []
    if arm is None or arm.type != "ARMATURE":
        return [("ERROR", "Armature du squelette masculin absente.", "Chargez les références Teef.")]
    bones = arm.data.bones
    if len(bones) != EXPECTED_BONES:
        issues.append(("ERROR", f"{arm.name} : {len(bones)} os au lieu de {EXPECTED_BONES}.", ""))
    if len(bones) == 0 or bones[0].name != ROOT_BONE[0]:
        issues.append(("ERROR", f"{arm.name} : SKEL_ROOT n'est pas l'os d'index 0.", ""))
    name, idx, tag_value = SPINE3
    i = bones.find(name)
    if i != idx:
        issues.append(("ERROR", f"{arm.name} : {name} à l'index {i} au lieu de {idx}.", ""))
    else:
        props = getattr(bones[i], "bone_properties", None)   # propriété ajoutée par Sollumz
        if props is None:
            issues.append(("ERROR", f"Tag de {name} illisible : Sollumz n'est pas actif.", ""))
        elif props.tag != tag_value:
            issues.append(("ERROR", f"{arm.name} : tag de {name} = {props.tag} au lieu de {tag_value}.", ""))
    return issues


def find_structure(root):
    """(drawable, [modèles maillage]) sous un Drawable Dictionary Sollumz."""
    drawables = [c for c in root.children if getattr(c, "sollum_type", "") == szb.DRAWABLE]
    if not drawables:
        return None, []
    drawable = drawables[0]
    models = [c for c in drawable.children if c.type == "MESH" and c.sollum_type == szb.MODEL]
    return drawable, models


def load_references(context, proj, force=False):
    """Importe la structure Teef dans la Scene Collection et y place mio_chain s'il existe.

    Résultat : teef_000_u (armature, 128 os) > teef_012_u (drawable) > mio_chain (ou SKEL_ROOT tant que
    mio_chain n'est pas construit). Retourne (racine, drawable, nom du mesh placé ou None).
    """
    from . import export
    szb.require()
    if proj.ref_root is not None and not force:
        if proj.final_obj is not None and not export.final_placed(proj):
            export.place_final(context, proj)
            return proj.ref_root, proj.ref_drawable, proj.final_obj.name
        raise McsError("Les références Teef sont déjà chargées. Utilisez « Recharger » pour les remplacer.")
    folder = teef_dir(context)
    ok, info, issues = check_folder(folder)
    if not ok:
        raise McsError("Dossier Teef invalide : " + " ".join(m for s, m, f in issues if s == "ERROR"))
    scene = project_scene(context)
    result, new = szb.import_ydd_with_external_skeleton(context, path_of("ydd", folder), path_of("yft", folder),
                                                        scene.collection)
    roots = [o for o in new if o.type == "ARMATURE" and o.sollum_type == szb.DWD]
    if "FINISHED" not in result or len(roots) != 1:
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
        raise McsError("Sollumz n'a pas produit la structure attendue (armature Drawable Dictionary). "
                       "Consultez le journal Info de Blender. La structure précédente est conservée.")
    root = roots[0]
    problems = [m for s, m, f in verify_armature(root) if s == "ERROR"]
    drawable, models = find_structure(root)
    if drawable is None or not models:
        problems.append("aucun drawable ou mesh sous l'armature importée")
    if problems:
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
        raise McsError("Références importées non conformes : " + " ; ".join(problems))
    # Remplacement : l'ancienne structure n'est retirée qu'après la réussite du nouvel import ;
    # mio_chain en est d'abord sorti (position monde conservée).
    export.release_final(proj)
    old_skeletons = [o.data for o in reference_objects(proj) if o.type == "ARMATURE"]
    for old in reference_objects(proj):
        remove_owned_object(old, proj, marker=TAG_REFERENCE)
    for data in old_skeletons:
        if data.users == 0:
            bpy.data.armatures.remove(data)     # données de l'ancien squelette importé, devenues inutilisées
    for o in new:
        link_only_to(o, scene.collection)
        tag(o, proj, role="reference", generated=False, **{TAG_REFERENCE: 1})
        base = re.sub(r"\.\d{3}$", "", o.name)
        if base != o.name and base not in bpy.data.objects:
            o.name = base          # nom d'origine (ex. SKEL_ROOT) une fois l'ancienne structure retirée
    base = re.sub(r"\.\d{3}$", "", root.data.name)
    if base != root.data.name and base not in bpy.data.armatures:
        root.data.name = base
    proj.ref_root, proj.ref_drawable, proj.ref_model = root, drawable, models[0]
    proj.ref_lod_names = json.dumps(sorted({m.name for m in szb.lod_meshes(models[0]).values() if m}))
    proj.export_target = None
    proj.replaced_signature = ""
    proj.teef_loaded_dir = folder
    export.apply_names(proj)
    placed = None
    if proj.final_obj is not None:
        rigging_mod = next((m for m in proj.final_obj.modifiers if m.type == "ARMATURE"), None)
        if rigging_mod is not None:
            rigging_mod.object = root
        export.place_final(context, proj)
        placed = proj.final_obj.name
    return root, drawable, placed


# ---------------------------------------------------------------------------

class MIO_OT_teef_check(bpy.types.Operator):
    bl_idname = "mio_chain.teef_check"
    bl_label = "Vérifier le dossier Teef"
    bl_description = "Contrôle la présence et le contenu des quatre fichiers de Teef.zip"

    def execute(self, context):
        _cache.clear()
        ok, info, issues = check_folder(teef_dir(context))
        if ok:
            save_user_prefs()
            self.report({"INFO"}, "Dossier Teef valide (chemin mémorisé).")
            return {"FINISHED"}
        self.report({"ERROR"}, " ".join(m for s, m, f in issues if s == "ERROR"))
        return {"CANCELLED"}


class MIO_OT_teef_load(bpy.types.Operator):
    bl_idname = "mio_chain.teef_load"
    bl_label = "Charger les références Teef"
    bl_description = "Importe teef_000_u.ydd.xml avec Sollumz en utilisant mp_m_freemode_01.yft.xml comme squelette"
    bl_options = {"REGISTER", "UNDO"}

    force: bpy.props.BoolProperty(name="Recharger", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        proj = get_project(context)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            root, drawable, placed = load_references(context, proj, self.force)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        child = placed or ", ".join(c.name for c in drawable.children)
        msg = f"Structure : {root.name} ({len(root.data.bones)} os) > {drawable.name} > {child}."
        if not placed:
            msg += " Cliquez « Rigger sur SKEL_Spine3 » pour y mettre mio_chain."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


CLASSES = (MIO_OT_teef_check, MIO_OT_teef_load)
