"""Statuts « À faire / À vérifier / Terminé » recalculés à partir de l'état réel de la scène."""

import json
import time

import bpy

from . import colors
from . import display
from . import export
from . import presets
from . import rigging
from . import sollumz_bridge as szb
from . import svg
from . import teef
from .prefs import addon_prefs
from .utils import STATUS_CHECK, STATUS_DONE, STATUS_TODO, part_meshes

_cache = {"time": 0.0, "values": {}}


def invalidate(*_args):
    _cache["values"].clear()


def cached(key, fn):
    now = time.monotonic()
    if now - _cache["time"] > 0.5:
        _cache["values"].clear()
        _cache["time"] = now
    if key not in _cache["values"]:
        _cache["values"][key] = fn()
    return _cache["values"][key]


def _ok(issues):
    return not any(s in ("ERROR", "WARNING") for s, m, f in issues)


def teef_status(context):
    return teef.check_folder(teef.teef_dir(context))


def step1(context, proj):
    res = svg.results(proj)
    if not res:
        return STATUS_TODO, [("INFO", "Importez votre SVG (Fichier ▸ Importer ▸ SVG), sélectionnez les courbes, "
                                      "affectez les couches puis préparez.", "")]
    issues = [tuple(i) for i in json.loads(proj.svg_report or "[]")]
    if proj.svg_signature != cached("svg_sig", lambda: svg.signature(proj)):
        issues.insert(0, ("WARNING", "Réglages ou maillages modifiés depuis la préparation.",
                          "Sélectionnez les maillages et cliquez « Préparer les SVG sélectionnés »."))
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def step2(context, proj):
    issues = []
    meshes = part_meshes(proj)
    if not meshes:
        return STATUS_TODO, [("ERROR", "Aucun composant désigné.", "Importez la chaîne et ajoutez le pendentif.")]
    roles = {r for o, r in meshes}
    if "CHAIN" not in roles:
        issues.append(("WARNING", "Aucune chaîne désignée.", "Importez votre chaîne ou ajoutez-la depuis la sélection."))
    if "PENDANT" not in roles:
        issues.append(("WARNING", "Aucun pendentif désigné.", "Préparez les SVG ou ajoutez la sélection comme pendentif."))
    lost = [p for p in proj.parts if p.obj is None]
    if lost:
        issues.append(("WARNING", f"{len(lost)} composant(s) supprimé(s) de la scène.", "Retirez-les de la liste."))
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def _part_material_issues(proj):
    issues, any_sollumz = [], False
    for obj, role in part_meshes(proj):
        me = obj.data
        used = {p.material_index for p in me.polygons}
        bad = [i for i in used if i >= len(me.materials) or not szb.is_sollumz_material(me.materials[i])]
        if any(szb.is_sollumz_material(m) for m in me.materials):
            any_sollumz = True
        if bad:
            n = sum(1 for p in me.polygons if p.material_index in bad)
            issues.append(("WARNING", f"{obj.name} : {n} face(s) sans matériau Sollumz.",
                           "Sélectionnez-les en Edit Mode et appliquez un matériau."))
        for i in used:
            mat = me.materials[i] if i < len(me.materials) else None
            if not szb.is_sollumz_material(mat):
                continue
            for node in szb.texture_nodes(mat):
                if node.name == "BumpSampler" and node.image and node.image.colorspace_settings.name != "Non-Color":
                    issues.append(("ERROR", f"{mat.name} : BumpSampler n'est pas en Non-Color.", "Réappliquez le matériau."))
                if node.name in ("BumpSampler", "SpecSampler") and not node.texture_properties.embedded:
                    issues.append(("ERROR", f"{mat.name} : {node.name} n'est pas Embedded.", "Réappliquez le matériau."))
                if node.name in ("DiffuseSampler", "BumpSampler", "SpecSampler") and (node.image is None or not node.image.filepath):
                    issues.append(("ERROR", f"{mat.name} : {node.name} sans texture.", ""))
    return any_sollumz, issues


def step3(context, proj):
    if not part_meshes(proj):
        return STATUS_TODO, [("ERROR", "Désignez d'abord les composants (étape 2).", "")]
    if not szb.detect().ok:
        return STATUS_TODO, [("ERROR", " ".join(szb.detect().errors), "")]
    any_sollumz, issues = cached("mat_issues", lambda: _part_material_issues(proj))
    if not any_sollumz:
        return STATUS_TODO, issues + [("INFO", "Aucun matériau Sollumz sur le bijou.", "")]
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def step4(context, proj):
    issues = []
    for name in presets.names():
        try:
            complete, missing, absent = presets.status(presets.load(name))
        except Exception as exc:
            issues.append(("WARNING", f"Preset « {name} » illisible : {exc}", ""))
            continue
        if not complete:
            issues.append(("WARNING", f"Preset « {name} » incomplet : " +
                           ", ".join(absent + [s for s, p in missing]), "Relocalisez les textures manquantes."))
    any_sollumz, _ = cached("mat_issues", lambda: _part_material_issues(proj))
    if not any_sollumz:
        return STATUS_TODO, issues
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def step5(context, proj):
    objs = [o for o, r in part_meshes(proj)]
    if not objs:
        return STATUS_TODO, [("ERROR", "Désignez d'abord les composants (étape 2).", "")]
    issues = colors.issues_for(objs)
    if len(issues) == 2 * len(objs):
        return STATUS_TODO, issues
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def uses_glow(proj):
    for obj, role in part_meshes(proj):
        for m in obj.data.materials:
            if szb.is_sollumz_material(m) and szb.param_node(m, "emissiveMultiplier") is not None:
                return True
    return proj.mat_kind == "EMISSIVE"


