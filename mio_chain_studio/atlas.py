"""Section 3b : atlas de textures (une image destinée à un DDS), UV adaptées, DDS et YTD Sollumz.

Le regroupement concerne uniquement les IMAGES. Les matériaux et shaders restent distincts :
à l'export, chacun pointe simplement vers l'atlas avec des UV recalculées.
Les UV d'origine ne sont jamais modifiées : l'atlas est stocké dans l'attribut « mcs_atlas_uv ».
"""

import json
import math
import os

import bpy
import numpy as np

from . import dds
from . import sollumz_bridge as szb
from .materials import image_file_ok, image_is_real, unique_materials
from .utils import (
    McsError,
    abspath,
    component_objects,
    get_project,
    hash_strings,
    project_dir_or_error,
    project_scene,
    tag,
)

ATTR = "mcs_atlas_uv"   # vecteur 3D par coin de face (pas une map UV : Sollumz renomme les maps UV)
KINDS = (("diffuse", "DiffuseSampler"), ("normal", "BumpSampler"), ("spec", "SpecSampler"))
EPS = 1e-4


def atlas_names(proj):
    return {
        "diffuse": proj.texture_name(),
        # Motifs observés dans votre référence : teef_normal_001, teef_spec_000.
        "normal": f"{proj.component}_normal_{proj.drawable_index:03d}",
        "spec": f"{proj.component}_spec_{proj.drawable_index:03d}",
    }


def enabled_kinds(proj):
    return [k for k in KINDS if k[0] == "diffuse" or (k[0] == "normal" and proj.atlas_normal)
            or (k[0] == "spec" and proj.atlas_spec)]


def source_uv(mesh):
    layer = mesh.uv_layers.get("UVMap 0") or mesh.uv_layers.active
    if layer is None:
        return None, None
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uv)
    return layer, uv.reshape(-1, 2)


