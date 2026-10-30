"""Sections 6, 7 et 8 : copie dédiée à l'export, rapport de vérification, export Sollumz, checklist CodeWalker."""

import json
import os
import re
import xml.etree.ElementTree as ET

import bpy
import numpy as np
from mathutils import Matrix

from . import atlas
from . import dds
from . import effects
from . import pendant
from . import rigging
from . import sollumz_bridge as szb
from .assembly import ensure_structure
from .materials import texture_issues
from .prefs import addon_prefs
from .utils import (
    McsError,
    TAG_DISPLAY,
    TAG_EXPORT,
    TAG_PREVIEW,
    TAG_PROJECT,
    abspath,
    component_objects,
    get_project,
    hash_strings,
    link_only_to,
    project_scene,
    sources_signature,
    tag,
    triangle_count_mesh,
)

RE_DRAWABLE = re.compile(r"^[a-z]{4}_\d{3}_[a-z]$")
RE_TEXTURE = re.compile(r"^[a-z]{4}_diff_\d{3}_[a-z]_[a-z]+$")


def export_objects(proj):
    pid = proj.project_id
    return [o for o in bpy.data.objects if o.get(TAG_PROJECT) == pid and o.get(TAG_EXPORT)]


def clear_export_copy(proj):
    pid = proj.project_id
    for obj in export_objects(proj):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    for mat in list(bpy.data.materials):
        if mat.get(TAG_PROJECT) == pid and mat.get(TAG_EXPORT) and mat.users == 0:
            bpy.data.materials.remove(mat)
    proj.export_root = None


def _layer_collection(layer_coll, coll):
    if layer_coll.collection == coll:
        return layer_coll
    for child in layer_coll.children:
        found = _layer_collection(child, coll)
        if found:
            return found
    return None


def _load_image(path):
    return bpy.data.images.load(path, check_existing=True) if path and os.path.isfile(path) else None


def _export_material(proj, mat):
    copy = mat.copy()
    copy.name = f"EXP_{mat.name}"
    tag(copy, proj, role="export", **{TAG_EXPORT: 1})
    if proj.use_atlas and proj.atlas_image is not None:
        rows = {r[0]: r for r in atlas.dds_status(proj)}
        for kind, sampler in atlas.KINDS:
            node = copy.node_tree.nodes.get(sampler)
            src = proj.atlas_image if kind == "diffuse" else getattr(proj, f"atlas_{kind}_image")
            if node is None or src is None or (kind != "diffuse" and not getattr(proj, f"atlas_{kind}")):
                continue
            row = rows.get(kind)
            img = _load_image(row[2]) if row and row[3] is not None else None
            node.image = img or src
            if kind != "diffuse":
                node.texture_properties.embedded = True
                img_used = node.image
                img_used.colorspace_settings.name = "Non-Color"
    return copy


