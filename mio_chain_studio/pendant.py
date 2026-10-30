"""Section 2a : pendentif généré à partir d'un texte (texte, plaque, bélière)."""

import math
import os

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from . import assembly
from .utils import (
    McsError,
    TAG_ROLE,
    abspath,
    get_project,
    hash_strings,
    link_only_to,
    tag,
)

SETTINGS = (
    "text", "font_path", "text_size", "letter_spacing", "word_spacing", "thickness", "bevel_depth",
    "bevel_resolution", "curve_resolution", "use_plate", "plate_margin", "plate_thickness",
    "plate_corner_radius", "plate_corner_segments", "plate_text_inset", "use_bail", "bail_radius",
    "bail_wire", "bail_segments", "bail_wire_segments",
)


def settings_hash(proj):
    parts = [getattr(proj, k) for k in SETTINGS]
    parts += [tuple(round(v, 6) for v in proj.bail_offset), tuple(round(v, 6) for v in proj.bail_rotation)]
    parts.append(proj.font.name if proj.font else "")
    return hash_strings(parts)


def is_up_to_date(proj):
    return proj.pendant_text is not None and proj.pendant_settings_hash == settings_hash(proj)


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------

def _resolve_font(proj):
    if proj.font_path:
        path = abspath(proj.font_path)
        if not os.path.isfile(path):
            raise McsError(f"Fichier de police introuvable : {path}")
        try:
            return bpy.data.fonts.load(path, check_existing=True)
        except RuntimeError as exc:
            raise McsError(f"Police illisible ({os.path.basename(path)}) : {exc}") from exc
    return proj.font


def _ensure_text_source(proj, pivot):
    src = proj.text_source
    if src is None or src.type != "FONT":
        curve = bpy.data.curves.new("MCS_Texte_Source", "FONT")
        tag(curve, proj, role="source_texte")
        src = bpy.data.objects.new("MCS_Texte_Source", curve)
        tag(src, proj, role="source_texte")
        link_only_to(src, proj.coll_sources)
        proj.text_source = src
    src.parent = pivot
    src.matrix_parent_inverse = Matrix.Identity(4)
    src.matrix_basis = Matrix.Identity(4)
    src.hide_viewport = True
    src.hide_render = True
    cu = src.data
    cu.body = proj.text
    font = _resolve_font(proj)
    if font is not None:
        cu.font = font
    cu.size = proj.text_size
    cu.space_character = proj.letter_spacing
    cu.space_word = proj.word_spacing
    cu.extrude = proj.thickness / 2.0
    cu.bevel_depth = proj.bevel_depth
    cu.bevel_resolution = proj.bevel_resolution
    cu.resolution_u = proj.curve_resolution
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.offset = 0.0
    return src


def _planar_uv(mesh, name="UVMap 0"):
    """UV planaires (plan XY du pendentif) ramenées dans [0, 1]."""
    for uv in list(mesh.uv_layers):
        mesh.uv_layers.remove(uv)
    layer = mesh.uv_layers.new(name=name)
    if not mesh.vertices:
        return
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = (maxx - minx) or 1.0
    sy = (maxy - miny) or 1.0
    for loop in mesh.loops:
        co = mesh.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = ((co.x - minx) / sx, (co.y - miny) / sy)


def text_mesh(proj, src):
    mesh = bpy.data.meshes.new_from_object(src)
    if len(mesh.polygons) == 0:
        bpy.data.meshes.remove(mesh)
        raise McsError("Le texte ne produit aucune géométrie (texte vide ou police sans ces caractères).")
    mesh.name = "MCS_Pendentif_Texte"
    _planar_uv(mesh)
    return mesh


