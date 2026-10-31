"""Étape 8 : structure d'export unique, placement de mio_chain à la place de SKEL_ROOT, vérification, export.

« Charger les références Teef » importe avec Sollumz : teef_000_u (armature Drawable Dictionary, squelette
masculin, 128 os) > teef_012_u (Drawable) > SKEL_ROOT (Drawable Model). Cette structure EST celle qui est
exportée : le mesh mio_chain (étape 7) y prend la place de SKEL_ROOT, après vérification. L'armature et
ses os ne sont jamais modifiés.
"""

import json
import os
import re
import xml.etree.ElementTree as ET

import bpy

from . import colors
from . import dds
from . import rigging
from . import sollumz_bridge as szb
from . import teef
from .prefs import addon_prefs
from .utils import (
    McsError,
    TAG_DISPLAY,
    TAG_PREVIEW,
    TAG_REFERENCE,
    abspath,
    get_project,
    hash_strings,
    link_only_to,
    matrix_key,
    project_scene,
    triangle_count,
)

BONE_INDEX = 38
COLUMNS = {"Position": 3, "BlendWeights": 4, "BlendIndices": 4, "Normal": 3, "Colour0": 4, "Colour1": 4,
           "Tangent": 4, **{f"TexCoord{i}": 2 for i in range(8)}}


def strip_suffix(name):
    return re.sub(r"\.\d{3}$", "", name)


def final_placed(proj):
    final, root = proj.final_obj, proj.ref_root
    return final is not None and root is not None and final in root.children_recursive


def release_final(proj):
    """Sort mio_chain de la structure en gardant sa position monde (avant un rechargement des références)."""
    final = proj.final_obj
    if final is None or not final_placed(proj):
        return False
    world = final.matrix_world.copy()
    final.parent = None
    final.matrix_world = world
    final.sollum_type = "sollumz_none"
    return True


def _target_candidates(proj):
    drawable = proj.ref_drawable
    if drawable is None:
        return []
    return [c for c in drawable.children if c.type == "MESH" and c.sollum_type == szb.MODEL
            and c != proj.final_obj and c.get(TAG_REFERENCE)]


def apply_lods(proj):
    """LOD du mesh placé selon le réglage : High seul, ou High recopié en Medium et Low (non optimisé)."""
    final = proj.final_obj
    high = final.data
    dup = proj.lod_mode == "DUPLICATE"
    szb.set_lods(final, {"sollumz_high": high, "sollumz_medium": high if dup else None,
                         "sollumz_low": high if dup else None, "sollumz_verylow": None})