def build_export_copy(context, proj):
    """Copie indépendante prête pour Sollumz : armature (DWD) > drawable > modèles. Les sources restent intactes."""
    szb.require()
    arm = rigging.require_armature(proj)
    comps = component_objects(proj)
    if not comps:
        raise McsError("Aucun composant à exporter.")
    for obj, role in comps:
        if not any(szb.is_sollumz_material(m) for m in obj.data.materials):
            raise McsError(f"{obj.name} n'a pas de matériau Sollumz (section 3).")
    ensure_structure(context, proj)
    clear_export_copy(proj)
    scene = project_scene(context)
    coll = proj.coll_export
    lc = _layer_collection(scene.view_layers[0].layer_collection, coll)
    if lc is not None:
        lc.exclude = False
        lc.hide_viewport = False
    coll.hide_viewport = False

    root = arm.copy()
    root.name = proj.ydd_name()
    tag(root, proj, role="export", **{TAG_EXPORT: 1})
    link_only_to(root, coll)
    root.parent = None
    root.matrix_world = arm.matrix_world.copy()
    root.sollum_type = szb.DWD

    drawable = bpy.data.objects.new(proj.drawable_name(), None)
    tag(drawable, proj, role="export", **{TAG_EXPORT: 1})
    link_only_to(drawable, coll)
    drawable.sollum_type = szb.DRAWABLE
    drawable.parent = root
    drawable.matrix_parent_inverse = Matrix.Identity(4)

    mats = {}
    prev_pose = arm.data.pose_position
    arm.data.pose_position = "REST"
    view_layer = scene.view_layers[0] if context.scene != scene else context.view_layer
    view_layer.update()
    try:
        dg = view_layer.depsgraph
        to_local = root.matrix_world.inverted()
        for obj, role in comps:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            mesh.name = f"EXP_{obj.name}"
            mesh.transform(to_local @ obj.matrix_world)
            if (to_local @ obj.matrix_world).determinant() < 0:
                mesh.flip_normals()
            tag(mesh, proj, role="export", **{TAG_EXPORT: 1})
            for i, mat in enumerate(mesh.materials):
                if mat is not None:
                    if mat.name not in mats:
                        mats[mat.name] = _export_material(proj, mat)
                    mesh.materials[i] = mats[mat.name]
            model = bpy.data.objects.new(f"{proj.drawable_name()}.{role}", mesh)
            tag(model, proj, role="export", **{TAG_EXPORT: 1, "mcs_src": obj.name})
            link_only_to(model, coll)
            model.parent = drawable
            model.matrix_parent_inverse = Matrix.Identity(4)
            szb.set_model(model)
            if proj.use_atlas:
                attr = mesh.attributes.get(atlas.ATTR)
                if attr is None:
                    raise McsError(f"{obj.name} : UV d'atlas absentes ; préparez l'atlas.")
                vec = np.empty(len(mesh.loops) * 3, dtype=np.float32)
                attr.data.foreach_get("vector", vec)
                uv = vec.reshape(-1, 3)[:, :2].copy()
                mesh.attributes.remove(mesh.attributes[atlas.ATTR])
                layer = mesh.uv_layers.get("UVMap 0") or mesh.uv_layers.new(name="UVMap 0")
                layer.data.foreach_set("uv", uv.ravel())
            elif mesh.attributes.get(atlas.ATTR) is not None:
                mesh.attributes.remove(mesh.attributes[atlas.ATTR])
            for mat in mesh.materials:
                if mat is not None:
                    szb.update_mesh_attributes(model, mat)
            if proj.use_vertex_colors and effects.used_color_indices(model):
                effects.apply_colors(proj, [(model, role)])
            for m in list(model.modifiers):
                model.modifiers.remove(m)
            rigging.ensure_modifier(model, root)
    finally:
        arm.data.pose_position = prev_pose
    proj.export_root = root
    proj.export_copy_sig = sources_signature(proj)
    return root


# ---------------------------------------------------------------------------
# Vérification
# ---------------------------------------------------------------------------

def _models(root):
    return [o for o in root.children_recursive if getattr(o, "sollum_type", "") == szb.MODEL]


