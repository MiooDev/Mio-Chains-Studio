"""Étape 1 : préparation des SVG importés en courbes (couches épaissies et empilées).

Les courbes d'origine restent intactes (masquées) et servent de source : chaque préparation repart
d'elles, si bien qu'un deuxième clic ne cumule jamais les épaisseurs et ne crée pas de doublon.
Les matériaux noirs sont retirés des maillages produits, mais toute la géométrie est conservée.
"""

import json

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from .utils import (
    McsError,
    TAG_SVG_RESULT,
    TAG_SVG_SOURCE,
    get_project,
    hash_strings,
    link_only_to,
    mesh_checksum,
    project_collection,
    tag,
)

AXIS_VECTORS = {"POS_Z": (0, 0, 1), "NEG_Z": (0, 0, -1), "POS_Y": (0, 1, 0),
                "NEG_Y": (0, -1, 0), "POS_X": (1, 0, 0), "NEG_X": (-1, 0, 0)}
KEY_SRC = "mcs_svg_src"


def axis_vector(proj):
    return Vector(AXIS_VECTORS[proj.stack_axis])


def thickness(proj, layer):
    return {1: proj.thickness_1, 2: proj.thickness_2, 3: proj.thickness_3}[layer]


def _to_srgb(c):
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def material_colors(mat):
    """Couleurs (linéaires) d'un matériau : couleur d'affichage et couleurs non reliées des BSDF."""
    colors = [tuple(mat.diffuse_color[:3])]
    if mat.node_tree:
        for node in mat.node_tree.nodes:
            for name in ("Color", "Base Color"):
                sock = node.inputs.get(name) if hasattr(node, "inputs") else None
                if sock is not None and not sock.is_linked and node.bl_idname.startswith("ShaderNodeBsdf"):
                    colors.append(tuple(sock.default_value[:3]))
    return colors


def is_black(mat, threshold):
    if mat is None:
        return False
    return all(max(_to_srgb(c) for c in col) <= threshold for col in material_colors(mat))


# ---------------------------------------------------------------------------
# Sources et couches
# ---------------------------------------------------------------------------

def sources_from_selection(context, proj):
    """Courbes sources désignées par la sélection (un maillage préparé renvoie vers sa courbe)."""
    srcs, skipped = [], []
    for obj in context.selected_objects:
        src = None
        if obj.get(TAG_SVG_RESULT) and obj.get("mcs_project") == proj.project_id:
            src = bpy.data.objects.get(obj.get(KEY_SRC, ""))
        elif obj.type == "CURVE":
            src = obj
        if src is None:
            skipped.append(obj.name)
        elif src not in srcs:
            srcs.append(src)
    return srcs, skipped


def flat_mesh(src):
    """Maillage plat de la courbe en coordonnées monde, sans extrusion ni biseau propres à la courbe."""
    curve = src.data.copy()
    curve.extrude = 0.0
    curve.bevel_depth = 0.0
    curve.bevel_object = None
    curve.taper_object = None
    tmp = bpy.data.objects.new("MCS_tmp_svg", curve)
    try:
        mesh = bpy.data.meshes.new_from_object(tmp)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.curves.remove(curve)
    mesh.transform(src.matrix_world)
    if len(mesh.polygons) == 0:
        bpy.data.meshes.remove(mesh)
        raise McsError(f"{src.name} : aucune surface remplie (courbe sans remplissage). "
                       "Réglez « Fill Mode » sur Both dans les propriétés de la courbe.")
    return mesh


def heights(mesh, d):
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    h = co.reshape(-1, 3) @ np.array(d)
    return float(h.mean()), float(h.max() - h.min())


