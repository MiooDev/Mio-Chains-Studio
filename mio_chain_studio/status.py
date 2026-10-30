"""Statuts des sections, recalculés à partir de l'état réel de la scène (jamais d'un simple clic).

Chaque fonction retourne (statut, [(sévérité, message, correction)]). Une modification qui invalide une
étape (texte changé, sources modifiées après la copie d'export, nouvel export après la checklist…)
fait repasser la section concernée à « À vérifier ».
"""

import json
import time

import bpy

from . import atlas
from . import dds
from . import display
from . import effects
from . import export
from . import pendant
from . import rigging
from . import sollumz_bridge as szb
from .assembly import chain_meshes, scale_warning
from .materials import component_materials, texture_issues
from .prefs import addon_prefs
from .utils import (
    STATUS_CHECK,
    STATUS_DONE,
    STATUS_TODO,
    component_objects,
    project_scene,
)

_cache = {"tick": 0, "time": 0.0, "values": {}}


def invalidate(*_args):
    _cache["tick"] += 1
    _cache["values"].clear()


def cached(key, fn):
    now = time.monotonic()
    if now - _cache["time"] > 0.5:
        _cache["values"].clear()
        _cache["time"] = now
    if key not in _cache["values"]:
        _cache["values"][key] = fn()
    return _cache["values"][key]


def _encoders():
    return dds.find_encoders()


def step1(context, proj):
    info = szb.detect()
    issues = [("ERROR", e, "") for e in info.errors] + [("WARNING", w, "") for w in info.warnings]
    if info.ok:
        formats = "CodeWalker XML" + (" et binaire natif" if info.native_available else
                                      " (binaire natif indisponible : PyMateria absent)")
        issues.append(("INFO", f"Sollumz {info.version_str} actif. Formats : {formats}.", ""))
    enc = _encoders()
    if enc:
        issues.append(("INFO", "Encodeur DDS : " + ", ".join(n for n, p in enc) + ".", ""))
    else:
        issues.append(("WARNING", "Aucun encodeur DDS (texconv ou ImageMagick) : l'atlas restera en PNG.",
                       "Installez texconv (DirectXTex) et indiquez son chemin dans les préférences de l'addon."))
    if not bpy.data.filepath:
        issues.append(("WARNING", "Le .blend n'est pas enregistré : textures et exports ne peuvent pas être rangés.",
                       "Enregistrez le fichier."))
    if not info.ok or proj.coll_root is None:
        return STATUS_TODO, issues
    return (STATUS_DONE if bpy.data.filepath else STATUS_CHECK), issues