def place_final(context, proj):
    """Met mio_chain à la place du mesh de référence (SKEL_ROOT) : même parent, type Sollumz, skinning, LOD."""
    szb.require()
    root, drawable, final = proj.ref_root, proj.ref_drawable, proj.final_obj
    if root is None or drawable is None or teef.verify_armature(root):
        raise McsError("Références Teef non chargées : cliquez « Charger les références Teef ».")
    if final is None:
        raise McsError("Aucun mesh mio_chain : cliquez « Rigger sur SKEL_Spine3 » (étape 7).")
    state, fresh = rigging.final_state(proj)
    if not fresh:
        raise McsError(f"mio_chain {state} : relancez l'étape 7.")
    problems = rigging.verify(proj, final, arm=root)
    if problems:
        raise McsError("mio_chain non conforme : " + " ".join(problems))
    target = proj.export_target
    if target is None:
        candidates = _target_candidates(proj)
        if len(candidates) > 1:
            raise McsError("Plusieurs meshes sous le drawable : choisissez le mesh à remplacer.")
        target = candidates[0] if candidates else None
    if target is not None and (target == final or target.type != "MESH" or target not in root.children_recursive
                               or not target.get(TAG_REFERENCE)):
        raise McsError(f"{target.name} n'est pas le mesh de référence de la structure Teef : remplacement refusé.")
    if target is None and final_placed(proj):
        apply_lods(proj)                      # déjà en place : seuls les LOD sont réappliqués
        problems = verify_replacement(proj)
        if problems:
            raise McsError("Structure non conforme : " + " ".join(problems))
        return None

    saved = dict(parent=final.parent, parent_type=final.parent_type, parent_bone=final.parent_bone,
                 inverse=final.matrix_parent_inverse.copy(), world=final.matrix_world.copy(),
                 sollum=final.sollum_type, lods=szb.lod_meshes(final),
                 mods=[(m, getattr(m, "object", None)) for m in final.modifiers],
                 colls=list(final.users_collection))
    world = final.matrix_world.copy()
    parent = target.parent if target is not None else drawable
    try:
        final.parent = parent
        final.parent_type = target.parent_type if target is not None else "OBJECT"
        final.parent_bone = target.parent_bone if target is not None else ""
        final.matrix_parent_inverse = parent.matrix_world.inverted()
        final.matrix_world = world
        link_only_to(final, drawable.users_collection[0])
        apply_lods(proj)
        rigging.ensure_armature_modifier(final, root)
        context.view_layer.update()
        problems = verify_replacement(proj, world, keep_target=target)
        if problems:
            raise McsError("Nouvelle structure non conforme : " + " ".join(problems))
    except Exception:
        final.parent = saved["parent"]
        final.parent_type = saved["parent_type"]
        final.parent_bone = saved["parent_bone"]
        final.matrix_parent_inverse = saved["inverse"]
        final.matrix_world = saved["world"]
        szb.set_lods(final, saved["lods"])
        final.sollum_type = saved["sollum"]
        for m, o in saved["mods"]:
            if m.name in final.modifiers:
                m.object = o
        for c in saved["colls"]:
            if final.name not in c.objects:
                c.objects.link(final)
        for c in list(final.users_collection):
            if c not in saved["colls"]:
                c.objects.unlink(final)
        raise
    removed = None
    if target is not None:
        removed = target.name
        if proj.ref_model == target:
            proj.ref_model = None
        bpy.data.objects.remove(target, do_unlink=True)
    proj.export_target = None
    problems = verify_replacement(proj, world)
    if problems:
        raise McsError("Après retrait du mesh de référence : " + " ".join(problems) + " Utilisez Ctrl+Z.")
    proj.replaced_signature = rigging.final_signature(proj)
    return removed


def exported_lods(final):
    return [label for lvl, label in szb.LOD_LEVELS if szb.lod_meshes(final).get(lvl) is not None]


def verify_replacement(proj, world=None, keep_target=None):
    problems = []
    root, drawable, final = proj.ref_root, proj.ref_drawable, proj.final_obj
    problems += [m for s, m, f in teef.verify_armature(root)]
    found, models = teef.find_structure(root) if root else (None, [])
    if found != drawable:
        problems.append("drawable introuvable sous l'armature.")
    expected = [final] + ([keep_target] if keep_target is not None else [])
    if sorted(o.name for o in models) != sorted(o.name for o in expected if o is not None):
        problems.append(f"meshes sous le drawable : {[o.name for o in models]}.")
    if final is not None:
        if final.parent != drawable:
            problems.append("mio_chain n'a pas le drawable pour parent.")
        if world is not None and max(abs(a - b) for ra, rb in zip(final.matrix_world, world) for a, b in zip(ra, rb)) > 1e-5:
            problems.append("la position monde du bijou a changé.")
        mod = next((m for m in final.modifiers if m.type == "ARMATURE"), None)
        if mod is None or mod.object != root:
            problems.append("mio_chain n'est pas lié à l'armature teef_000_u.")
        problems += rigging.verify(proj, final, arm=root)
        ref_lods = set(json.loads(proj.ref_lod_names or "[]"))
        for lvl, mesh in szb.lod_meshes(final).items():
            if mesh is not None and (mesh.name in ref_lods or mesh != final.data):
                problems.append(f"LOD {lvl} : ancienne géométrie ou maillage inattendu ({mesh.name}).")
    return problems