def step6(context, proj):
    if not uses_glow(proj):
        return STATUS_DONE, [("INFO", "Aucun matériau émissif : pas de zone de glow à peindre.", "")]
    if not proj.glow_painted:
        return STATUS_CHECK, [("WARNING", "Peignez les zones de glow dans Color 1, puis cochez la case.", "")]
    return STATUS_DONE, []


def step7(context, proj):
    issues = [("ERROR", m, f) for s, m, f in teef.verify_armature(proj.ref_root) if s == "ERROR"]
    if issues:
        return STATUS_TODO, [("ERROR", "Squelette masculin non chargé.", "Cliquez « Charger les références Teef ».")]
    final = proj.final_obj
    if final is None:
        return STATUS_TODO, [("INFO", "mio_chain non créé.", "Cliquez « Rigger sur SKEL_Spine3 ».")]
    if not export.final_placed(proj):
        issues.append(("WARNING", "mio_chain n'est pas dans la structure teef_000_u > teef_012_u.",
                       "Cliquez « Placer mio_chain dans la structure » (étape 8)."))
    state, fresh = rigging.final_state(proj)
    if not fresh:
        issues.append(("WARNING", f"mio_chain {state}.", "Cliquez de nouveau « Rigger sur SKEL_Spine3 »."))
    mod = next((m for m in final.modifiers if m.type == "ARMATURE"), None)
    for p in cached("final_verify", lambda: rigging.verify(proj, final, arm=mod.object if mod else None)):
        issues.append(("ERROR", p, ""))
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


def step8(context, proj):
    if proj.ref_root is None:
        return STATUS_TODO, [("INFO", "Références Teef non chargées.", "Cliquez « Charger les références Teef ».")]
    if not export.final_placed(proj):
        return STATUS_CHECK, [("WARNING", "mio_chain n'est pas encore à la place de SKEL_ROOT.",
                               "Cliquez « Rigger sur SKEL_Spine3 » (étape 7).")]
    issues = []
    if not proj.export_count:
        issues.append(("INFO", "Pas encore exporté.", ""))
        return STATUS_CHECK, issues
    data = json.loads(proj.last_export or "{}")
    issues += [("ERROR", e, "") for e in data.get("errors", [])]
    if proj.last_export_sig != cached("report_sig", lambda: export.report_signature(proj)):
        issues.append(("WARNING", "Le projet a changé depuis le dernier export.", "Vérifiez puis exportez de nouveau."))
    issues.append(("INFO", "Export Blender ≠ validation FiveM : testez le bijou en jeu.", ""))
    return (STATUS_DONE if proj.last_export_ok and _ok(issues) else STATUS_CHECK), issues


def step_display(context, proj):
    if proj.preview_scene is None:
        return STATUS_TODO, [("INFO", "Facultatif : choisissez votre .blend puis « Charger le display ».", "")]
    issues = [("INFO", f"Ressource manquante dans le display — {m}", "") for m in json.loads(proj.display_missing or "[]")[:4]]
    if not display.preview_objects(proj, "copy"):
        issues.append(("WARNING", "Bijou pas encore placé sur le display.", "Cliquez « Actualiser le bijou »."))
    elif proj.preview_signature != cached("prev_sig", lambda: display.preview_signature(proj)):
        issues.append(("WARNING", "Le bijou a changé depuis le placement.", "Cliquez « Actualiser le bijou »."))
    return (STATUS_DONE if _ok(issues) else STATUS_CHECK), issues


STEPS = (
    ("1", "Préparation des SVG", step1),
    ("2", "Chaîne et composants", step2),
    ("3", "Matériaux sur les faces", step3),
    ("4", "Value Parameters et presets", step4),
    ("5", "Color Attributes", step5),
    ("6", "Glow", step6),
    ("7", "Rigging sur SKEL_Spine3", step7),
    ("8", "Structure d'export et export", step8),
    ("A", "Aperçu sur mon display", step_display),
)


def _safe(fn, context, proj):
    """Un statut qui échoue ne doit jamais casser l'affichage : l'erreur est montrée dans le panneau."""
    try:
        return fn(context, proj)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return STATUS_CHECK, [("ERROR", f"Erreur interne pendant le calcul du statut : {type(exc).__name__} : {exc}",
                               "Fenêtre ▸ Afficher la console système, puis envoyez le message rouge.")]


def compute(context, proj, key):
    for k, label, fn in STEPS:
        if k == key:
            return cached(f"step_{k}", lambda: _safe(fn, context, proj))
    raise KeyError(key)
