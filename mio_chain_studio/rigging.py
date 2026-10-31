"""Étape 7 : mesh final unique pondéré à 100 % sur SKEL_Spine3 du squelette masculin fourni.

Le mesh final est une COPIE : chaîne et pendentif sources restent modifiables. Les poids sont écrits
par l'API (VertexGroup.add), sans simuler de peinture.
"""

import bpy
import numpy as np

from . import teef
from .utils import (
    McsError,
    TAG_FINAL,
    get_project,
    link_only_to,
    part_meshes,
    parts_signature,
    project_collection,
    tag,
    world_bounds,
)

BONE = "SKEL_Spine3"
MOD_NAME = "MCS_Armature"


def require_armature(proj):
    arm = proj.ref_root
    problems = teef.verify_armature(arm)
    if problems:
        raise McsError(" ".join(m for s, m, f in problems) + " Chargez les références Teef (étape 8).")
    return arm


def ensure_armature_modifier(obj, arm):
    mods = [m for m in obj.modifiers if m.type == "ARMATURE"]
    mod = mods[0] if mods else obj.modifiers.new(MOD_NAME, "ARMATURE")
    for extra in mods[1:]:
        obj.modifiers.remove(extra)
    mod.object = arm
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    return mod


def build_final(context, proj):
    arm = require_armature(proj)
    parts = part_meshes(proj)
    if not parts:
        raise McsError("Aucun composant désigné (étape 2).")
    roles = {r for o, r in parts}
    notes = []
    if "CHAIN" not in roles:
        notes.append("aucune chaîne désignée")
    if "PENDANT" not in roles:
        notes.append("aucun pendentif désigné")
    uv_sets = {tuple(u.name for u in o.data.uv_layers) for o, r in parts}
    if len(uv_sets) > 1:
        notes.append("noms de maps UV différents entre composants : " + " / ".join(",".join(s) or "aucune" for s in uv_sets))
    coll = project_collection(context, proj, "MCS_Preparation", "preparation")
    dg = context.evaluated_depsgraph_get()
    copies = []
    try:
        for obj, role in parts:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            mesh.transform(obj.matrix_world)
            if obj.matrix_world.determinant() < 0:
                mesh.flip_normals()
            tmp = bpy.data.objects.new(f"MCS_tmp_{obj.name}", mesh)
            coll.objects.link(tmp)
            copies.append(tmp)
        if len(copies) > 1:
            joined_meshes = [o.data for o in copies[1:]]
            with context.temp_override(active_object=copies[0], object=copies[0], selected_objects=copies,
                                       selected_editable_objects=copies):
                bpy.ops.object.join()
            for m in joined_meshes:
                if m.users == 0:
                    bpy.data.meshes.remove(m)
            copies = copies[:1]
        final = copies[0]
    except Exception:
        for o in copies:
            if o.name in bpy.data.objects:
                data = o.data
                bpy.data.objects.remove(o)
                if data.users == 0:
                    bpy.data.meshes.remove(data)
        raise
    final.name = "MCS_Bijou_Final"
    final.data.name = "MCS_Bijou_Final"
    tag(final, proj, role="final", **{TAG_FINAL: 1})
    tag(final.data, proj, role="final")
    link_only_to(final, coll)
    removed = [g.name for g in final.vertex_groups if g.name != BONE]
    for g in list(final.vertex_groups):
        if g.name != BONE:
            final.vertex_groups.remove(g)
    group = final.vertex_groups.get(BONE) or final.vertex_groups.new(name=BONE)
    group.add(list(range(len(final.data.vertices))), 1.0, "REPLACE")
    for m in list(final.modifiers):
        final.modifiers.remove(m)
    ensure_armature_modifier(final, arm)
    problems = verify(proj, final, parts)
    if problems:
        bpy.data.objects.remove(final)
        raise McsError("Mesh final non conforme : " + " ".join(problems))
    # Réussite : l'ancien mesh final est retiré seulement maintenant.
    old = proj.final_obj
    if old is not None and old != final and old.get(TAG_FINAL) and old.get("mcs_project") == proj.project_id:
        data = old.data
        bpy.data.objects.remove(old)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    final.name = "MCS_Bijou_Final"
    final.data.name = "MCS_Bijou_Final"
    proj.final_obj = final
    proj.final_signature = final_signature(proj)
    if removed:
        notes.append("groupes retirés de la copie : " + ", ".join(removed[:8]))
    return final, notes