def run_checks(context, proj):
    """[(sévérité, catégorie, message, correction, objet)]"""
    out = []

    def add(sev, cat, msg, fix="", obj=""):
        out.append((sev, cat, msg, fix, obj))

    prefs = addon_prefs(context)
    info = szb.detect(refresh=True)
    for e in info.errors:
        add("ERROR", "Dépendances", e)
    for w in info.warnings:
        add("WARNING", "Dépendances", w)
    if not info.ok:
        return out
    if not proj.export_cwxml and not proj.export_native:
        add("ERROR", "Export", "Aucun format d'export choisi.", "Cochez CodeWalker XML et/ou Binaire natif.")
    if not proj.export_gen8 and not proj.export_gen9:
        add("ERROR", "Export", "Aucune version du jeu choisie.", "Cochez Gen8 (Legacy) pour FiveM.")
    if proj.export_native and not info.native_available:
        add("ERROR", "Export", "Le format binaire natif exige PyMateria dans Sollumz (Windows).",
            "Installez PyMateria depuis les préférences de Sollumz, ou exportez en CodeWalker XML.")
    if proj.export_dir.startswith("//") and not bpy.data.filepath:
        add("ERROR", "Export", "Dossier d'export relatif alors que le .blend n'est pas enregistré.", "Enregistrez le fichier.")

    if proj.pendant_text is not None and not pendant.is_up_to_date(proj):
        add("WARNING", "Pendentif", "Les réglages du pendentif ont changé depuis la dernière génération.",
            "Cliquez « Mettre à jour le pendentif ».")

    root = proj.export_root
    if root is None:
        add("ERROR", "Copie d'export", "Aucune copie d'export.", "Cliquez « Créer / actualiser la copie d'export ».")
        return out
    if proj.export_copy_sig != sources_signature(proj):
        add("ERROR", "Copie d'export", "La copie d'export est périmée (sources modifiées depuis).",
            "Cliquez « Créer / actualiser la copie d'export ».")

    # Hiérarchie attendue par Sollumz.
    if root.type != "ARMATURE" or root.sollum_type != szb.DWD:
        add("ERROR", "Organisation", f"{root.name} doit être une armature de type Drawable Dictionary.", "", root.name)
    if re.sub(r"\.\d{3}$", "", root.name.lower()) != proj.ydd_name():
        add("ERROR", "Noms", f"Le dictionnaire s'appelle {root.name} au lieu de {proj.ydd_name()} (nom du fichier).",
            "Actualisez la copie d'export.", root.name)
    drawables = [c for c in root.children if c.sollum_type == szb.DRAWABLE]
    if len(drawables) != 1:
        add("ERROR", "Organisation", f"{len(drawables)} drawable(s) sous {root.name} (1 attendu).")
        return out
    drawable = drawables[0]
    if re.sub(r"\.\d{3}$", "", drawable.name.lower()) != proj.drawable_name():
        add("ERROR", "Noms", f"Le drawable s'appelle {drawable.name} au lieu de {proj.drawable_name()}.",
            "Un objet porte déjà ce nom ? Renommez-le puis actualisez la copie.", drawable.name)
    models = _models(root)
    if not models:
        add("ERROR", "Organisation", "Aucun Drawable Model sous le drawable.")
    included = [root] + list(root.children_recursive)
    add("INFO", "Objets inclus", f"{len(included)} objet(s) : " + ", ".join(o.name for o in included))
    for obj in included:
        if obj.get(TAG_PREVIEW) or obj.get(TAG_DISPLAY) or obj.type in {"CAMERA", "LIGHT"}:
            add("ERROR", "Exclusion", f"{obj.name} (présentation) est dans l'export.", "Retirez-le de la hiérarchie.", obj.name)
        if not obj.get(TAG_EXPORT):
            add("ERROR", "Organisation", f"{obj.name} n'appartient pas à la copie d'export.", "", obj.name)
        if proj.preview_scene is not None and proj.preview_scene in obj.users_scene:
            add("ERROR", "Exclusion", f"{obj.name} est aussi dans la scène d'aperçu.", "", obj.name)
    scene = project_scene(context)
    stray = [o.name for o in scene.objects if o.get(TAG_DISPLAY) or o.get(TAG_PREVIEW)]
    if stray:
        add("WARNING", "Exclusion", "Éléments de présentation dans la scène du projet (non exportés, non sélectionnés) : "
            + ", ".join(stray[:6]))
    elif proj.preview_scene is not None:
        add("INFO", "Exclusion", f"Display, lumières, caméras et copies d'aperçu isolés dans « {proj.preview_scene.name} ».")

    # Matériaux, textures, attributs.
    tex_names = set()
    total_tris = 0
    for model in models:
        me = model.data
        total_tris += triangle_count_mesh(me)
        if not me.materials:
            add("ERROR", "Matériaux", f"{model.name} n'a aucun matériau.", "", model.name)
        for mat in me.materials:
            if not szb.is_sollumz_material(mat):
                add("ERROR", "Matériaux", f"{model.name} : matériau non Sollumz {mat.name if mat else '(vide)'}.",
                    "Configurez les matériaux (section 3).", model.name)
                continue
            shader = szb.find_shader(szb.material_shader(mat))
            if shader is None:
                add("ERROR", "Matériaux", f"{mat.name} : shader {szb.material_shader(mat)} inconnu.", "", model.name)
                continue
            if not szb.material_shader(mat).startswith("ped"):
                add("WARNING", "Matériaux", f"{mat.name} : shader hors famille « ped » pour un composant de ped.", "", model.name)
            for sev, msg, fix in texture_issues(mat, prefs):
                add(sev, "Textures", msg, fix, model.name)
            for node in szb.texture_nodes(mat):
                if node.image and node.image.filepath and node.name in szb.shader_texture_params(szb.material_shader(mat)):
                    if not node.texture_properties.embedded:
                        tex_names.add(szb.texture_name_of_image(node.image))
            for idx in shader.used_texcoords_indices:
                if szb.uv_map_name(idx) not in me.uv_layers:
                    add("ERROR", "UV", f"{model.name} : map « {szb.uv_map_name(idx)} » exigée par {shader.filename}.", "", model.name)
        if len(me.vertices) > 65535:
            add("INFO", "Géométrie", f"{model.name} : {len(me.vertices)} sommets, Sollumz découpera la géométrie.")
    if proj.use_vertex_colors:
        for sev, msg, fix in effects.colors_issues(proj, [(m, "") for m in models]):
            add(sev, "Couleurs de sommets", msg, fix)
    limit = prefs.tri_warning if prefs else 15000
    add("WARNING" if total_tris > limit else "INFO", "Géométrie",
        f"{total_tris} triangles au total (votre seuil : {limit} ; ce n'est pas une limite officielle).")

    # Noms.
    if not RE_DRAWABLE.match(proj.drawable_name()):
        add("WARNING", "Noms", f"{proj.drawable_name()} ne suit pas le motif composant_000_u de votre référence.")
    if not RE_TEXTURE.match(proj.texture_name()):
        add("WARNING", "Noms", f"{proj.texture_name()} ne suit pas le motif teef_diff_000_a_uni de votre référence.")
    if proj.texture_name() not in tex_names:
        add("WARNING", "Noms", f"Aucun shader ne référence {proj.texture_name()} (textures référencées : "
            f"{', '.join(sorted(tex_names)) or 'aucune'}).", "Activez l'atlas ou nommez le fichier diffuse ainsi.")

    # Atlas, DDS, YTD.
    if proj.use_atlas:
        state, ok = atlas.atlas_state(proj)
        if not ok:
            add("ERROR", "Atlas", f"Atlas {state}.", "Cliquez « Préparer l'atlas ».")
        for sev, msg, fix in atlas.verify(proj):
            if sev != "INFO":
                add(sev, "Atlas", msg, fix)
    if proj.export_ytd:
        txd = szb.find_txd(scene, proj.ytd_name())
        if txd is None:
            add("ERROR", "YTD", f"Dictionnaire de textures {proj.ytd_name()} absent.", "Cliquez « Préparer le YTD ».")
        else:
            in_txd = {t.name for t in txd.textures}
            for name in sorted(tex_names - in_txd):
                add("ERROR", "YTD", f"La texture {name} référencée par le YDD n'est pas dans le YTD.", "Cliquez « Préparer le YTD ».")
            for t in txd.textures:
                img = t.image
                if img is None or (img.packed_file is None and not abspath(img.filepath).lower().endswith(".dds")):
                    add("ERROR", "YTD", f"{t.name} : le YTD exige un DDS.", "Convertissez en DDS puis préparez le YTD.")
                elif img.packed_file is not None and not bytes(img.packed_file.data[:4]) == b"DDS ":
                    add("ERROR", "YTD", f"{t.name} : données intégrées non DDS.", "")
        for kind, name, path, dinfo, issues in atlas.dds_status(proj):
            for sev, msg, fix in issues:
                add(sev, "DDS", msg, fix)
    else:
        add("WARNING", "YTD", "Export du YTD désactivé : il faudra créer le YTD avec la texture DDS dans CodeWalker.")

    # Rigging sur la copie d'export.
    for sev, msg, fix, name in rigging.analyse(proj, [(m, "") for m in models], armature=root):
        if "n'est pas à l'origine" in msg:
            sev = "WARNING"
        add(sev, "Rigging", msg, fix, name)
    return out


