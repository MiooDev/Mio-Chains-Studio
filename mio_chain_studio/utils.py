"""Outils communs : étiquettes de projet, collections, suppression sûre, statistiques, signatures."""

import hashlib
import os
import textwrap
import uuid

import bpy
import numpy as np
from mathutils import Matrix

# Propriétés personnalisées posées sur les données générées par l'addon.
TAG_PROJECT = "mcs_project"      # identifiant du projet propriétaire
TAG_ROLE = "mcs_role"            # chaine / texte / plaque / beliere / pivot / racine / source_texte
TAG_GENERATED = "mcs_generated"  # 1 = créé par l'addon (peut être remplacé ou supprimé par lui)
TAG_EXPORT = "mcs_export"        # objet de la copie d'export
TAG_PREVIEW = "mcs_preview"      # copie de présentation (scène d'aperçu)
TAG_DISPLAY = "mcs_display"      # élément chargé depuis le .blend du display

ROLES_PENDANT = ("texte", "plaque", "beliere")
ROLES_ALL = ("chaine",) + ROLES_PENDANT
ROLE_LABELS = {
    "chaine": "Chaîne",
    "texte": "Texte du pendentif",
    "plaque": "Plaque",
    "beliere": "Bélière",
}
ROLE_PROP = {
    "chaine": "chain",
    "texte": "pendant_text",
    "plaque": "plate",
    "beliere": "bail",
}

STATUS_TODO = "À faire"
STATUS_CHECK = "À vérifier"
STATUS_DONE = "Terminé"
STATUS_ICONS = {STATUS_TODO: "RADIOBUT_OFF", STATUS_CHECK: "ERROR", STATUS_DONE: "CHECKMARK"}
SEVERITY_ICONS = {"ERROR": "CANCEL", "WARNING": "ERROR", "INFO": "INFO"}


class McsError(Exception):
    """Erreur destinée à l'utilisateur (message déjà en français)."""


# ---------------------------------------------------------------------------
# Projet
# ---------------------------------------------------------------------------

def project_scene(context):
    """Scène qui porte le projet (la scène d'aperçu renvoie vers sa scène source)."""
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


def is_owned(id_block, proj, require_generated=True):
    if id_block is None or not proj.project_id:
        return False
    if id_block.get(TAG_PROJECT) != proj.project_id:
        return False
    return bool(id_block.get(TAG_GENERATED)) if require_generated else True


def ensure_collection(name, parent, proj, role):
    """Retourne la collection du projet ayant ce rôle, ou la crée sous `parent`."""
    for coll in bpy.data.collections:
        if is_owned(coll, proj) and coll.get(TAG_ROLE) == role:
            if parent is not None and coll.name not in parent.children:
                parent.children.link(coll)
            return coll
    coll = bpy.data.collections.new(name)
    tag(coll, proj, role=role)
    if parent is not None:
        parent.children.link(coll)
    return coll


def link_only_to(obj, coll):
    """Range un objet créé par l'addon dans une seule collection."""
    for c in list(obj.users_collection):
        if c != coll:
            c.objects.unlink(obj)
    if obj.name not in coll.objects:
        coll.objects.link(obj)


def remove_generated_object(obj, proj, marker=TAG_GENERATED):
    """Supprime un objet uniquement s'il a été créé par ce projet. Retourne True si supprimé."""
    if obj is None or obj.get(TAG_PROJECT) != proj.project_id or not obj.get(marker):
        return False
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0 and data.get(TAG_PROJECT) == proj.project_id:
        remove_id(data)
    return True


_ID_CONTAINERS = (
    (bpy.types.Mesh, "meshes"),
    (bpy.types.Curve, "curves"),
    (bpy.types.Armature, "armatures"),
    (bpy.types.Material, "materials"),
    (bpy.types.Image, "images"),
)


def remove_id(id_block):
    for id_type, coll_name in _ID_CONTAINERS:
        if isinstance(id_block, id_type):
            getattr(bpy.data, coll_name).remove(id_block)
            return


def iter_tree(obj):
    yield obj
    for child in obj.children:
        yield from iter_tree(child)


def role_object(proj, role):
    return getattr(proj, ROLE_PROP[role])