def cluster(values, tol):
    """Regroupe des hauteurs triées : [[valeurs], ...] du bas vers le haut."""
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def detect_layers(context, proj, srcs):
    """Affecte automatiquement les couches si les hauteurs initiales sont distinctes. Retourne (auto, message)."""
    d = axis_vector(proj)
    hs = {}
    for src in srcs:
        mesh = flat_mesh(src)
        hs[src] = heights(mesh, d)[0]
        bpy.data.meshes.remove(mesh)
    groups = cluster(hs.values(), proj.height_tolerance)
    if len(groups) == 1:
        return False, ("Toutes les courbes sont à la même hauteur : l'ordre ne peut pas être déduit. "
                       "Affectez-les aux couches 1, 2 et 3.")
    if len(groups) > 3:
        return False, f"{len(groups)} hauteurs distinctes : plus de trois couches. Affectez-les manuellement."
    for src, h in hs.items():
        for i, g in enumerate(groups):
            if g[0] - 1e-12 <= h <= g[-1] + 1e-12:
                src.mio_svg_layer = i + 1
    return True, f"{len(groups)} couche(s) détectée(s) d'après les hauteurs initiales (couche 1 = la plus basse)."


# ---------------------------------------------------------------------------
# Épaississement
# ---------------------------------------------------------------------------

def solidify(mesh, d, back, t):
    """Aplatit le maillage au niveau `back` le long de `d`, puis l'épaissit de `t` (solide fermé)."""
    dv = Vector(d)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    for v in bm.verts:
        v.co = v.co - dv * v.co.dot(dv) + dv * back
    uv = bm.loops.layers.uv.active
    faces = list(bm.faces)
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    top = {v: bm.verts.new(v.co + dv * t) for v in list(bm.verts) if v.link_faces}
    for f in faces:
        nf = bm.faces.new([top[v] for v in f.verts])
        nf.material_index = f.material_index
        if uv is not None:
            for lo, ln in zip(f.loops, nf.loops):
                ln[uv].uv = lo[uv].uv
    for e in boundary:
        f = e.link_faces[0]
        loop = next(lp for lp in f.loops if lp.edge == e)
        a, b = loop.vert, loop.link_loop_next.vert
        side = bm.faces.new((b, a, top[a], top[b]))
        side.material_index = f.material_index
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def strip_black(mesh, threshold):
    """Retire les matériaux noirs : leurs faces restent, sans matériau. Retourne les noms retirés."""
    mats = list(mesh.materials)
    if not mats:
        return []
    removed = [m.name for m in mats if is_black(m, threshold)]
    if not removed:
        return []
    idx = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", idx)
    keep = []
    for m in mats:
        if m is not None and not is_black(m, threshold) and m not in keep:
            keep.append(m)
    needs_empty = any(mats[i] is None or is_black(mats[i], threshold) for i in set(idx.tolist()) if i < len(mats))
    new_slots = keep + ([None] if needs_empty and keep else [])
    remap = {}
    for i, m in enumerate(mats):
        if m is not None and m in keep:
            remap[i] = keep.index(m)
        else:
            remap[i] = len(keep) if keep else 0
    new_idx = np.array([remap.get(i, 0) for i in idx], dtype=np.int32)
    mesh.materials.clear()
    for m in new_slots:
        mesh.materials.append(m)
    mesh.polygons.foreach_set("material_index", new_idx)
    return removed


def _area_facing(mesh, d, sign):
    dv = np.array(d)
    total, count = 0.0, 0
    for p in mesh.polygons:
        if float(np.dot(np.array(p.normal), dv)) * sign > 0.999:
            total += p.area
            count += 1
    return total, count