def report_signature(proj):
    return hash_strings([sources_signature(proj), proj.export_copy_sig, proj.export_cwxml, proj.export_native,
                         proj.export_gen8, proj.export_gen9, proj.export_ytd, proj.export_dir])


def store_report(proj, items):
    proj.report.clear()
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for sev, cat, msg, fix, obj in sorted(items, key=lambda i: order[i[0]]):
        it = proj.report.add()
        it.severity, it.category, it.message, it.fix, it.object_name = sev, cat, msg, fix, obj
    proj.report_sig = report_signature(proj)
    proj.report_count += 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _snapshot(directory):
    snap = {}
    for base, dirs, files in os.walk(directory):
        for f in files:
            p = os.path.join(base, f)
            snap[p] = os.path.getmtime(p)
    return snap


def _verify_outputs(proj, files):
    """Vérifie le contenu réel des fichiers produits ; retourne (lignes, erreurs, avertissements)."""
    lines, errors, warnings = [], [], []
    ydd, ytd = proj.ydd_name(), proj.ytd_name()
    for path in files:
        name = os.path.basename(path).lower()
        rel = os.path.relpath(path, abspath(proj.export_dir))
        if name == f"{ydd}.ydd.xml":
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as exc:
                errors.append(f"{rel} : XML invalide ({exc}).")
                continue
            names = [n.text for n in root.findall("./Item/Name")]
            if root.tag != "DrawableDictionary" or proj.drawable_name() not in names:
                errors.append(f"{rel} : drawable {proj.drawable_name()} absent ({names}).")
            skin = [h.get("value") for h in root.iter("HasSkin")]
            if not skin or any(v != "1" for v in skin):
                errors.append(f"{rel} : modèles non skinnés (HasSkin={skin}).")
            if root.find(".//Skeleton") is not None:
                errors.append(f"{rel} : squelette inclus alors qu'il doit être exclu.")
            textures = sorted({n.text for n in root.iter("Name") if n.text and n.text == proj.texture_name()})
            lines.append(f"{rel} : YDD CodeWalker XML, drawable {proj.drawable_name()}, skinné"
                         + (f", référence {textures[0]}" if textures else ""))
        elif name == f"{ytd}.ytd.xml":
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as exc:
                errors.append(f"{rel} : XML invalide ({exc}).")
                continue
            names = [n.text for n in root.findall("./Item/Name")]
            missing = [n for n in names if not os.path.isfile(os.path.join(os.path.dirname(path), ytd, f"{n}.dds"))]
            if proj.texture_name() not in names:
                errors.append(f"{rel} : texture {proj.texture_name()} absente du YTD ({names}).")
            if missing:
                errors.append(f"{rel} : DDS manquant(s) à côté du XML : {', '.join(missing)}.")
            for item in root.findall("./Item"):
                tex = item.findtext("Name")
                dds_file = os.path.join(os.path.dirname(path), ytd, f"{tex}.dds")
                if not os.path.isfile(dds_file):
                    continue
                head = dds.read_header(dds_file)
                xml_fmt = (item.findtext("Format") or "").replace("D3DFMT_", "")
                mips = item.find("MipLevels")
                xml_mips = int(mips.get("value", "0")) if mips is not None else 0
                if xml_fmt != head["format"] or xml_mips != head["mips"]:
                    warnings.append(f"{rel} : le XML annonce {xml_fmt or '?'} / {xml_mips} mip pour {tex}, le DDS est "
                                    f"{head['format']} / {head['mips']} mip (valeurs par défaut de szio). "
                                    "Vérifiez le format réel dans CodeWalker après import.")
            lines.append(f"{rel} : YTD CodeWalker XML, textures {', '.join(names)}")
        elif name.endswith(".dds"):
            try:
                i = dds.read_header(path)
                lines.append(f"{rel} : DDS {i['format']} {i['width']}×{i['height']}")
            except McsError as exc:
                errors.append(f"{rel} : {exc}")
        elif name in (f"{ydd}.ydd", f"{ytd}.ytd"):
            with open(path, "rb") as f:
                magic = f.read(4)
            if os.path.getsize(path) == 0 or not magic.startswith(b"RSC"):
                errors.append(f"{rel} : fichier binaire vide ou en-tête inattendu ({magic!r}).")
            lines.append(f"{rel} : binaire natif ({os.path.getsize(path)} octets, en-tête {magic.decode('ascii', 'replace')})")
        else:
            lines.append(f"{rel}")
    return lines, errors, warnings


