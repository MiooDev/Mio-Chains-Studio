"""Sections 1 et 2b : structure du projet, chaîne importée ou sélectionnée, assemblage."""

import math
import os

import bpy
from mathutils import Matrix, Vector

from .utils import (
    McsError,
    ROLE_LABELS,
    ROLE_PROP,
    TAG_PROJECT,
    abspath,
    component_objects,
    ensure_collection,
    ensure_project_id,
    get_project,
    iter_tree,
    link_only_to,
    project_scene,
    remove_generated_object,
    tag,
)

TAG_IMPORTED = "mcs_imported"


def weight_method_of(obj):
    return obj.get("mcs_weight_method") if obj is not None else None


def ensure_structure(context, proj):
    """Collections et vides du projet ; ne recrée que ce qui manque."""
    ensure_project_id(proj)
    scene = project_scene(context)
    if proj.coll_root is None:
        proj.coll_root = ensure_collection("Mio Chain Studio", None, proj, "racine_collection")
    if proj.coll_root.name not in scene.collection.children:
        scene.collection.children.link(proj.coll_root)
    if proj.coll_sources is None:
        proj.coll_sources = ensure_collection("MCS_Sources", proj.coll_root, proj, "sources")
    if proj.coll_jewel is None:
        proj.coll_jewel = ensure_collection("MCS_Bijou", proj.coll_root, proj, "bijou")
    if proj.coll_export is None:
        proj.coll_export = ensure_collection("MCS_Export", proj.coll_root, proj, "export")

    if proj.jewel_root is None:
        root = bpy.data.objects.new("MCS_Bijou_Racine", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.03
        tag(root, proj, role="racine")
        link_only_to(root, proj.coll_jewel)
        proj.jewel_root = root
    if proj.pendant_pivot is None:
        pivot = bpy.data.objects.new("MCS_Pendentif_Pivot", None)
        pivot.empty_display_type = "ARROWS"
        pivot.empty_display_size = 0.015
        # Texte dans le plan XY (face +Z) tourné de 90° sur X : face vers -Y, haut vers +Z.
        # -Y est l'avant du torse dans votre référence teef_012_u. Réglable ensuite.
        pivot.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        tag(pivot, proj, role="pivot")
        link_only_to(pivot, proj.coll_jewel)
        pivot.parent = proj.jewel_root
        proj.pendant_pivot = pivot
    return proj


def parent_keep(obj, parent):
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted() if parent else Matrix.Identity(4)
    obj.matrix_world = world


def chain_meshes(proj):
    return [o for o, r in component_objects(proj, ("chaine",))]


def world_bounds(objs):
    pts = []
    for obj in objs:
        if obj.type == "MESH" and obj.data.vertices:
            mw = obj.matrix_world
            pts.extend(mw @ Vector(c) for c in obj.bound_box)
    if not pts:
        return None
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def scale_warning(proj, objs):
    """Compare la taille de la chaîne à celle du modèle de référence, si fourni."""
    b = world_bounds(objs)
    if b is None:
        return None
    size = (b[1] - b[0]).length
    if proj.ref_model is not None:
        rb = world_bounds([proj.ref_model])
        if rb is not None:
            ref = (rb[1] - rb[0]).length
            if ref > 0 and not (0.2 <= size / ref <= 5.0):
                return (f"La chaîne mesure {size:.3f} m de diagonale contre {ref:.3f} m pour le modèle de référence "
                        f"(rapport {size / ref:.2f}). Vérifiez l'échelle et les axes d'import.")
    elif size > 5.0 or size < 0.01:
        return (f"La chaîne mesure {size:.3f} m de diagonale : l'unité du fichier est peut-être différente "
                "(cm ou mm). Ajustez l'échelle d'import.")
    return None


def remove_imported_chain(proj):
    chain = proj.chain
    if chain is None or chain.get(TAG_PROJECT) != proj.project_id or not chain.get(TAG_IMPORTED):
        return False
    for obj in reversed(list(iter_tree(chain))):
        if obj.get(TAG_IMPORTED):
            remove_generated_object(obj, proj, marker=TAG_IMPORTED)
    proj.chain = None
    return True


def import_chain(context, proj):
    path = abspath(proj.chain_path)
    if not path:
        raise McsError("Choisissez d'abord un fichier .obj.")
    if not os.path.isfile(path):
        raise McsError(f"Fichier introuvable : {path}")
    if os.path.splitext(path)[1].lower() != ".obj":
        raise McsError("Format non pris en charge : seuls les fichiers .obj sont convenus pour la chaîne.")
    ensure_structure(context, proj)
    replaced = remove_imported_chain(proj)
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.obj_import(filepath=path, forward_axis=proj.chain_forward, up_axis=proj.chain_up,
                              global_scale=proj.chain_scale)
    except RuntimeError as exc:
        raise McsError(f"Import OBJ impossible : {exc}") from exc
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        for o in new:
            bpy.data.objects.remove(o)
        raise McsError("Le fichier OBJ ne contient aucun maillage.")
    for o in new:
        link_only_to(o, proj.coll_jewel)
        tag(o, proj, role="chaine", generated=False)
        o[TAG_IMPORTED] = 1
        if o.data is not None:
            tag(o.data, proj, role="chaine", generated=False)
            o.data[TAG_IMPORTED] = 1
    if len(meshes) == 1:
        chain = meshes[0]
    elif proj.chain_join:
        with context.temp_override(active_object=meshes[0], object=meshes[0], selected_objects=meshes,
                                   selected_editable_objects=meshes):
            bpy.ops.object.join()
        chain = meshes[0]
    else:
        chain = bpy.data.objects.new("MCS_Chaine", None)
        chain.empty_display_size = 0.02
        tag(chain, proj, role="chaine", generated=False)
        chain[TAG_IMPORTED] = 1
        link_only_to(chain, proj.coll_jewel)
        for m in meshes:
            parent_keep(m, chain)
    chain.name = chain.name if chain.name.startswith("MCS_") else f"MCS_Chaine_{chain.name}"
    parent_keep(chain, proj.jewel_root)
    proj.chain = chain
    return chain, replaced, len(meshes)


def snap_pendant_to_chain(proj):
    """Place le point d'attache du pendentif sur le point le plus bas de la chaîne."""
    meshes = chain_meshes(proj)
    if not meshes:
        raise McsError("Aucune chaîne définie.")
    if proj.pendant_pivot is None or proj.pendant_text is None:
        raise McsError("Créez d'abord le pendentif.")
    low = None
    for obj in meshes:
        mw = obj.matrix_world
        for v in obj.data.vertices:
            p = mw @ v.co
            if low is None or p.z < low.z:
                low = p
    if proj.bail is not None:
        b = world_bounds([proj.bail])
        attach = Vector(((b[0].x + b[1].x) / 2, (b[0].y + b[1].y) / 2, (b[0].z + b[1].z) / 2))
    else:
        parts = [o for o, r in component_objects(proj, ("texte", "plaque"))]
        b = world_bounds(parts)
        attach = Vector(((b[0].x + b[1].x) / 2, (b[0].y + b[1].y) / 2, b[1].z))
    pivot = proj.pendant_pivot
    pivot.matrix_world = Matrix.Translation(low - attach) @ pivot.matrix_world
    return low


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_init_project(bpy.types.Operator):
    bl_idname = "mio_chain.init_project"
    bl_label = "Initialiser le projet"
    bl_description = "Crée les collections et les repères du projet (sans toucher aux autres objets)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        ensure_structure(context, proj)
        if not proj.cw_checks:
            from .export import reset_cw_checks
            reset_cw_checks(proj)
        self.report({"INFO"}, f"Projet prêt (identifiant {proj.project_id}).")
        return {"FINISHED"}


class MIO_OT_chain_import(bpy.types.Operator):
    bl_idname = "mio_chain.chain_import"
    bl_label = "Importer la chaîne"
    bl_description = "Importe le fichier .obj ; une chaîne importée précédemment par l'addon est remplacée"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            chain, replaced, count = import_chain(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        msg = f"Chaîne importée ({count} maillage(s)) : {chain.name}."
        if replaced:
            msg += " L'import précédent a été remplacé."
        warn = scale_warning(proj, chain_meshes(proj))
        if warn:
            self.report({"WARNING"}, msg + " " + warn)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_role_assign(bpy.types.Operator):
    bl_idname = "mio_chain.role_assign"
    bl_label = "Utiliser la sélection"
    bl_description = "Attribue l'objet actif à ce rôle et le rattache à l'assemblage (transformation conservée)"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.StringProperty()

    def execute(self, context):
        proj = get_project(context)
        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "Sélectionnez d'abord un objet.")
            return {"CANCELLED"}
        if self.role not in ROLE_PROP:
            return {"CANCELLED"}
        allowed = {"MESH", "EMPTY"} if self.role == "chaine" else {"MESH"}
        if obj.type not in allowed:
            self.report({"ERROR"}, f"« {ROLE_LABELS[self.role]} » doit être un maillage.")
            return {"CANCELLED"}
        ensure_structure(context, proj)
        if obj in (proj.jewel_root, proj.pendant_pivot):
            self.report({"ERROR"}, "Ce vide fait partie de la structure du projet.")
            return {"CANCELLED"}
        for other_role, prop in ROLE_PROP.items():
            if other_role != self.role and getattr(proj, prop) == obj:
                setattr(proj, prop, None)
        setattr(proj, ROLE_PROP[self.role], obj)
        if obj.get(TAG_PROJECT) is None:
            tag(obj, proj, role=self.role, generated=False)
        parent_keep(obj, proj.jewel_root if self.role == "chaine" else proj.pendant_pivot)
        self.report({"INFO"}, f"{obj.name} → {ROLE_LABELS[self.role]}.")
        return {"FINISHED"}


class MIO_OT_role_clear(bpy.types.Operator):
    bl_idname = "mio_chain.role_clear"
    bl_label = "Retirer du rôle"
    bl_description = "Retire l'objet de ce rôle sans le supprimer de la scène"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.StringProperty()

    def execute(self, context):
        proj = get_project(context)
        if self.role in ROLE_PROP:
            setattr(proj, ROLE_PROP[self.role], None)
        return {"FINISHED"}


class MIO_OT_select_object(bpy.types.Operator):
    bl_idname = "mio_chain.select_object"
    bl_label = "Sélectionner"
    bl_description = "Sélectionne cet objet dans la vue 3D"

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or obj.name not in context.view_layer.objects:
            self.report({"WARNING"}, f"Objet « {self.name} » absent de cette scène.")
            return {"CANCELLED"}
        for o in context.view_layer.objects.selected:
            o.select_set(False)
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class MIO_OT_pendant_snap(bpy.types.Operator):
    bl_idname = "mio_chain.pendant_snap"
    bl_label = "Accrocher au bas de la chaîne"
    bl_description = "Déplace le pivot du pendentif pour placer la bélière au point le plus bas de la chaîne"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            low = snap_pendant_to_chain(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Pendentif placé au point bas de la chaîne (z = {low.z:.4f} m). Ajustez si besoin.")
        return {"FINISHED"}


CLASSES = (MIO_OT_init_project, MIO_OT_chain_import, MIO_OT_role_assign, MIO_OT_role_clear,
           MIO_OT_select_object, MIO_OT_pendant_snap)