def step2(context, proj):
    issues = []
    has_pendant = proj.pendant_text is not None
    if not has_pendant:
        issues.append(("ERROR", "Pendentif non créé.", "Écrivez le texte puis « Créer le pendentif »."))
    elif not pendant.is_up_to_date(proj):
        issues.append(("WARNING", "Réglages modifiés depuis la génération.", "Cliquez « Mettre à jour le pendentif »."))
    chains = chain_meshes(proj)
    if not chains:
        issues.append(("ERROR", "Aucune chaîne.", "Importez un .obj ou utilisez la chaîne sélectionnée."))
    else:
        warn = scale_warning(proj, chains)
        if warn:
            issues.append(("WARNING", warn, ""))
        root = proj.jewel_root
        if root is not None and proj.chain is not None and proj.chain.parent != root:
            issues.append(("WARNING", "La chaîne n'est plus rattachée à la racine du bijou.",
                           "Réattribuez-la (bouton « Utiliser la sélection »)."))
    if proj.pendant_pivot is not None and proj.jewel_root is not None and proj.pendant_pivot.parent != proj.jewel_root:
        issues.append(("WARNING", "Le pivot du pendentif n'est plus rattaché à la racine.", ""))
    if proj.ref_model is None:
        issues.append(("INFO", "Aucun modèle de référence : la taille de la chaîne n'est pas comparée.", ""))
    if not has_pendant and not chains:
        return STATUS_TODO, issues
    ok = not any(s in ("ERROR", "WARNING") for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step3(context, proj):
    issues = []
    comps = component_objects(proj)
    if not comps:
        return STATUS_TODO, [("ERROR", "Aucun composant.", "Créez le pendentif et la chaîne (section 2).")]
    prefs = addon_prefs(context)
    any_mat = False
    for obj, role in comps:
        mats = [m for m in obj.data.materials if szb.is_sollumz_material(m)]
        if not mats:
            issues.append(("ERROR", f"{obj.name} : aucun matériau Sollumz.", "Cliquez « Créer / configurer les matériaux »."))
            continue
        any_mat = True
        if len(mats) != len(obj.data.materials):
            issues.append(("ERROR", f"{obj.name} : emplacement de matériau non Sollumz.", "Cliquez « Créer / configurer »."))
        wanted = proj.shader_for(role)
        if any(szb.material_shader(m) != wanted for m in mats):
            issues.append(("WARNING", f"{obj.name} : shader différent du choix ({wanted}).", "Cliquez « Créer / configurer »."))
    seen = set()
    for obj, role, i, mat in component_materials(proj):
        if mat.name in seen:
            continue
        seen.add(mat.name)
        issues.extend(texture_issues(mat, prefs))
    if proj.use_atlas:
        state, ok = cached("atlas_state", lambda: atlas.atlas_state(proj))
        if not ok:
            issues.append(("ERROR", f"Atlas {state}.", "Cliquez « Préparer l'atlas »."))
    if proj.export_ytd and any_mat:
        rows = cached("dds_status", lambda: atlas.dds_status(proj))
        if not rows:
            issues.append(("ERROR", "Aucune texture diffuse pour le YTD.", ""))
        for kind, name, path, info, probs in rows:
            if info is None:
                issues.append(("WARNING", f"{name} : pas encore de DDS.", "Convertissez en DDS (ou indiquez un DDS)."))
            else:
                issues.extend(probs)
        txd = szb.find_txd(project_scene(context), proj.ytd_name())
        names = {t.name for t in txd.textures} if txd else set()
        if not txd or any(r[1] not in names for r in rows if r[0] == "diffuse"):
            issues.append(("WARNING", "YTD Sollumz non préparé ou incomplet.", "Cliquez « Préparer le YTD »."))
    if not any_mat:
        return STATUS_TODO, issues
    ok = not any(s in ("ERROR", "WARNING") for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step4(context, proj):
    issues = []
    mats = component_materials(proj)
    if not mats:
        return STATUS_TODO, [("ERROR", "Configurez d'abord les matériaux (section 3).", "")]
    for obj, role, i, mat in mats:
        value = effects.emissive_value(mat)
        if value is not None:
            sev = "WARNING" if value <= 0 else "INFO"
            issues.append((sev, f"{mat.name} : émissif ({szb.material_shader(mat)}, emissiveMultiplier = {value:g}).",
                           "Valeur nulle : aucun effet." if value <= 0 else ""))
    if proj.use_vertex_colors:
        issues.extend(cached("colors", lambda: effects.colors_issues(proj)))
    else:
        issues.append(("WARNING", "Couleurs de sommets non préparées : Sollumz créera des attributs blancs "
                                  "(255 255 255 255), différents de votre référence (255 128 0 255).", ""))
    ok = not any(s in ("ERROR", "WARNING") for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step5(context, proj):
    issues = []
    arm = proj.ref_armature
    if arm is None:
        return STATUS_TODO, [("ERROR", "Aucune armature de référence.", "Choisissez l'armature du ped.")]
    comps = component_objects(proj)
    bones = {b.name for b in arm.data.bones}
    for obj, role in comps:
        if not any(m.type == "ARMATURE" and m.object == arm for m in obj.modifiers):
            issues.append(("ERROR", f"{obj.name} : non lié à {arm.name}.", "Cliquez « Lier à l'armature »."))
        if not obj.vertex_groups:
            issues.append(("ERROR", f"{obj.name} : aucun poids.", "Générez les poids."))
        else:
            unknown = [g.name for g in obj.vertex_groups if g.name not in bones]
            if unknown:
                issues.append(("ERROR", f"{obj.name} : groupes inconnus de l'armature ({', '.join(unknown[:3])}).", ""))
    sig = cached("rig_sig", lambda: rigging.rig_signature(proj))
    if proj.rig_report_sig != sig:
        issues.append(("WARNING", "Analyse détaillée des poids absente ou périmée.", "Cliquez « Vérifier le rigging »."))
    else:
        for it in proj.rig_report:
            if it.severity != "INFO":
                issues.append((it.severity, it.message, it.fix))
    if not (proj.deform_confirmed and proj.deform_confirmed_sig == sig):
        issues.append(("WARNING", "Déformation non vérifiée visuellement depuis la dernière modification.",
                       "Testez la déformation puis confirmez."))
    if not comps:
        return STATUS_TODO, issues
    ok = not any(s in ("ERROR", "WARNING") for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step_display(context, proj):
    issues = []
    if proj.preview_scene is None:
        return STATUS_TODO, [("ERROR", "Display non chargé.", "Choisissez le .blend puis « Charger le display ».")]
    missing = json.loads(proj.display_missing or "[]")
    for m in missing[:8]:
        issues.append(("WARNING", f"Ressource externe manquante — {m}", ""))
    if proj.preview_marker is None:
        issues.append(("ERROR", "Aucun repère de placement.", "Définissez le repère du bijou."))
    else:
        prefs = addon_prefs(context)
        if prefs and display.marker_key(proj.display_loaded_path) not in prefs.markers():
            issues.append(("INFO", "Repère non enregistré pour les projets suivants.", "Cliquez « Enregistrer le repère »."))
    if not display.preview_objects(proj, "copy"):
        issues.append(("ERROR", "Bijou non placé sur le display.", "Cliquez « Placer le bijou sur le display »."))
    elif proj.preview_signature != cached("prev_sig", lambda: display.preview_signature(proj)):
        issues.append(("WARNING", "Aperçu périmé : le bijou a changé.", "Cliquez « Actualiser l'aperçu »."))
    if proj.render_camera is None:
        issues.append(("WARNING", "Aucune caméra choisie pour le rendu.", ""))
    ok = not any(s in ("ERROR", "WARNING") for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step6(context, proj):
    if not proj.report_count:
        return STATUS_TODO, [("ERROR", "Vérification jamais lancée.", "Créez la copie d'export puis vérifiez.")]
    issues = []
    stale = proj.report_sig != cached("report_sig", lambda: export.report_signature(proj))
    if stale:
        issues.append(("WARNING", "Rapport périmé : le projet a changé depuis la vérification.", "Relancez la vérification."))
    errors = sum(1 for i in proj.report if i.severity == "ERROR")
    warnings = sum(1 for i in proj.report if i.severity == "WARNING")
    if errors:
        issues.append(("ERROR", f"{errors} erreur(s) bloquante(s) dans le rapport.", "Corrigez-les (détail ci-dessous)."))
    if warnings:
        issues.append(("INFO", f"{warnings} avertissement(s) à lire.", ""))
    if errors:
        return STATUS_TODO, issues
    return (STATUS_CHECK if stale else STATUS_DONE), issues


def step7(context, proj):
    if not proj.export_count:
        return STATUS_TODO, [("INFO", "Aucun export réalisé.", "")]
    data = json.loads(proj.last_export_files or "{}")
    issues = [("ERROR", e, "") for e in data.get("errors", [])]
    issues += [("INFO", w, "") for w in data.get("warnings", [])]
    if proj.last_export_sig != cached("report_sig", lambda: export.report_signature(proj)):
        issues.append(("WARNING", "Le projet a changé depuis le dernier export.", "Vérifiez puis exportez de nouveau."))
    ok = proj.last_export_ok and not any(s != "INFO" for s, m, f in issues)
    return (STATUS_DONE if ok else STATUS_CHECK), issues


def step8(context, proj):
    if not proj.export_count:
        return STATUS_TODO, [("INFO", "Exportez d'abord le bijou.", "")]
    done = [c for c in proj.cw_checks if c.done]
    issues = []
    if not proj.cw_checks:
        return STATUS_TODO, [("INFO", "Checklist non initialisée.", "Cliquez « Réinitialiser la checklist ».")]
    if proj.cw_confirm_export_count < proj.export_count:
        issues.append(("WARNING", "Nouvel export depuis vos vérifications : refaites-les.", ""))
        return STATUS_CHECK if done else STATUS_TODO, issues
    if len(done) < len(proj.cw_checks):
        issues.append(("INFO", f"{len(done)}/{len(proj.cw_checks)} point(s) vérifié(s).", ""))
        return STATUS_CHECK if done else STATUS_TODO, issues
    return STATUS_DONE, issues


STEPS = (
    ("1", "Préparer le projet", step1),
    ("2", "Créer et assembler le bijou", step2),
    ("3", "Matériaux et textures", step3),
    ("4", "Effets", step4),
    ("5", "Préparer le rigging", step5),
    ("A", "Aperçu sur mon display", step_display),
    ("6", "Vérifier avant export", step6),
    ("7", "Exporter", step7),
    ("8", "Vérifier dans CodeWalker", step8),
)


def compute(context, proj, key):
    for k, label, fn in STEPS:
        if k == key:
            return cached(f"step_{k}", lambda: fn(context, proj))
    raise KeyError(key)
