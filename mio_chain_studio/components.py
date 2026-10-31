"""Étape 2 : chaîne OBJ importée ou choisie dans la scène, composants du bijou (chaîne / pendentif).

Matériaux et UV importés sont conservés tels quels. Si un import échoue, la chaîne précédente est gardée.
"""

import os

import bpy

from .utils import (
    McsError,
    ROLE_LABELS,
    TAG_IMPORTED,
    abspath,
    get_project,
    iter_tree,
    link_only_to,
    project_collection,
    remove_owned_object,
    tag,
)


def add_part(proj, obj, role):
    for p in proj.parts:
        if p.obj == obj:
            p.role = role
            return p
    p = proj.parts.add()
    p.obj, p.role = obj, role
    return p


def cleanup_parts(proj):
    for i in reversed(range(len(proj.parts))):
        if proj.parts[i].obj is None:
            proj.parts.remove(i)


def import_chain(context, proj):
    path = abspath(proj.chain_path)
    if not path:
        raise McsError("Choisissez d'abord un fichier .obj.")
    if not os.path.isfile(path):
        raise McsError(f"Fichier introuvable : {path}. La chaîne précédente est conservée.")
    if os.path.splitext(path)[1].lower() != ".obj":
        raise McsError("Seuls les fichiers .obj sont acceptés pour la chaîne.")
    coll = project_collection(context, proj, "MCS_Chaine", "chaine")
    before = set(bpy.data.objects)
    try:
        with context.temp_override(collection=coll):
            result = bpy.ops.wm.obj_import(filepath=path, forward_axis=proj.chain_forward, up_axis=proj.chain_up,
                                           global_scale=proj.chain_scale)
    except RuntimeError as exc:
        result, error = {"CANCELLED"}, str(exc)
    else:
        error = ""
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH" and len(o.data.polygons)]
    if "FINISHED" not in result or not meshes:
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
        raise McsError(f"Import OBJ impossible{' : ' + error if error else ' (aucun maillage)'}. "
                       "La chaîne précédente est conservée.")
    # Réussite : la chaîne importée précédemment par l'addon est remplacée.
    previous = [p.obj for p in proj.parts if p.role == "CHAIN" and p.obj is not None and p.obj.get(TAG_IMPORTED)]
    for old in previous:
        for o in reversed(list(iter_tree(old))):
            remove_owned_object(o, proj, marker=TAG_IMPORTED)
    cleanup_parts(proj)
    if len(meshes) == 1:
        chain = meshes[0]
    else:
        chain = bpy.data.objects.new("MCS_Chaine", None)
        chain.empty_display_size = 0.02
        coll.objects.link(chain)
        for m in meshes:
            world = m.matrix_world.copy()
            m.parent = chain
            m.matrix_world = world
        new.append(chain)
    for o in new:
        link_only_to(o, coll)
        tag(o, proj, role="chaine", generated=False, **{TAG_IMPORTED: 1})
        if o.data is not None:
            tag(o.data, proj, role="chaine", generated=False, **{TAG_IMPORTED: 1})
    add_part(proj, chain, "CHAIN")
    return chain, len(meshes), len(previous)


class MIO_OT_chain_import(bpy.types.Operator):
    bl_idname = "mio_chain.chain_import"
    bl_label = "Importer ma chaîne"
    bl_description = "Importe le .obj (matériaux et UV conservés) ; une chaîne importée avant par l'addon est remplacée"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            chain, n, replaced = import_chain(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        msg = f"Chaîne importée : {chain.name} ({n} maillage(s))."
        if replaced:
            msg += " L'import précédent a été remplacé."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_part_add(bpy.types.Operator):
    bl_idname = "mio_chain.part_add"
    bl_label = "Ajouter la sélection"
    bl_description = "Désigne les objets sélectionnés comme composant du bijou"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.EnumProperty(items=[("CHAIN", "Chaîne", ""), ("PENDANT", "Pendentif", "")], options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        objs = [o for o in context.selected_objects if o.type in {"MESH", "EMPTY"}]
        blocked = [o.name for o in objs if o.get("mcs_reference") or o.get("mcs_export") or o.get("mcs_preview")
                   or o.get("mcs_final")]
        objs = [o for o in objs if o.name not in blocked]
        if not objs:
            self.report({"ERROR"}, "Sélectionnez un ou plusieurs maillages de votre bijou.")
            return {"CANCELLED"}
        for o in objs:
            add_part(proj, o, self.role)
        msg = f"{len(objs)} objet(s) → {ROLE_LABELS[self.role]}."
        if blocked:
            msg += " Ignorés (références, export ou aperçu) : " + ", ".join(blocked)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_part_remove(bpy.types.Operator):
    bl_idname = "mio_chain.part_remove"
    bl_label = "Retirer du bijou"
    bl_description = "Retire ce composant de la liste (l'objet reste dans la scène)"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        if 0 <= self.index < len(proj.parts):
            proj.parts.remove(self.index)
        return {"FINISHED"}


class MIO_OT_select_object(bpy.types.Operator):
    bl_idname = "mio_chain.select_object"
    bl_label = "Sélectionner"
    bl_description = "Sélectionne cet objet"

    name: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or obj.name not in context.view_layer.objects:
            self.report({"WARNING"}, f"« {self.name} » n'est pas dans cette scène.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects.selected:
            o.select_set(False)
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


CLASSES = (MIO_OT_chain_import, MIO_OT_part_add, MIO_OT_part_remove, MIO_OT_select_object)