def verify(proj, final, parts=None, arm=None):
    """Contrôles réels du mesh final ; retourne la liste des problèmes."""
    problems = []
    arm = arm or proj.ref_root
    me = final.data
    names = [g.name for g in final.vertex_groups]
    if names != [BONE]:
        problems.append(f"groupes de sommets {names} au lieu de [{BONE}].")
    else:
        gi = final.vertex_groups[BONE].index
        bad = 0
        for v in me.vertices:
            w = [g for g in v.groups]
            if len(w) != 1 or w[0].group != gi or abs(w[0].weight - 1.0) > 1e-6:
                bad += 1
        if bad:
            problems.append(f"{bad} sommet(s) sans poids exactement 1 sur {BONE}.")
    mods = [m for m in final.modifiers if m.type == "ARMATURE"]
    if len(mods) != 1 or mods[0].object != arm:
        problems.append("liaison au squelette absente (modificateur Armature).")
    elif arm is None or arm.data.bones.find(BONE) < 0:
        problems.append(f"l'armature liée n'a pas d'os {BONE}.")
    if parts is not None:
        expected_polys = sum(len(o.data.polygons) for o, r in parts)
        if len(me.polygons) != expected_polys:
            problems.append(f"{len(me.polygons)} faces au lieu de {expected_polys}.")
        b_src, b_dst = world_bounds([o for o, r in parts]), world_bounds([final])
        if b_src and b_dst and (np.abs(b_src[0] - b_dst[0]).max() > 1e-5 or np.abs(b_src[1] - b_dst[1]).max() > 1e-5):
            problems.append("placement visuel modifié.")
        mats = {m.name for o, r in parts for m in o.data.materials if m}
        if not mats <= {m.name for m in me.materials if m}:
            problems.append("des matériaux ont été perdus.")
        colors = {c.name for o, r in parts for c in o.data.color_attributes}
        if not colors <= {c.name for c in me.color_attributes}:
            problems.append("des Color Attributes ont été perdus.")
    return problems


def final_signature(proj):
    """Signature des composants sources au moment de la construction du mesh final."""
    return parts_signature(proj)


def final_state(proj):
    """(statut lisible, à jour ?) du mesh final par rapport aux composants."""
    if proj.final_obj is None:
        return "absent", False
    if proj.final_signature != final_signature(proj):
        return "périmé (composants modifiés depuis)", False
    return "à jour", True


class MIO_OT_rig_spine3(bpy.types.Operator):
    bl_idname = "mio_chain.rig_spine3"
    bl_label = "Rigger sur SKEL_Spine3"
    bl_description = ("Réunit chaîne et pendentif dans une copie unique, assigne tous les sommets à SKEL_Spine3 "
                      "avec un poids de 1 et la lie au squelette masculin fourni")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            final, notes = build_final(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        msg = (f"{final.name} : {len(final.data.vertices)} sommets à 100 % sur {BONE}, lié à {proj.ref_root.name}.")
        if notes:
            self.report({"WARNING"}, msg + " Remarques : " + " ; ".join(notes))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_weight_paint(bpy.types.Operator):
    bl_idname = "mio_chain.weight_paint"
    bl_label = "Contrôler en Weight Paint"
    bl_description = "Sélectionne le mesh final et passe en Weight Paint sur SKEL_Spine3"

    def execute(self, context):
        proj = get_project(context)
        final = proj.final_obj
        if final is None or final.name not in context.view_layer.objects:
            self.report({"ERROR"}, "Aucun mesh final dans cette scène : cliquez « Rigger sur SKEL_Spine3 ».")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects.selected:
            o.select_set(False)
        final.hide_set(False)
        final.select_set(True)
        context.view_layer.objects.active = final
        group = final.vertex_groups.get(BONE)
        if group is not None:
            final.vertex_groups.active_index = group.index
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        return {"FINISHED"}


CLASSES = (MIO_OT_rig_spine3, MIO_OT_weight_paint)