def prepare(context, proj):
    srcs, skipped = sources_from_selection(context, proj)
    if not srcs:
        raise McsError("Sélectionnez les courbes SVG (ou leurs maillages préparés).")
    missing = [s.name for s in srcs if s.mio_svg_layer not in (1, 2, 3)]
    if missing:
        raise McsError("Couche non affectée pour : " + ", ".join(missing[:8]) +
                       ". Détectez les couches ou affectez-les manuellement.")
    d = axis_vector(proj)
    flats, hs = {}, {}
    try:
        for src in srcs:
            flats[src] = flat_mesh(src)
            h, spread = heights(flats[src], d)
            if spread > max(proj.height_tolerance, 1e-6):
                raise McsError(f"{src.name} n'est pas plane perpendiculairement à la direction d'empilement "
                               f"(écart {spread:.5f} m). Vérifiez la direction choisie.")
            hs[src] = h
    except McsError:
        for m in flats.values():
            bpy.data.meshes.remove(m)
        raise
    base = min(hs.values())
    layers = sorted({s.mio_svg_layer for s in srcs})
    backs, cursor = {}, base
    for layer in layers:
        backs[layer] = cursor
        cursor += thickness(proj, layer) + proj.layer_gap

    coll = project_collection(context, proj, "MCS_Pendentif_SVG", "svg")
    created, report = [], []
    for src in srcs:
        layer = src.mio_svg_layer
        mesh = flats[src]
        flat_area = sum(p.area for p in mesh.polygons)
        flat_faces = len(mesh.polygons)
        solidify(mesh, d, backs[layer], thickness(proj, layer))
        removed = strip_black(mesh, proj.black_threshold)
        mesh.name = f"{src.name}_maillage"
        tag(mesh, proj, role="svg")
        old = [o for o in bpy.data.objects if o.get(TAG_SVG_RESULT) and o.get(KEY_SRC) == src.name
               and o.get("mcs_project") == proj.project_id]
        obj = bpy.data.objects.new(f"{src.name}_maillage", mesh)
        tag(obj, proj, role="svg", **{TAG_SVG_RESULT: 1, KEY_SRC: src.name, "mcs_svg_layer": layer,
                                      "mcs_flat_area": flat_area, "mcs_flat_faces": flat_faces})
        link_only_to(obj, coll)
        for o in old:
            _replace_part(proj, o, obj)
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data.users == 0:
                bpy.data.meshes.remove(data)
        if not any(p.obj == obj for p in proj.parts):
            part = proj.parts.add()
            part.obj, part.role = obj, "PENDANT"
        tag(src, proj, role="svg_source", generated=False, **{TAG_SVG_SOURCE: 1})
        src.hide_set(True)
        src.hide_render = True
        created.append(obj)
        if removed:
            report.append(("INFO", f"{obj.name} : matériau(x) noir(s) retiré(s) ({', '.join(sorted(set(removed)))}), "
                                   "géométrie conservée.", ""))
    for p in [p for p in proj.parts if p.obj is None]:
        proj.parts.remove(list(proj.parts).index(p))
    issues = verify(proj, created, backs) + report
    errors = [m for s, m, f in issues if s == "ERROR"]
    proj.svg_report = json.dumps(issues)
    proj.svg_signature = "" if errors else signature(proj)
    if errors:
        raise McsError("Préparation non conforme : " + " ".join(errors))
    if skipped:
        issues.append(("WARNING", "Ignorés (ni courbe ni maillage SVG préparé) : " + ", ".join(skipped[:6]), ""))
        proj.svg_report = json.dumps(issues)
    return created, issues


def _replace_part(proj, old, new):
    for p in proj.parts:
        if p.obj == old:
            p.obj = new


def results(proj):
    pid = proj.project_id
    return [o for o in bpy.data.objects if pid and o.get("mcs_project") == pid and o.get(TAG_SVG_RESULT)]


def verify(proj, objs=None, backs=None):
    """Mesures réelles : épaisseur, contact entre couches, surface conservée, matériaux noirs absents."""
    objs = objs if objs is not None else results(proj)
    d = axis_vector(proj)
    dv = np.array(d)
    issues, extent = [], {}
    for obj in objs:
        me = obj.data
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        h = co.reshape(-1, 3) @ np.array(obj.matrix_world)[:3, :3].T @ dv + float(np.array(obj.matrix_world)[:3, 3] @ dv)
        layer = obj.get("mcs_svg_layer", 0)
        t = thickness(proj, layer)
        measured = float(h.max() - h.min())
        tol = 1e-6 + 1e-5 * t
        if abs(measured - t) > tol:
            issues.append(("ERROR", f"{obj.name} : épaisseur mesurée {measured:.5f} m au lieu de {t:.5f} m.", ""))
        lo, hi = extent.get(layer, (np.inf, -np.inf))
        extent[layer] = (min(lo, float(h.min())), max(hi, float(h.max())))
        area, faces = _area_facing(me, d, -1)
        if abs(area - obj.get("mcs_flat_area", area)) > 1e-9 + 1e-5 * area or faces != obj.get("mcs_flat_faces", faces):
            issues.append(("ERROR", f"{obj.name} : surface du dessin modifiée ({faces} faces de dos, "
                                    f"{obj.get('mcs_flat_faces')} attendues).", ""))
        if any(m is not None and is_black(m, proj.black_threshold) for m in me.materials):
            issues.append(("ERROR", f"{obj.name} : un matériau noir est encore présent.", ""))
    layers = sorted(extent)
    for a, b in zip(layers, layers[1:]):
        gap = extent[b][0] - extent[a][1]
        if abs(gap - proj.layer_gap) > 1e-6:
            issues.append(("ERROR", f"Couches {a} et {b} : écart réel {gap:.6f} m au lieu de {proj.layer_gap:.6f} m.", ""))
    for layer in layers:
        lo, hi = extent[layer]
        n = sum(1 for o in objs if o.get("mcs_svg_layer") == layer)
        issues.append(("INFO", f"Couche {layer} : {n} objet(s), dos {lo:.4f} m, avant {hi:.4f} m, "
                               f"épaisseur {hi - lo:.4f} m.", ""))
    return issues