def apply_names(proj):
    """Renomme l'armature et le drawable selon les noms de sortie choisis. Retourne les changements."""
    changes = []
    for obj, wanted in ((proj.ref_root, proj.output_name.strip()), (proj.ref_drawable, proj.drawable_name.strip())):
        if obj is not None and wanted and strip_suffix(obj.name) != wanted:
            old = obj.name
            obj.name = wanted
            changes.append(f"{old} → {obj.name}")
    return changes


# ---------------------------------------------------------------------------
# Vérification avant export
# ---------------------------------------------------------------------------

def run_checks(context, proj):
    out = []

    def add(sev, cat, msg, fix="", obj=""):
        out.append((sev, cat, msg, fix, obj))

    info = szb.detect(refresh=True)
    for e in info.errors:
        add("ERROR", "Dépendances", e)
    for w in info.warnings:
        add("WARNING", "Dépendances", w)
    if not info.ok:
        return out
    if not proj.export_cwxml and not proj.export_native:
        add("ERROR", "Export", "Aucun format choisi.", "Cochez CodeWalker XML et/ou Binaire natif.")
    if not proj.export_gen8 and not proj.export_gen9:
        add("ERROR", "Export", "Aucune version du jeu choisie.", "Cochez Gen8 (Legacy).")
    if proj.export_native and not info.native_available:
        add("ERROR", "Export", "Le binaire natif exige PyMateria dans Sollumz (Windows).", "Exportez en CodeWalker XML.")
    if proj.export_dir.startswith("//") and not bpy.data.filepath:
        add("ERROR", "Export", "Dossier relatif alors que le .blend n'est pas enregistré.", "Enregistrez le fichier.")
    root, drawable, final = proj.ref_root, proj.ref_drawable, proj.final_obj
    if root is None:
        add("ERROR", "Structure", "Références Teef non chargées.", "Cliquez « Charger les références Teef ».")
        return out
    if strip_suffix(root.name) != proj.output_name.strip():
        add("WARNING", "Noms", f"L'armature s'appelle {root.name} : elle sera renommée {proj.output_name} à l'export.",
            "", root.name)
    if drawable is not None and strip_suffix(drawable.name) != proj.drawable_name.strip():
        add("WARNING", "Noms", f"Le drawable s'appelle {drawable.name} : il sera renommé {proj.drawable_name} à l'export.",
            "", drawable.name)
    if not final_placed(proj):
        add("ERROR", "Structure", "mio_chain n'est pas encore à la place de SKEL_ROOT.",
            "Cliquez « Rigger sur SKEL_Spine3 » (étape 7) ou « Placer mio_chain dans la structure ».")
    else:
        if proj.replaced_signature != rigging.final_signature(proj):
            add("ERROR", "Structure", "Les composants ont changé depuis le remplacement.", "Refaites les étapes 7 et 8.")
        for p in verify_replacement(proj):
            add("ERROR", "Structure", p)
        add("INFO", "LOD", "Niveaux exportés : " + ", ".join(exported_lods(final)) +
            (" (Medium et Low = copie du High, non optimisée)" if proj.lod_mode == "DUPLICATE" else
             " (Medium et Low vides)"))
        me = final.data
        prefs = addon_prefs(context)
        tris = triangle_count(me)
        limit = prefs.tri_warning if prefs else 15000
        add("WARNING" if tris > limit else "INFO", "Géométrie",
            f"{tris} triangles (votre seuil : {limit}, pas une limite officielle).")
        for mi, mat in enumerate(me.materials):
            if not szb.is_sollumz_material(mat):
                used = any(p.material_index == mi for p in me.polygons)
                if used:
                    add("ERROR", "Matériaux", f"Faces sans matériau Sollumz (emplacement {mi} : "
                        f"{mat.name if mat else 'vide'}).", "Appliquez un matériau aux faces concernées (étape 3).", final.name)
                continue
            shader = szb.find_shader(szb.material_shader(mat))
            for idx in shader.used_texcoords_indices:
                if szb.uv_map_name(idx) not in me.uv_layers:
                    add("ERROR", "UV", f"Map « {szb.uv_map_name(idx)} » exigée par {shader.filename}.", "", final.name)
            for node in szb.texture_nodes(mat):
                if node.name not in ("DiffuseSampler", "BumpSampler", "SpecSampler"):
                    continue
                img = node.image
                label = f"{mat.name} › {node.name}"
                if img is None or not img.filepath:
                    add("ERROR", "Textures", f"{label} : aucune texture.", "Étape 3 ou 4.")
                    continue
                if img.packed_file is None and not os.path.isfile(abspath(img.filepath)):
                    add("ERROR", "Textures", f"{label} : fichier introuvable ({abspath(img.filepath)}).", "")
                if node.name in ("BumpSampler", "SpecSampler") and not node.texture_properties.embedded:
                    add("ERROR", "Textures", f"{label} doit être Embedded.", "Réappliquez le matériau (étape 3).")
                if node.name == "BumpSampler" and img.colorspace_settings.name != "Non-Color":
                    add("ERROR", "Textures", f"{label} doit être en Non-Color.", "Réappliquez le matériau (étape 3).")
                if node.texture_properties.embedded and not abspath(img.filepath).lower().endswith(".dds"):
                    add("ERROR", "Textures", f"{label} : texture intégrée non DDS.", "Utilisez un fichier .dds.")
                if node.name == "DiffuseSampler" and not node.texture_properties.embedded:
                    add("WARNING", "Textures", f"{label} non intégrée : la texture "
                        f"{szb.texture_name_of_image(img)} devra être fournie dans un YTD.", "")
        for sev, msg, fix in colors.issues_for([final]):
            add(sev, "Color Attributes", msg, fix, final.name)
    included = [root] + list(root.children_recursive)
    add("INFO", "Objets inclus", ", ".join(o.name for o in included))
    for obj in included:
        if obj.get(TAG_PREVIEW) or obj.get(TAG_DISPLAY) or obj.type in {"CAMERA", "LIGHT"}:
            add("ERROR", "Exclusion", f"{obj.name} (présentation) est dans l'export.", "", obj.name)
        if proj.preview_scene is not None and proj.preview_scene in obj.users_scene:
            add("ERROR", "Exclusion", f"{obj.name} est aussi dans la scène d'aperçu.", "", obj.name)
    if proj.preview_scene is not None:
        add("INFO", "Exclusion", f"Display, lumières, caméras et copies d'aperçu isolés dans « {proj.preview_scene.name} ».")
    return out