def loop_material_indices(mesh):
    npoly = len(mesh.polygons)
    mats = np.empty(npoly, dtype=np.int32)
    totals = np.empty(npoly, dtype=np.int32)
    starts = np.empty(npoly, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", mats)
    mesh.polygons.foreach_get("loop_total", totals)
    mesh.polygons.foreach_get("loop_start", starts)
    out = np.empty(len(mesh.loops), dtype=np.int32)
    for m, s, t in zip(mats, starts, totals):
        out[s:s + t] = m
    return out


def collect_tiles(proj):
    """Images diffuses uniques (une tuile chacune) et correspondance matériau → tuile."""
    mats = unique_materials(proj)
    if not mats:
        raise McsError("Aucun matériau Sollumz : configurez d'abord les matériaux (section 3).")
    tiles, mat_tile = [], {}
    for mat, role in mats:
        node = mat.node_tree.nodes.get("DiffuseSampler")
        img = node.image if node else None
        if not image_is_real(img) or not image_file_ok(img):
            raise McsError(f"{mat.name} : texture diffuse absente ou introuvable ; l'atlas en a besoin.")
        if img.is_float:
            raise McsError(f"{img.name} : image en virgule flottante (HDR/EXR) non prise en charge par l'atlas.")
        if img not in tiles:
            tiles.append(img)
        mat_tile[mat.name] = tiles.index(img)
    return tiles, mat_tile


def grid_layout(n, size, pad):
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cw, ch = size // cols, size // rows
    rects = []
    for k in range(n):
        c, r = k % cols, k // cols
        x, y, w, h = c * cw + pad, r * ch + pad, cw - 2 * pad, ch - 2 * pad
        if w < 4 or h < 4:
            raise McsError(f"Atlas {size}px trop petit pour {n} tuiles avec {pad}px de marge.")
        rects.append((x, y, w, h))
    return rects


def _tile_pixels(img, w, h):
    tmp = img.copy()
    try:
        tmp.scale(w, h)
        px = np.empty(w * h * 4, dtype=np.float32)
        tmp.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(tmp)
    return px.reshape(h, w, 4)


def _compose(images, rects, size, pad):
    canvas = np.zeros((size, size, 4), dtype=np.float32)
    for img, (x, y, w, h) in zip(images, rects):
        tile = _tile_pixels(img, w, h)
        if pad:
            tile = np.pad(tile, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        canvas[y - pad:y + h + pad, x - pad:x + w + pad] = tile
    return canvas


def _save_png(proj, canvas, name, folder, non_color):
    size = canvas.shape[0]
    path = os.path.join(folder, name + ".png")
    tmp = bpy.data.images.new("MCS_tmp_atlas", size, size, alpha=True)
    try:
        tmp.pixels.foreach_set(canvas.ravel())
        tmp.filepath_raw = path
        tmp.file_format = "PNG"
        tmp.save()
    finally:
        bpy.data.images.remove(tmp)
    if not os.path.isfile(path):
        raise McsError(f"Écriture de l'atlas impossible : {path}")
    img = bpy.data.images.load(path, check_existing=True)
    img.reload()
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    tag(img, proj, role=f"atlas_{name}")
    return img


def build(proj):
    szb.require()
    tiles, mat_tile = collect_tiles(proj)
    size, pad = int(proj.atlas_size), proj.atlas_padding
    rects = grid_layout(len(tiles), size, pad)
    folder = project_dir_or_error("textures")
    names = atlas_names(proj)

    # UV : vérification des plages d'origine avant toute écriture.
    errors = []
    plans = []
    for obj, role in component_objects(proj):
        me = obj.data
        layer, uv = source_uv(me)
        if layer is None:
            errors.append(f"{obj.name} n'a pas de map UV.")
            continue
        if len(uv) and ((uv < -EPS).any() or (uv > 1 + EPS).any()):
            errors.append(f"{obj.name} : UV hors de [0, 1] (texture répétée) ; un atlas exige des UV dans [0, 1].")
            continue
        lm = loop_material_indices(me)
        for mi, mat in enumerate(me.materials):
            if (lm == mi).any() and (mat is None or mat.name not in mat_tile):
                errors.append(f"{obj.name} : l'emplacement {mi} n'a pas de matériau Sollumz avec texture.")
        plans.append((obj, uv, lm))
    if errors:
        raise McsError(" ".join(errors))

    # Images.
    results = {}
    for kind, sampler in enabled_kinds(proj):
        if kind == "diffuse":
            images = tiles
        else:
            images = []
            for img in tiles:
                mat_names = [m for m, t in mat_tile.items() if tiles[t] == img]
                other = None
                for mname in mat_names:
                    node = bpy.data.materials[mname].node_tree.nodes.get(sampler)
                    if node is not None and image_is_real(node.image) and image_file_ok(node.image):
                        other = node.image
                if other is None:
                    raise McsError(f"Atlas {kind} : {', '.join(mat_names)} sans texture {sampler}. "
                                   "Chaque tuile doit en avoir une (aucune valeur neutre n'est inventée).")
                images.append(other)
        canvas = _compose(images, rects, size, pad)
        results[kind] = _save_png(proj, canvas, names[kind], folder, non_color=(kind != "diffuse"))
    proj.atlas_image = results.get("diffuse")
    proj.atlas_normal_image = results.get("normal")
    proj.atlas_spec_image = results.get("spec")

    # UV d'atlas, stockées à part.
    uv_rects = {name: (rects[t][0] / size, rects[t][1] / size, rects[t][2] / size, rects[t][3] / size)
                for name, t in mat_tile.items()}
    for obj, uv, lm in plans:
        me = obj.data
        new = uv.copy()
        for mi, mat in enumerate(me.materials):
            if mat is None or mat.name not in uv_rects:
                continue
            x, y, w, h = uv_rects[mat.name]
            mask = lm == mi
            new[mask, 0] = x + uv[mask, 0] * w
            new[mask, 1] = y + uv[mask, 1] * h
        attr = me.attributes.get(ATTR)
        if attr is not None and (attr.domain != "CORNER" or attr.data_type != "FLOAT_VECTOR"):
            me.attributes.remove(attr)
            attr = None
        if attr is None:
            attr = me.attributes.new(ATTR, "FLOAT_VECTOR", "CORNER")
        vec = np.zeros((len(new), 3), dtype=np.float32)
        vec[:, :2] = new
        attr.data.foreach_set("vector", vec.ravel())

    proj.atlas_layout = json.dumps({"size": size, "pad": pad, "rects": uv_rects,
                                    "tiles": [abspath(t.filepath) for t in tiles]})
    issues = verify(proj)
    if any(s == "ERROR" for s, m, f in issues):
        raise McsError("Atlas créé mais vérification en échec : " + " ".join(m for s, m, f in issues if s == "ERROR"))
    proj.atlas_signature = current_signature(proj)
    return results, len(tiles), issues


def current_signature(proj):
    parts = [proj.atlas_size, proj.atlas_padding, proj.atlas_normal, proj.atlas_spec, proj.texture_name()]
    try:
        tiles, mat_tile = collect_tiles(proj)
    except McsError:
        return ""
    for img in tiles:
        path = abspath(img.filepath)
        parts += [path, tuple(img.size), os.path.getmtime(path) if os.path.isfile(path) else 0]
    parts.append(sorted(mat_tile.items()))
    for obj, role in component_objects(proj):
        me = obj.data
        layer, uv = source_uv(me)
        parts += [obj.name, len(me.loops), "|".join(m.name if m else "-" for m in me.materials),
                  float(uv.sum()) if uv is not None and len(uv) else 0]
    return hash_strings(parts)


def verify(proj):
    """Vérifie le résultat réel : fichiers, dimensions et UV de chaque coin de face."""
    issues = []
    if not proj.atlas_layout:
        return [("ERROR", "Aucun atlas préparé.", "Cliquez sur « Préparer l'atlas ».")]
    layout = json.loads(proj.atlas_layout)
    size = layout["size"]
    for kind, sampler in enabled_kinds(proj):
        img = getattr(proj, "atlas_image" if kind == "diffuse" else f"atlas_{kind}_image")
        if img is None or not image_file_ok(img):
            issues.append(("ERROR", f"Atlas {kind} introuvable.", "Préparez de nouveau l'atlas."))
        elif tuple(img.size) != (size, size):
            issues.append(("ERROR", f"Atlas {kind} : {img.size[0]}×{img.size[1]} au lieu de {size}×{size}.", ""))
    rects = layout["rects"]
    for obj, role in component_objects(proj):
        me = obj.data
        attr = me.attributes.get(ATTR)
        if attr is None or len(attr.data) != len(me.loops):
            issues.append(("ERROR", f"{obj.name} : UV d'atlas absentes ou périmées.", "Préparez de nouveau l'atlas."))
            continue
        vec = np.empty(len(me.loops) * 3, dtype=np.float32)
        attr.data.foreach_get("vector", vec)
        uv = vec.reshape(-1, 3)[:, :2]
        lm = loop_material_indices(me)
        for mi, mat in enumerate(me.materials):
            mask = lm == mi
            if not mask.any():
                continue
            if mat is None or mat.name not in rects:
                issues.append(("ERROR", f"{obj.name} : matériau {mi} absent de l'atlas.", "Préparez de nouveau l'atlas."))
                continue
            x, y, w, h = rects[mat.name]
            sub = uv[mask]
            if (sub[:, 0] < x - EPS).any() or (sub[:, 0] > x + w + EPS).any() or \
               (sub[:, 1] < y - EPS).any() or (sub[:, 1] > y + h + EPS).any():
                issues.append(("ERROR", f"{obj.name} : UV hors de la tuile de {mat.name}.", "Préparez de nouveau l'atlas."))
    if not issues:
        issues.append(("INFO", f"Atlas {size}×{size} vérifié : chaque coin de face est dans sa tuile.", ""))
    return issues


def atlas_state(proj):
    """(statut lisible, à jour ?)"""
    if not proj.atlas_signature:
        return "absent", False
    return ("à jour", True) if proj.atlas_signature == current_signature(proj) else ("périmé", False)


# ---------------------------------------------------------------------------
# DDS et YTD
# ---------------------------------------------------------------------------

def dds_targets(proj):
    """[(type, image PNG/DDS source, format attendu)] des textures à placer en DDS."""
    targets = []
    if proj.use_atlas:
        if proj.atlas_image:
            targets.append(("diffuse", proj.atlas_image, proj.dds_format))
        # Normales et spéculaire en DXT1 comme dans votre référence (teef_normal_001, teef_spec_000).
        if proj.atlas_normal and proj.atlas_normal_image:
            targets.append(("normal", proj.atlas_normal_image, "DXT1"))
        if proj.atlas_spec and proj.atlas_spec_image:
            targets.append(("spec", proj.atlas_spec_image, "DXT1"))
    else:
        for mat, role in unique_materials(proj):
            node = mat.node_tree.nodes.get("DiffuseSampler")
            if node and image_is_real(node.image):
                targets.append(("diffuse", node.image, proj.dds_format))
    return targets


def dds_path_for(image):
    return os.path.splitext(abspath(image.filepath))[0] + ".dds"


def dds_status(proj):
    """[(type, nom de texture, chemin DDS, info|None, problèmes)]"""
    rows = []
    for kind, img, fmt in dds_targets(proj):
        src = abspath(img.filepath)
        path = src if src.lower().endswith(".dds") else dds_path_for(img)
        if kind == "diffuse" and proj.use_atlas and proj.dds_path:
            path = abspath(proj.dds_path)
        info, issues = dds.verify(path, expected_size=tuple(img.size) if not src.lower().endswith(".dds") else None,
                                  expected_format=fmt)
        name = os.path.splitext(os.path.basename(path))[0].lower()
        expected_name = szb.texture_name_of_image(img)
        if info is not None and name != expected_name:
            issues.append(("ERROR", f"Le DDS s'appelle {name} mais la texture attendue est {expected_name}.",
                           "Sollumz déduit le nom de texture du nom de fichier : renommez le DDS."))
        if info is not None and os.path.isfile(src) and not src.lower().endswith(".dds") \
                and os.path.getmtime(path) < os.path.getmtime(src):
            issues.append(("WARNING", f"{os.path.basename(path)} est plus ancien que l'image source.",
                           "Reconvertissez après chaque modification de l'atlas."))
        rows.append((kind, expected_name, path, info, issues))
    return rows


def prepare_ytd(context, proj):
    """Crée/actualise le dictionnaire de textures Sollumz avec le(s) DDS diffuse(s) vérifié(s)."""
    szb.require()
    images = []
    for kind, name, path, info, issues in dds_status(proj):
        if kind != "diffuse":
            continue
        errs = [m for s, m, f in issues if s == "ERROR"]
        if info is None or errs:
            raise McsError(f"DDS de {name} non valide : " + " ".join(m for s, m, f in issues))
        img = bpy.data.images.load(path, check_existing=True)
        if img.packed_file is None:
            img.pack()
        images.append(img)
    if not images:
        raise McsError("Aucune texture diffuse DDS à placer dans le YTD.")
    txd = szb.ensure_txd(project_scene(context), proj.ytd_name(), images)
    found = sorted(t.name for t in txd.textures)
    expected = sorted(szb.texture_name_of_image(i) for i in images)
    if found != expected:
        raise McsError(f"Contenu du YTD inattendu : {found} au lieu de {expected}.")
    return txd


class MIO_OT_atlas_build(bpy.types.Operator):
    bl_idname = "mio_chain.atlas_build"
    bl_label = "Préparer l'atlas"
    bl_description = "Regroupe les textures dans une image, calcule les UV d'atlas et vérifie le résultat"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            results, n, issues = build(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        files = ", ".join(os.path.basename(i.filepath) for i in results.values())
        self.report({"INFO"}, f"Atlas vérifié ({n} tuile(s)) : {files}. Étape suivante : conversion DDS.")
        return {"FINISHED"}


class MIO_OT_dds_convert(bpy.types.Operator):
    bl_idname = "mio_chain.dds_convert"
    bl_label = "Convertir en DDS"
    bl_description = "Convertit les textures avec texconv ou ImageMagick, puis vérifie l'en-tête du DDS produit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        targets = dds_targets(proj)
        if not targets:
            self.report({"ERROR"}, "Rien à convertir : préparez l'atlas ou les textures diffuses.")
            return {"CANCELLED"}
        done = []
        for kind, img, fmt in targets:
            src = abspath(img.filepath)
            if src.lower().endswith(".dds"):
                continue
            try:
                out, info, enc = dds.convert(src, fmt, proj.dds_mipmaps)
            except McsError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            info2, issues = dds.verify(out, tuple(img.size), fmt)
            errs = [m for s, m, f in issues if s == "ERROR"]
            if errs:
                self.report({"ERROR"}, f"{os.path.basename(out)} : " + " ".join(errs))
                return {"CANCELLED"}
            if kind == "diffuse" and proj.use_atlas:
                proj.dds_path = out
            done.append(f"{os.path.basename(out)} ({info['format']}, {info['width']}×{info['height']}, "
                        f"{info['mips']} mip, {enc})")
        self.report({"INFO"}, "DDS vérifié(s) : " + "; ".join(done) if done else "Les textures sont déjà en DDS.")
        return {"FINISHED"}


class MIO_OT_dds_use_file(bpy.types.Operator):
    bl_idname = "mio_chain.dds_use_file"
    bl_label = "Vérifier ce DDS"
    bl_description = "Vérifie le DDS de l'atlas converti avec un autre outil (en-tête, taille, nom)"

    def execute(self, context):
        proj = get_project(context)
        if not proj.atlas_image:
            self.report({"ERROR"}, "Préparez d'abord l'atlas.")
            return {"CANCELLED"}
        info, issues = dds.verify(abspath(proj.dds_path), tuple(proj.atlas_image.size), proj.dds_format)
        rows = [r for r in dds_status(proj) if r[0] == "diffuse"]
        issues = rows[0][4] if rows else issues
        errs = [m for s, m, f in issues if s == "ERROR"]
        if info is None or errs:
            self.report({"ERROR"}, " ".join(m for s, m, f in issues))
            return {"CANCELLED"}
        self.report({"INFO"}, f"DDS valide : {info['format']}, {info['width']}×{info['height']}, {info['mips']} mip.")
        return {"FINISHED"}


class MIO_OT_ytd_prepare(bpy.types.Operator):
    bl_idname = "mio_chain.ytd_prepare"
    bl_label = "Préparer le YTD (Sollumz)"
    bl_description = "Place le DDS diffuse vérifié dans un dictionnaire de textures Sollumz"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            txd = prepare_ytd(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"YTD « {txd.name} » : {', '.join(t.name for t in txd.textures)}.")
        return {"FINISHED"}


CLASSES = (MIO_OT_atlas_build, MIO_OT_dds_convert, MIO_OT_dds_use_file, MIO_OT_ytd_prepare)