def _rounded_rect(minx, maxx, miny, maxy, radius, segments):
    w, h = maxx - minx, maxy - miny
    r = max(0.0, min(radius, w / 2.0 - 1e-6, h / 2.0 - 1e-6))
    if r <= 1e-7:
        return [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    pts = []
    corners = ((maxx - r, miny + r, -90.0), (maxx - r, maxy - r, 0.0), (minx + r, maxy - r, 90.0), (minx + r, miny + r, 180.0))
    for cx, cy, start in corners:
        for i in range(segments + 1):
            a = math.radians(start + 90.0 * i / segments)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def plate_mesh(proj, text_bounds):
    minx, maxx, miny, maxy, minz, _maxz = text_bounds
    m = proj.plate_margin
    outline = _rounded_rect(minx - m, maxx + m, miny - m, maxy + m,
                            proj.plate_corner_radius, proj.plate_corner_segments)
    front_z = minz + proj.plate_text_inset
    back_z = front_z - proj.plate_thickness
    bm = bmesh.new()
    front = [bm.verts.new((x, y, front_z)) for x, y in outline]
    back = [bm.verts.new((x, y, back_z)) for x, y in outline]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((back[i], back[j], front[j], front[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("MCS_Plaque")
    bm.to_mesh(mesh)
    bm.free()
    _planar_uv(mesh)
    return mesh


def bail_mesh(proj, anchor):
    R, r = proj.bail_radius, proj.bail_wire
    seg, wseg = proj.bail_segments, proj.bail_wire_segments
    rot = Euler(proj.bail_rotation).to_matrix().to_4x4()
    mat = Matrix.Translation(anchor + Vector(proj.bail_offset)) @ rot
    bm = bmesh.new()
    grid = []
    for i in range(seg):
        a = 2.0 * math.pi * i / seg
        ring = []
        for j in range(wseg):
            b = 2.0 * math.pi * j / wseg
            p = Vector(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
            ring.append(bm.verts.new(mat @ p))
        grid.append(ring)
    uv_layer = bm.loops.layers.uv.new("UVMap 0")
    for i in range(seg):
        for j in range(wseg):
            i2, j2 = (i + 1) % seg, (j + 1) % wseg
            face = bm.faces.new((grid[i][j], grid[i2][j], grid[i2][j2], grid[i][j2]))
            uvs = ((i / seg, j / wseg), ((i + 1) / seg, j / wseg), ((i + 1) / seg, (j + 1) / wseg), (i / seg, (j + 1) / wseg))
            for loop, uv in zip(face.loops, uvs):
                loop[uv_layer].uv = uv
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("MCS_Beliere")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _bounds(mesh):
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


# ---------------------------------------------------------------------------
# Objets
# ---------------------------------------------------------------------------

def _set_component(proj, role, prop, name, mesh, pivot):
    """Crée l'objet du composant ou remplace son maillage (matériaux conservés)."""
    obj = getattr(proj, prop)
    if mesh is None:
        if obj is not None and obj.get(TAG_ROLE) == role:
            # Composant désactivé : l'objet généré est retiré (jamais un objet manuel).
            from .utils import remove_generated_object
            if remove_generated_object(obj, proj):
                setattr(proj, prop, None)
        return None
    tag(mesh, proj, role=role)
    if obj is None:
        obj = bpy.data.objects.new(name, mesh)
        tag(obj, proj, role=role)
        link_only_to(obj, proj.coll_jewel)
        obj.parent = pivot
        obj.matrix_parent_inverse = Matrix.Identity(4)
        setattr(proj, prop, obj)
    else:
        old = obj.data
        for mat in old.materials:
            mesh.materials.append(mat)
        obj.data = mesh
        if old.users == 0:
            bpy.data.meshes.remove(old)
    return obj


def generate(context, proj):
    if not proj.text.strip():
        raise McsError("Le texte du pendentif est vide.")
    assembly.ensure_structure(context, proj)
    pivot = proj.pendant_pivot
    src = _ensure_text_source(proj, pivot)

    tmesh = text_mesh(proj, src)
    bounds = _bounds(tmesh)
    minx, maxx, miny, maxy, minz, maxz = bounds

    pmesh = plate_mesh(proj, bounds) if proj.use_plate else None
    top = (maxy + proj.plate_margin) if proj.use_plate else maxy
    back = (minz + proj.plate_text_inset - proj.plate_thickness) if proj.use_plate else minz
    anchor = Vector(((minx + maxx) / 2.0, top + proj.bail_radius - proj.bail_wire, (back + maxz) / 2.0))
    bmesh_ = bail_mesh(proj, anchor) if proj.use_bail else None

    previous = {role: assembly.weight_method_of(getattr(proj, prop))
                for role, prop in (("texte", "pendant_text"), ("plaque", "plate"), ("beliere", "bail"))}

    _set_component(proj, "texte", "pendant_text", "MCS_Pendentif_Texte", tmesh, pivot)
    _set_component(proj, "plaque", "plate", "MCS_Plaque", pmesh, pivot)
    _set_component(proj, "beliere", "bail", "MCS_Beliere", bmesh_, pivot)
    proj.pendant_settings_hash = settings_hash(proj)

    # Les noms de groupes de sommets vivent dans le maillage : on réapplique la méthode enregistrée.
    reapplied = []
    if any(previous.values()):
        from . import rigging
        try:
            reapplied = rigging.reapply_pendant_weights(context, proj, previous)
        except McsError as exc:
            reapplied = [f"poids non réappliqués : {exc}"]
    return reapplied


class MIO_OT_pendant_create(bpy.types.Operator):
    bl_idname = "mio_chain.pendant_create"
    bl_label = "Créer le pendentif"
    bl_description = "Génère le texte 3D, la plaque et la bélière à partir des réglages"
    bl_options = {"REGISTER", "UNDO"}

    update_only: bpy.props.BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        proj = get_project(context)
        if self.update_only and proj.pendant_text is None:
            self.report({"ERROR"}, "Aucun pendentif à mettre à jour : utilisez « Créer le pendentif ».")
            return {"CANCELLED"}
        existed = proj.pendant_text is not None
        try:
            notes = generate(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if proj.pendant_text is None or len(proj.pendant_text.data.polygons) == 0:
            self.report({"ERROR"}, "Le pendentif n'a pas été généré correctement.")
            return {"CANCELLED"}
        from .utils import triangle_count, component_objects
        tris = sum(triangle_count(o) for o, r in component_objects(proj, ("texte", "plaque", "beliere")))
        verb = "mis à jour" if existed else "créé"
        msg = f"Pendentif {verb} : {tris} triangles."
        if notes:
            msg += " " + " ; ".join(notes)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


CLASSES = (MIO_OT_pendant_create,)