def do_export(context, proj):
    items = run_checks(context, proj)
    store_report(proj, items)
    blocking = [i for i in items if i[0] == "ERROR"]
    if blocking:
        raise McsError(f"{len(blocking)} erreur(s) bloquante(s) : " + " ".join(i[2] for i in blocking[:3]))
    directory = abspath(proj.export_dir)
    os.makedirs(directory, exist_ok=True)
    before = _snapshot(directory)
    formats = [f for f, on in (("CWXML", proj.export_cwxml), ("NATIVE", proj.export_native)) if on]
    versions = [v for v, on in (("GEN8", proj.export_gen8), ("GEN9", proj.export_gen9)) if on]
    try:
        res = szb.export_assets(context, project_scene(context), proj.export_root, directory, formats, versions,
                                proj.ytd_name() if proj.export_ytd else None)
    except RuntimeError as exc:
        raise McsError(f"L'export Sollumz a échoué : {exc}") from exc
    after = _snapshot(directory)
    files = sorted(p for p, t in after.items() if p not in before or t != before[p])
    if "FINISHED" not in res or not files:
        raise McsError("Sollumz n'a produit aucun fichier (consultez le journal Info de Blender).")
    lines, errors, warnings = _verify_outputs(proj, files)
    expected = []
    for v in versions:
        sub = "" if len(versions) == 1 else v.lower()
        for f in formats:
            ext = ".xml" if f == "CWXML" else ""
            expected.append(os.path.join(directory, sub, f"{proj.ydd_name()}.ydd{ext}"))
            if proj.export_ytd:
                expected.append(os.path.join(directory, sub, f"{proj.ytd_name()}.ytd{ext}"))
    absent = [os.path.relpath(p, directory) for p in expected if not os.path.isfile(p)]
    if absent:
        errors.append("Fichiers attendus absents : " + ", ".join(absent))
    proj.last_export_files = json.dumps({"files": [os.path.relpath(p, directory) for p in files], "lines": lines,
                                         "errors": errors, "warnings": warnings, "formats": formats, "versions": versions})
    proj.export_count += 1
    proj.last_export_sig = report_signature(proj)
    proj.last_export_ok = not errors
    if not proj.cw_checks:
        reset_cw_checks(proj)
    return lines, errors, formats