def report_signature(proj):
    final = proj.final_obj
    return hash_strings([proj.replaced_signature, rigging.final_signature(proj), proj.output_name, proj.drawable_name,
                         proj.lod_mode, proj.export_cwxml, proj.export_native, proj.export_gen8, proj.export_gen9,
                         proj.export_dir, matrix_key(final.matrix_world) if final else "-"])


def store_report(proj, items):
    proj.report.clear()
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for sev, cat, msg, fix, obj in sorted(items, key=lambda i: order[i[0]]):
        it = proj.report.add()
        it.severity, it.category, it.message, it.fix, it.object_name = sev, cat, msg, fix, obj
    proj.report_sig = report_signature(proj)
    proj.report_count += 1


# ---------------------------------------------------------------------------
# Export et relecture des fichiers produits
# ---------------------------------------------------------------------------

def _snapshot(directory):
    snap = {}
    for base, dirs, files in os.walk(directory):
        for f in files:
            p = os.path.join(base, f)
            snap[p] = os.path.getmtime(p)
    return snap


def analyse_vertex_buffers(item):
    """Poids et indices d'os de tous les sommets d'un drawable CW XML."""
    stats = {"vertices": 0, "spine3_full": 0, "colour0": set(), "colour1": set()}
    for vb in item.iter("VertexBuffer"):
        layout = vb.find("Layout")
        data = vb.findtext("Data") or ""
        if layout is None:
            continue
        cols, off = {}, 0
        for child in layout:
            size = COLUMNS.get(child.tag, 0)
            cols[child.tag] = (off, size)
            off += size
        for line in data.strip().splitlines():
            vals = line.split()
            if len(vals) < off:
                continue
            stats["vertices"] += 1
            if "BlendWeights" in cols and "BlendIndices" in cols:
                wo, ws = cols["BlendWeights"]
                io, isz = cols["BlendIndices"]
                w = [int(float(x)) for x in vals[wo:wo + ws]]
                i = [int(float(x)) for x in vals[io:io + isz]]
                nz = [k for k, x in enumerate(w) if x]
                if len(nz) == 1 and w[nz[0]] == 255 and i[nz[0]] == BONE_INDEX:
                    stats["spine3_full"] += 1
            for name in ("Colour0", "Colour1"):
                if name in cols:
                    o, s = cols[name]
                    stats[name.lower()].add(" ".join(vals[o:o + s]))
    return stats