def component_objects(proj, roles=ROLES_ALL):
    """Objets maillage des composants, la chaîne pouvant être un vide parent de plusieurs maillages."""
    result = []
    for role in roles:
        obj = role_object(proj, role)
        if obj is None:
            continue
        if role == "chaine" and obj.type == "EMPTY":
            result.extend((o, role) for o in iter_tree(obj) if o.type == "MESH")
        elif obj.type == "MESH":
            result.append((obj, role))
    return result


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------

def triangle_count_mesh(mesh):
    n = len(mesh.polygons)
    if n == 0:
        return 0
    loops = np.empty(n, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", loops)
    return int((loops - 2).sum())


def triangle_count(obj, depsgraph=None):
    if obj is None or obj.type not in {"MESH", "FONT", "CURVE"}:
        return 0
    if depsgraph is not None:
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        try:
            return triangle_count_mesh(mesh)
        finally:
            obj_eval.to_mesh_clear()
    if obj.type == "MESH":
        return triangle_count_mesh(obj.data)
    return 0


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


def object_signature_parts(obj):
    parts = [obj.name, obj.type, matrix_key(obj.matrix_world)]
    if obj.type == "MESH":
        me = obj.data
        parts.append(mesh_checksum(me))
        parts.append("|".join(g.name for g in obj.vertex_groups))
        parts.append("|".join(m.name if m else "-" for m in me.materials))
        parts.append("|".join(u.name for u in me.uv_layers))
        parts.append("|".join(f"{c.name}:{c.domain}:{c.data_type}" for c in me.color_attributes))
        parts.append("|".join(f"{m.type}:{m.name}:{getattr(m, 'object', None) and m.object.name}" for m in obj.modifiers))
    return parts


def material_signature_parts(mat):
    parts = [mat.name, getattr(getattr(mat, "shader_properties", None), "filename", "")]
    if mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.bl_idname == "ShaderNodeTexImage":
                parts.append(f"{n.name}={n.image.filepath if n.image else ''}")
            elif n.bl_idname == "SOLLUMZ_NT_SHADER_Parameter":
                parts.append(f"{n.name}=" + ",".join(f"{o.default_value:.4f}" for o in n.outputs))
    return parts


def sources_signature(proj):
    parts = []
    for obj, role in component_objects(proj):
        parts.append(role)
        parts.extend(object_signature_parts(obj))
        for mat in obj.data.materials:
            if mat:
                parts.extend(material_signature_parts(mat))
    arm = proj.ref_armature
    parts.append(arm.name if arm else "-")
    if arm is not None and arm.type == "ARMATURE":
        parts.append(len(arm.data.bones))
        parts.append(matrix_key(arm.matrix_world))
    parts += [proj.ydd_name(), proj.drawable_name(), proj.texture_name(), proj.use_atlas,
              proj.atlas_signature if proj.use_atlas else "", proj.use_vertex_colors,
              tuple(proj.vcol0), tuple(proj.vcol1)]
    return hash_strings(parts)


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

def abspath(path):
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def project_dir_or_error(sub):
    """Dossier `//sub` à côté du .blend ; exige un fichier enregistré."""
    if not bpy.data.filepath:
        raise McsError("Enregistrez d'abord le fichier .blend : les fichiers générés sont rangés à côté de lui.")
    path = os.path.join(os.path.dirname(bpy.data.filepath), sub)
    os.makedirs(path, exist_ok=True)
    return path


def is_power_of_two(n):
    return n > 0 and (n & (n - 1)) == 0


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def draw_wrapped(layout, context, text, icon="NONE"):
    width = context.region.width if context.region else 300
    chars = max(20, int(width / 6.5))
    lines = textwrap.wrap(text, chars) or [""]
    col = layout.column(align=True)
    col.scale_y = 0.8
    for i, line in enumerate(lines):
        col.label(text=line, icon=icon if i == 0 else "BLANK1" if icon != "NONE" else "NONE")
    return col


def draw_issues(layout, context, issues, limit=12):
    """Affiche une liste de (sévérité, message, correction)."""
    if not issues:
        return
    box = layout.box()
    for sev, msg, fix in issues[:limit]:
        draw_wrapped(box, context, msg, icon=SEVERITY_ICONS.get(sev, "INFO"))
        if fix:
            draw_wrapped(box, context, "→ " + fix)
    if len(issues) > limit:
        box.label(text=f"… et {len(issues) - limit} autre(s) point(s).")


def identity():
    return Matrix.Identity(4)