CW_ITEMS = (
    ("Convertir les XML en binaires", "Si l'export est en CodeWalker XML : importez {ydd}.ydd.xml et {ytd}.ytd.xml "
     "dans CodeWalker (RPF Explorer > Import XML) pour obtenir {ydd}.ydd et {ytd}.ytd."),
    ("Le DDS est bien dans le YTD", "Ouvrez {ytd}.ytd et vérifiez que la texture {tex} y figure réellement "
     "(étape absente de la vidéo, signalée par son auteur dans le commentaire épinglé)."),
    ("Noms identiques YDD ↔ YTD", "Le shader du YDD référence {tex} : le YTD doit contenir exactement ce nom."),
    ("Taille et format de la texture", "Dans le YTD : dimensions, format DDS et mipmaps identiques au DDS exporté "
     "(le XML de Sollumz 2.9 peut annoncer DXT1 / 0 mip par défaut)."),
    ("Aperçu du modèle", "Dans CodeWalker, affichez le ped avec ce composant ({comp}) : position, matériaux, transparence."),
    ("Déformation en jeu", "Dans FiveM : bougez le personnage ; aucun sommet étiré, pendentif solidaire de la chaîne."),
    ("Émissif en jeu", "Si un matériau est émissif : l'aspect Blender n'est qu'indicatif, vérifiez de jour et de nuit."),
    ("Fichiers de stream", "Selon votre méthode (remplacement ou pack addon), préparez les noms et métadonnées "
     "attendus par FiveM : hors du périmètre de l'addon."),
)