def verify_outputs(proj, files, directory):
    lines, errors, warnings = [], [], []
    ydd = proj.output_name.strip().lower()
    expected_lods = ["High"] + (["Medium", "Low"] if proj.lod_mode == "DUPLICATE" else [])
    for path in files:
        rel = os.path.relpath(path, directory)
        name = os.path.basename(path).lower()
        if name == f"{ydd}.ydd.xml":
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as exc:
                errors.append(f"{rel} : XML invalide ({exc}).")
                continue
            items = root.findall("./Item")
            names = [i.findtext("Name") for i in items]
            if root.tag != "DrawableDictionary" or names != [proj.drawable_name.strip().lower()]:
                errors.append(f"{rel} : drawables {names} au lieu de [{proj.drawable_name}].")
                continue
            item = items[0]
            lods = [lvl for lvl in ("High", "Medium", "Low", "Vlow") if item.find(f"DrawableModels{lvl}") is not None]
            if lods != expected_lods:
                errors.append(f"{rel} : LOD exportés {lods} au lieu de {expected_lods}.")
            if item.find("Skeleton") is not None:
                errors.append(f"{rel} : squelette inclus alors qu'il doit être exclu.")
            skin = [h.get("value") for h in item.iter("HasSkin")]
            if not skin or any(v != "1" for v in skin):
                errors.append(f"{rel} : modèles non skinnés (HasSkin={skin}).")
            stats = analyse_vertex_buffers(item)
            if stats["vertices"] == 0 or stats["spine3_full"] != stats["vertices"]:
                errors.append(f"{rel} : {stats['spine3_full']}/{stats['vertices']} sommets à 100 % sur l'os {BONE_INDEX}.")
            embedded = [t.findtext("Name") for t in item.findall("./ShaderGroup/TextureDictionary/Item")]
            for tex in embedded:
                dds_path = os.path.join(os.path.dirname(path), ydd, f"{tex}.dds")
                if not os.path.isfile(dds_path):
                    errors.append(f"{rel} : DDS intégré {tex}.dds absent du dossier {ydd}/.")
                else:
                    try:
                        dds.read_header(dds_path)
                    except McsError as exc:
                        errors.append(f"{rel} : {exc}")
            lines.append(f"{rel} : YDD CodeWalker XML, drawable {names[0]}, LOD {', '.join(lods)}, "
                         f"{stats['vertices']} sommets à 100 % sur l'os {BONE_INDEX} (SKEL_Spine3), "
                         f"textures intégrées : {', '.join(embedded) or 'aucune'}")
            lines.append(f"Colour0 : {len(stats['colour0'])} valeur(s) distincte(s) ; Colour1 : "
                         f"{len(stats['colour1'])} valeur(s) distincte(s)")
        elif name == f"{ydd}.ydd":
            with open(path, "rb") as f:
                magic = f.read(4)
            if os.path.getsize(path) == 0 or not magic.startswith(b"RSC"):
                errors.append(f"{rel} : binaire vide ou en-tête inattendu ({magic!r}).")
            lines.append(f"{rel} : YDD binaire natif ({os.path.getsize(path)} octets)")
        elif name.endswith(".dds"):
            try:
                h = dds.read_header(path)
                lines.append(f"{rel} : DDS {h['format']} {h['width']}×{h['height']}")
            except McsError as exc:
                errors.append(f"{rel} : {exc}")
        else:
            lines.append(rel)
    return lines, errors, warnings


