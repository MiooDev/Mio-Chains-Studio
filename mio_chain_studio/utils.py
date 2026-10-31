"""Outils communs : étiquettes de projet, suppression sûre, composants, signatures, affichage."""

import hashlib
import os
import textwrap
import uuid

import bpy
import numpy as np

TAG_PROJECT = "mcs_project"      # identifiant du projet propriétaire
TAG_ROLE = "mcs_role"
TAG_GENERATED = "mcs_generated"  # 1 = créé par l'addon : il peut le remplacer ou le supprimer
TAG_SVG_SOURCE = "mcs_svg_source"
TAG_SVG_RESULT = "mcs_svg_result"
TAG_IMPORTED = "mcs_imported"
TAG_REFERENCE = "mcs_reference"
TAG_EXPORT = "mcs_export"
TAG_FINAL = "mcs_final"
TAG_PREVIEW = "mcs_preview"
TAG_DISPLAY = "mcs_display"

STATUS_TODO = "À faire"
STATUS_CHECK = "À vérifier"
STATUS_DONE = "Terminé"
STATUS_ICONS = {STATUS_TODO: "RADIOBUT_OFF", STATUS_CHECK: "ERROR", STATUS_DONE: "CHECKMARK"}
SEVERITY_ICONS = {"ERROR": "CANCEL", "WARNING": "ERROR", "INFO": "INFO"}
ROLE_LABELS = {"CHAIN": "Chaîne", "PENDANT": "Pendentif"}


class McsError(Exception):
    """Erreur destinée à l'utilisateur (message en français)."""


# ---------------------------------------------------------------------------
# Projet
# ---------------------------------------------------------------------------

def project_scene(context):
    """Scène du projet (une scène d'aperçu renvoie vers sa scène source)."""
    scene = context.scene
    src = getattr(scene, "mio_chain_source", None)
    return src if src is not None else scene


def get_project(context):
    return project_scene(context).mio_chain


def ensure_project_id(proj):
    if not proj.project_id:
        proj.project_id = uuid.uuid4().hex[:12]
    return proj.project_id


def tag(id_block, proj, role=None, generated=True, **extra):
    id_block[TAG_PROJECT] = ensure_project_id(proj)
    if role:
        id_block[TAG_ROLE] = role
    if generated:
        id_block[TAG_GENERATED] = 1
    for key, value in extra.items():
        id_block[key] = value


def owned(id_block, proj, marker=TAG_GENERATED):
    return (id_block is not None and bool(proj.project_id) and id_block.get(TAG_PROJECT) == proj.project_id
            and bool(id_block.get(marker)))


def remove_owned_object(obj, proj, marker=TAG_GENERATED):
    """Supprime un objet seulement s'il appartient au projet et porte `marker`. Retourne True si supprimé."""
    if not owned(obj, proj, marker):
        return False
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if isinstance(data, bpy.types.Mesh) and data.users == 0 and data.get(TAG_PROJECT) == proj.project_id:
        bpy.data.meshes.remove(data)
    return True


def project_collection(context, proj, name, role):
    """Collection du projet (créée sous « Mio Chain Studio » dans la scène du projet si absente)."""
    ensure_project_id(proj)
    scene = project_scene(context)
    root = None
    for coll in bpy.data.collections:
        if coll.get(TAG_PROJECT) == proj.project_id and coll.get(TAG_ROLE) == "racine":
            root = coll
    if root is None:
        root = bpy.data.collections.new("Mio Chain Studio")
        tag(root, proj, role="racine")
    if root.name not in scene.collection.children:
        scene.collection.children.link(root)
    for coll in root.children:
        if coll.get(TAG_PROJECT) == proj.project_id and coll.get(TAG_ROLE) == role:
            return coll
    coll = bpy.data.collections.new(name)
    tag(coll, proj, role=role)
    root.children.link(coll)
    return coll


def link_only_to(obj, coll):
    for c in list(obj.users_collection):
        if c != coll:
            c.objects.unlink(obj)
    if obj.name not in coll.objects:
        coll.objects.link(obj)