def reset_cw_checks(proj):
    proj.cw_checks.clear()
    fmt = dict(ydd=proj.ydd_name(), ytd=proj.ytd_name(), tex=proj.texture_name(), comp=proj.component)
    for label, detail in CW_ITEMS:
        it = proj.cw_checks.add()
        it.label, it.detail = label, detail.format(**fmt)
    proj.cw_confirm_export_count = 0


class MIO_OT_export_copy(bpy.types.Operator):
    bl_idname = "mio_chain.export_copy"
    bl_label = "Créer / actualiser la copie d'export"
    bl_description = "Reconstruit la copie dédiée à l'export (les sources modifiables ne sont pas touchées)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            root = build_export_copy(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        items = run_checks(context, proj)
        store_report(proj, items)
        n = sum(1 for i in items if i[0] == "ERROR")
        self.report({"WARNING" if n else "INFO"}, f"Copie d'export {root.name} créée ; {n} erreur(s) bloquante(s).")
        return {"FINISHED"}


class MIO_OT_check(bpy.types.Operator):
    bl_idname = "mio_chain.check"
    bl_label = "Lancer la vérification"
    bl_description = "Contrôle complet avant export : erreurs bloquantes et avertissements"

    def execute(self, context):
        proj = get_project(context)
        items = run_checks(context, proj)
        store_report(proj, items)
        e = sum(1 for i in items if i[0] == "ERROR")
        w = sum(1 for i in items if i[0] == "WARNING")
        self.report({"WARNING" if e else "INFO"}, f"Vérification : {e} bloquante(s), {w} avertissement(s).")
        return {"FINISHED"}


class MIO_OT_export(bpy.types.Operator):
    bl_idname = "mio_chain.export"
    bl_label = "Exporter avec Sollumz"
    bl_description = "Vérifie, puis exporte la copie d'export avec Sollumz et contrôle les fichiers produits"

    def execute(self, context):
        proj = get_project(context)
        try:
            lines, errors, formats = do_export(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if errors:
            self.report({"ERROR"}, "Fichiers produits mais contrôle en échec : " + " ".join(errors[:3]))
            return {"FINISHED"}
        rest = " Étape restante : conversion des XML dans CodeWalker." if "CWXML" in formats and "NATIVE" not in formats else ""
        self.report({"INFO"}, f"Export Sollumz vérifié ({len(lines)} fichier(s)).{rest} "
                              "Non validé dans FiveM tant que la section 8 n'est pas faite.")
        return {"FINISHED"}


class MIO_OT_cw_reset(bpy.types.Operator):
    bl_idname = "mio_chain.cw_reset"
    bl_label = "Réinitialiser la checklist"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        reset_cw_checks(get_project(context))
        return {"FINISHED"}


class MIO_OT_open_folder(bpy.types.Operator):
    bl_idname = "mio_chain.open_folder"
    bl_label = "Ouvrir le dossier"

    path: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        path = abspath(self.path)
        if not os.path.isdir(path):
            self.report({"ERROR"}, f"Dossier introuvable : {path}")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


CLASSES = (MIO_OT_export_copy, MIO_OT_check, MIO_OT_export, MIO_OT_cw_reset, MIO_OT_open_folder)