def do_export(context, proj):
    szb.require()                 # message clair si Sollumz est absent ou désactivé
    apply_names(proj)
    if final_placed(proj):
        apply_lods(proj)
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
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        res = szb.export_assets(context, project_scene(context), proj.ref_root, directory, formats, versions)
    except RuntimeError as exc:
        raise McsError(f"L'export Sollumz a échoué : {exc}") from exc
    after = _snapshot(directory)
    files = sorted(p for p, t in after.items() if p not in before or t != before[p])
    if "FINISHED" not in res or not files:
        raise McsError("Sollumz n'a produit aucun fichier (consultez le journal Info de Blender).")
    lines, errors, warnings = verify_outputs(proj, files, directory)
    for v in versions:
        sub = "" if len(versions) == 1 else v.lower()
        for f in formats:
            path = os.path.join(directory, sub, f"{proj.output_name.strip().lower()}.ydd" + (".xml" if f == "CWXML" else ""))
            if not os.path.isfile(path):
                errors.append(f"Fichier attendu absent : {os.path.relpath(path, directory)}")
    proj.last_export = json.dumps({"files": [os.path.relpath(p, directory) for p in files], "lines": lines,
                                   "errors": errors, "warnings": warnings, "formats": formats, "versions": versions})
    proj.export_count += 1
    proj.last_export_sig = report_signature(proj)
    proj.last_export_ok = not errors
    return lines, errors, formats


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_export_place(bpy.types.Operator):
    bl_idname = "mio_chain.export_place"
    bl_label = "Placer mio_chain dans la structure"
    bl_description = ("Met mio_chain à la place du mesh de référence SKEL_ROOT sous teef_012_u (même parent, "
                      "type Sollumz, skinning, LOD), vérifie, puis retire SKEL_ROOT")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            removed = place_final(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{proj.final_obj.name} en place sous {proj.ref_drawable.name}"
                              + (f", {removed} retiré" if removed else " (LOD réappliqués)")
                              + f". LOD : {', '.join(exported_lods(proj.final_obj))}.")
        return {"FINISHED"}


class MIO_OT_export_check(bpy.types.Operator):
    bl_idname = "mio_chain.export_check"
    bl_label = "Vérifier avant export"
    bl_description = "Contrôle complet : structure, squelette, poids, LOD, matériaux, textures, Color Attributes, exclusions"

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
    bl_description = "Vérifie puis lance l'export Sollumz du modèle d'export et relit les fichiers produits"

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
        rest = " Restant : convertir le XML dans CodeWalker." if formats == ["CWXML"] else ""
        self.report({"INFO"}, f"Export Sollumz relu et conforme ({len(lines)} élément(s)).{rest} "
                              "Le bijou n'est pas validé dans FiveM tant qu'il n'y a pas été testé.")
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


CLASSES = (MIO_OT_export_place, MIO_OT_export_check, MIO_OT_export, MIO_OT_open_folder)