def signature(proj):
    parts = [proj.thickness_1, proj.thickness_2, proj.thickness_3, proj.layer_gap, proj.stack_axis, proj.black_threshold]
    for obj in sorted(results(proj), key=lambda o: o.name):
        src = bpy.data.objects.get(obj.get(KEY_SRC, ""))
        parts += [obj.name, mesh_checksum(obj.data), src.name if src else "-", src.mio_svg_layer if src else 0]
    return hash_strings(parts)


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_svg_detect(bpy.types.Operator):
    bl_idname = "mio_chain.svg_detect"
    bl_label = "Détecter les couches"
    bl_description = "Déduit l'ordre des couches des hauteurs initiales des courbes sélectionnées"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        srcs, skipped = sources_from_selection(context, proj)
        if not srcs:
            self.report({"ERROR"}, "Sélectionnez des courbes SVG.")
            return {"CANCELLED"}
        try:
            auto, msg = detect_layers(context, proj, srcs)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"} if auto else {"WARNING"}, msg)
        return {"FINISHED"}


class MIO_OT_svg_assign(bpy.types.Operator):
    bl_idname = "mio_chain.svg_assign"
    bl_label = "Affecter à la couche"
    bl_description = "Affecte les courbes sélectionnées à cette couche"
    bl_options = {"REGISTER", "UNDO"}

    layer: bpy.props.IntProperty(min=0, max=3, options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        srcs, skipped = sources_from_selection(context, proj)
        if not srcs:
            self.report({"ERROR"}, "Sélectionnez des courbes SVG.")
            return {"CANCELLED"}
        for s in srcs:
            s.mio_svg_layer = self.layer
        self.report({"INFO"}, f"{len(srcs)} courbe(s) → couche {self.layer}.")
        return {"FINISHED"}


class MIO_OT_svg_prepare(bpy.types.Operator):
    bl_idname = "mio_chain.svg_prepare"
    bl_label = "Préparer les SVG sélectionnés"
    bl_description = ("Convertit les courbes sélectionnées en maillages épaissis et empilés, retire les matériaux "
                      "noirs en gardant toute la géométrie ; les courbes d'origine sont conservées masquées")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            created, issues = prepare(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        for o in created:
            o.select_set(True)
        context.view_layer.objects.active = created[0]
        self.report({"INFO"}, f"{len(created)} maillage(s) préparé(s) et vérifié(s).")
        return {"FINISHED"}


class MIO_OT_svg_show_sources(bpy.types.Operator):
    bl_idname = "mio_chain.svg_show_sources"
    bl_label = "Afficher / masquer les courbes sources"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        srcs = [o for o in bpy.data.objects if o.get(TAG_SVG_SOURCE) and o.get("mcs_project") == proj.project_id
                and o.name in context.view_layer.objects]
        if not srcs:
            self.report({"WARNING"}, "Aucune courbe source.")
            return {"CANCELLED"}
        hide = not srcs[0].hide_get()
        for o in srcs:
            o.hide_set(hide)
        return {"FINISHED"}


CLASSES = (MIO_OT_svg_detect, MIO_OT_svg_assign, MIO_OT_svg_prepare, MIO_OT_svg_show_sources)