def iter_tree(obj):
    yield obj
    for child in obj.children:
        yield from iter_tree(child)


# ---------------------------------------------------------------------------
# Composants du bijou
# ---------------------------------------------------------------------------

def part_meshes(proj, role=None):
    """[(objet maillage, rôle)] des composants désignés ; un vide compte pour ses maillages enfants."""
    out, seen = [], set()
    for part in proj.parts:
        obj = part.obj
        if obj is None or (role and part.role != role):
            continue
        for o in (iter_tree(obj) if obj.type == "EMPTY" else [obj]):
            if o.type == "MESH" and o.name not in seen:
                seen.add(o.name)
                out.append((o, part.role))
    return out


# ---------------------------------------------------------------------------
# Statistiques et signatures
# ---------------------------------------------------------------------------

def triangle_count(mesh):
    n = len(mesh.polygons)
    if n == 0:
        return 0
    loops = np.empty(n, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", loops)
    return int((loops - 2).sum())


def mesh_checksum(mesh):
    n = len(mesh.vertices)
    if n == 0:
        return "0"
    co = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    return f"{n}:{len(mesh.polygons)}:{float(np.round(co, 5).sum()):.5f}:{float(np.abs(co).sum()):.5f}"


def matrix_key(m):
    return ",".join(f"{v:.5f}" for row in m for v in row)


def hash_strings(parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def object_signature(obj):
    parts = [obj.name, obj.type, matrix_key(obj.matrix_world)]
    if obj.type == "MESH":
        me = obj.data
        parts += [mesh_checksum(me), "|".join(m.name if m else "-" for m in me.materials),
                  "|".join(u.name for u in me.uv_layers),
                  "|".join(f"{c.name}:{c.domain}:{c.data_type}" for c in me.color_attributes)]
        mi = np.empty(len(me.polygons), dtype=np.int32)
        me.polygons.foreach_get("material_index", mi)
        parts.append(int(mi.sum()))
    return parts


def parts_signature(proj):
    parts = []
    for obj, role in part_meshes(proj):
        parts.append(role)
        parts.extend(object_signature(obj))
    return hash_strings(parts)


def world_bounds(objs):
    pts = []
    for obj in objs:
        if obj.type == "MESH" and len(obj.data.vertices):
            n = len(obj.data.vertices)
            co = np.empty(n * 3, dtype=np.float64)
            obj.data.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            m = np.array(obj.matrix_world)
            pts.append(co @ m[:3, :3].T + m[:3, 3])
    if not pts:
        return None
    allp = np.vstack(pts)
    return allp.min(axis=0), allp.max(axis=0)


# ---------------------------------------------------------------------------
# Chemins et images
# ---------------------------------------------------------------------------

def abspath(path):
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def same_path(a, b):
    return bool(a) and bool(b) and os.path.normcase(abspath(a)) == os.path.normcase(abspath(b))


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def draw_wrapped(layout, context, text, icon="NONE"):
    width = context.region.width if getattr(context, "region", None) else 300
    chars = max(20, int(width / 6.5))
    col = layout.column(align=True)
    col.scale_y = 0.8
    lines = [line for block in text.split("\n") for line in (textwrap.wrap(block, chars) or [""])]
    for i, line in enumerate(lines):
        if icon == "NONE":
            col.label(text=line)
        else:
            col.label(text=line, icon=icon if i == 0 else "BLANK1")
    return col


def draw_issues(layout, context, issues, limit=10):
    """Affiche [(sévérité, message, correction)]."""
    if not issues:
        return
    box = layout.box()
    for sev, msg, fix in issues[:limit]:
        draw_wrapped(box, context, msg, icon=SEVERITY_ICONS.get(sev, "INFO"))
        if fix:
            draw_wrapped(box, context, "→ " + fix)
    if len(issues) > limit:
        box.label(text=f"… et {len(issues) - limit} autre(s) point(s).")
