"""Section 5 : armature de référence, poids (méthodes explicites et réversibles), vérifications, test de déformation."""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.kdtree import KDTree

from .utils import (
    McsError,
    ROLES_PENDANT,
    component_objects,
    get_project,
    hash_strings,
    mesh_checksum,
)

MOD_NAME = "MCS_Armature"
KEY_BACKUP = "mcs_weights_backup"
KEY_METHOD = "mcs_weight_method"
KEY_BONE = "mcs_weight_bone"
KEY_POSE = "mcs_pose_backup"


def require_armature(proj):
    arm = proj.ref_armature
    if arm is None or arm.type != "ARMATURE":
        raise McsError("Choisissez l'armature de référence (squelette du ped).")
    if len(arm.data.bones) == 0:
        raise McsError(f"L'armature {arm.name} n'a aucun os.")
    return arm


def group_targets(proj, group):
    roles = ("chaine",) if group == "CHAIN" else ROLES_PENDANT
    return [o for o, r in component_objects(proj, roles)]


# ---------------------------------------------------------------------------
# Lecture / écriture des poids
# ---------------------------------------------------------------------------

def read_weights(obj):
    """{index de sommet: {nom de groupe: poids}}"""
    names = {g.index: g.name for g in obj.vertex_groups}
    out = {}
    for v in obj.data.vertices:
        d = {names[g.group]: g.weight for g in v.groups if g.group in names and g.weight > 0.0}
        if d:
            out[v.index] = d
    return out


def write_weights(obj, weights):
    """Remplace tous les groupes de sommets de `obj` par `weights`."""
    obj.vertex_groups.clear()
    groups = {}
    for vi, d in weights.items():
        for name, w in d.items():
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([vi], w, "REPLACE")


def backup(obj):
    weights = read_weights(obj)
    data = {}
    for vi, d in weights.items():
        for name, w in d.items():
            data.setdefault(name, ([], []))
            data[name][0].append(vi)
            data[name][1].append(w)
    obj[KEY_BACKUP] = {
        "n": len(obj.data.vertices),
        "method": obj.get(KEY_METHOD, ""),
        "names": [g.name for g in obj.vertex_groups],
        "groups": {name: {"i": i, "w": w} for name, (i, w) in data.items()},
    }


def restore(obj):
    data = obj.get(KEY_BACKUP)
    if data is None:
        raise McsError(f"{obj.name} : aucune sauvegarde de poids.")
    if data["n"] != len(obj.data.vertices):
        raise McsError(f"{obj.name} : la géométrie a changé depuis la sauvegarde ; restauration impossible.")
    obj.vertex_groups.clear()
    for name in data["names"]:
        obj.vertex_groups.new(name=name)
    for name, g in data["groups"].items():
        vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
        for vi, w in zip(g["i"], g["w"]):
            vg.add([int(vi)], float(w), "REPLACE")
    if data.get("method"):
        obj[KEY_METHOD] = data["method"]
    elif KEY_METHOD in obj:
        del obj[KEY_METHOD]
    del obj[KEY_BACKUP]


def limit_and_normalize(weights, k):
    out = {}
    for vi, d in weights.items():
        top = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:k]
        total = sum(w for n, w in top)
        if total > 0:
            out[vi] = {n: w / total for n, w in top}
    return out


# ---------------------------------------------------------------------------
# Méthodes
# ---------------------------------------------------------------------------

class rest_pose:
    """Met l'armature en pose de repos le temps d'une opération."""

    def __init__(self, arm):
        self.arm = arm

    def __enter__(self):
        self.prev = self.arm.data.pose_position
        self.arm.data.pose_position = "REST"
        bpy.context.view_layer.update()

    def __exit__(self, *exc):
        self.arm.data.pose_position = self.prev
        bpy.context.view_layer.update()


def transfer_weights(context, proj, obj, arm):
    src = proj.ref_weights_mesh
    if src is None or len(src.vertex_groups) == 0:
        raise McsError("Choisissez un maillage source des poids ayant des groupes de sommets nommés comme les os.")
    if src == obj:
        raise McsError("Le maillage source des poids ne peut pas être le maillage cible.")
    bones = {b.name for b in arm.data.bones}
    obj.vertex_groups.clear()
    for g in src.vertex_groups:
        obj.vertex_groups.new(name=g.name)
    mod = obj.modifiers.new("MCS_TransfertPoids", "DATA_TRANSFER")
    mod.object = src
    mod.use_object_transform = True
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    src_arm = src.find_armature()
    try:
        with rest_pose(arm), (rest_pose(src_arm) if src_arm and src_arm != arm else _null()):
            with context.temp_override(object=obj, active_object=obj):
                bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
                bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError as exc:
        if mod.name in obj.modifiers:
            obj.modifiers.remove(obj.modifiers[mod.name])
        raise McsError(f"Transfert des poids impossible sur {obj.name} : {exc}") from exc
    weights = limit_and_normalize(read_weights(obj), proj.max_influences)
    weights = {vi: {n: w for n, w in d.items()} for vi, d in weights.items()}
    write_weights(obj, weights)
    unknown = sorted({n for d in weights.values() for n in d} - bones)
    return unknown


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def attach_point(proj):
    if proj.bail is not None:
        mw = proj.bail.matrix_world
        pts = [mw @ v.co for v in proj.bail.data.vertices]
    else:
        pts = []
        for o, r in component_objects(proj, ("texte", "plaque")):
            pts.extend(o.matrix_world @ v.co for v in o.data.vertices)
        if pts:
            top = max(p.z for p in pts)
            pts = [p for p in pts if p.z >= top - 1e-4]
    if not pts:
        raise McsError("Pendentif vide : impossible de trouver le point d'attache.")
    return sum(pts, Vector()) / len(pts)


def chain_weight_at(proj, point):
    chains = [o for o, r in component_objects(proj, ("chaine",))]
    if not chains:
        raise McsError("Définissez la chaîne avant de pondérer le pendentif par son point d'attache.")
    candidates = []
    for obj in chains:
        w = read_weights(obj)
        mw = obj.matrix_world
        for vi, d in w.items():
            candidates.append((mw @ obj.data.vertices[vi].co, d))
    if not candidates:
        raise McsError("La chaîne n'a pas encore de poids : pondérez d'abord la chaîne.")
    tree = KDTree(len(candidates))
    for i, (co, d) in enumerate(candidates):
        tree.insert(co, i)
    tree.balance()
    co, idx, dist = tree.find(point)
    return candidates[idx][1], dist


def generate(context, proj, group, objs=None):
    """Génère les poids d'un groupe ; chaque objet est sauvegardé avant modification."""
    arm = require_armature(proj)
    method = proj.weight_method_chain if group == "CHAIN" else proj.weight_method_pendant
    targets = objs if objs is not None else group_targets(proj, group)
    if not targets:
        raise McsError("Aucun objet à pondérer pour ce groupe.")
    if method == "KEEP":
        return [f"{o.name} : poids conservés" for o in targets]
    notes = []
    bones = {b.name for b in arm.data.bones}
    if method == "RIGID_ATTACH":
        weights, dist = chain_weight_at(proj, attach_point(proj))
        weights = limit_and_normalize({0: weights}, proj.max_influences)[0]
        notes.append(f"point d'attache à {dist * 1000:.1f} mm de la chaîne : "
                     + ", ".join(f"{n} {w:.2f}" for n, w in weights.items()))
    for obj in targets:
        if obj.data.users > 1:
            raise McsError(f"{obj.name} partage son maillage avec un autre objet ; rendez-le unique d'abord.")
        backup(obj)
        if method == "TRANSFER":
            unknown = transfer_weights(context, proj, obj, arm)
            if unknown:
                notes.append(f"{obj.name} : groupes sans os correspondant : {', '.join(unknown[:6])}")
        elif method == "SINGLE_BONE":
            bone = proj.bone_chain if group == "CHAIN" else proj.bone_pendant
            if bone not in bones:
                restore(obj)
                raise McsError("Choisissez un os existant de l'armature pour la méthode « Un os choisi ».")
            write_weights(obj, {v.index: {bone: 1.0} for v in obj.data.vertices})
            obj[KEY_BONE] = bone
        elif method == "RIGID_ATTACH":
            write_weights(obj, {v.index: dict(weights) for v in obj.data.vertices})
        obj[KEY_METHOD] = method
        ensure_modifier(obj, arm)
    return notes


def reapply_pendant_weights(context, proj, previous):
    """Après régénération du texte, réapplique la méthode enregistrée sur chaque composant."""
    notes = []
    for role, prop in (("texte", "pendant_text"), ("plaque", "plate"), ("beliere", "bail")):
        method = previous.get(role)
        obj = getattr(proj, prop)
        if not method or obj is None or method == "KEEP":
            continue
        saved = proj.weight_method_pendant
        proj.weight_method_pendant = method
        try:
            generate(context, proj, "PENDANT", objs=[obj])
            notes.append(f"poids réappliqués sur {obj.name}")
        finally:
            proj.weight_method_pendant = saved
    return notes


def ensure_modifier(obj, arm):
    mod = obj.modifiers.get(MOD_NAME)
    if mod is None or mod.type != "ARMATURE":
        mod = obj.modifiers.new(MOD_NAME, "ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    return mod


# ---------------------------------------------------------------------------
# Vérifications
# ---------------------------------------------------------------------------

def rig_signature(proj):
    parts = [proj.ref_armature.name if proj.ref_armature else "-"]
    for obj, role in component_objects(proj):
        parts += [obj.name, mesh_checksum(obj.data), "|".join(g.name for g in obj.vertex_groups),
                  obj.get(KEY_METHOD, "")]
    return hash_strings(parts)


def analyse(proj, objs=None, armature=None, require_modifier=True):
    """Analyse complète : [(sévérité, message, correction, objet)]."""
    issues = []
    arm = armature or proj.ref_armature
    if arm is None or arm.type != "ARMATURE":
        return [("ERROR", "Aucune armature de référence.", "Choisissez l'armature du ped.", "")]
    bones = {b.name for b in arm.data.bones}
    if not bones:
        return [("ERROR", f"{arm.name} n'a aucun os.", "", arm.name)]
    if not arm.matrix_world.is_identity:
        issues.append(("WARNING", f"{arm.name} n'est pas à l'origine (position/rotation/échelle).",
                       "Les positions exportées sont relatives à l'armature : gardez-la à l'origine.", arm.name))
    k = proj.max_influences
    for obj, role in (objs if objs is not None else component_objects(proj)):
        if require_modifier:
            mods = [m for m in obj.modifiers if m.type == "ARMATURE"]
            if not mods:
                issues.append(("ERROR", f"{obj.name} : aucun modificateur Armature.", "Cliquez « Lier à l'armature ».", obj.name))
            elif any(m.object != arm for m in mods):
                issues.append(("ERROR", f"{obj.name} : modificateur Armature relié à une autre armature.",
                               "Cliquez « Lier à l'armature ».", obj.name))
        other = [m for m in obj.modifiers if m.type not in {"ARMATURE", "DATA_TRANSFER"}]
        if other:
            issues.append(("WARNING", f"{obj.name} : modificateurs {', '.join(m.type for m in other)} avant export.",
                           "Les poids s'appliquent au maillage de base ; appliquez ces modificateurs si besoin.", obj.name))
        if any(s < 0 for s in obj.matrix_world.to_scale()):
            issues.append(("WARNING", f"{obj.name} : échelle négative (normales inversées à l'export).", "", obj.name))
        unknown = [g.name for g in obj.vertex_groups if g.name not in bones]
        if unknown:
            issues.append(("ERROR", f"{obj.name} : groupes sans os dans {arm.name} : {', '.join(unknown[:6])}"
                                    + ("…" if len(unknown) > 6 else "") + ".",
                           "Sollumz les rattacherait à l'os racine : supprimez-les ou refaites les poids.", obj.name))
        weights = read_weights(obj)
        valid = {vi: {n: w for n, w in d.items() if n in bones} for vi, d in weights.items()}
        n = len(obj.data.vertices)
        unweighted = n - sum(1 for d in valid.values() if sum(d.values()) > 1e-6)
        if unweighted:
            issues.append(("ERROR", f"{obj.name} : {unweighted} sommet(s) sur {n} sans poids.",
                           "Générez les poids (section 5).", obj.name))
        over = sum(1 for d in valid.values() if len(d) > k)
        if over:
            issues.append(("WARNING", f"{obj.name} : {over} sommet(s) avec plus de {k} influences.",
                           "Seules les plus fortes seront gardées : refaites les poids pour les normaliser.", obj.name))
        bad_sum = sum(1 for d in valid.values() if d and abs(sum(d.values()) - 1.0) > 0.01)
        if bad_sum:
            issues.append(("WARNING", f"{obj.name} : {bad_sum} sommet(s) dont la somme des poids ≠ 1.", "", obj.name))
        method = obj.get(KEY_METHOD)
        if method and KEY_BACKUP in obj:
            issues.append(("INFO", f"{obj.name} : poids « {method} », sauvegarde précédente disponible.", "", obj.name))
    return issues


def store_report(proj, issues):
    proj.rig_report.clear()
    for sev, msg, fix, name in issues:
        item = proj.rig_report.add()
        item.severity, item.message, item.fix, item.object_name = sev, msg, fix, name
    proj.rig_report_sig = rig_signature(proj)


def weight_bones(proj):
    """Os réellement utilisés par le bijou, du plus influent au moins influent."""
    totals = {}
    for obj, role in component_objects(proj):
        for d in read_weights(obj).values():
            for n, w in d.items():
                totals[n] = totals.get(n, 0.0) + w
    return [n for n, w in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]


# ---------------------------------------------------------------------------
# Test de déformation (réversible)
# ---------------------------------------------------------------------------

def pose_test(proj):
    arm = require_armature(proj)
    bone = proj.deform_bone or (weight_bones(proj) or [None])[0]
    if bone is None or bone not in arm.pose.bones:
        raise McsError("Aucun os à tester : générez les poids ou choisissez un os.")
    pb = arm.pose.bones[bone]
    if KEY_POSE not in arm:
        arm[KEY_POSE] = {b.name: {"mode": b.rotation_mode, "q": list(b.rotation_quaternion),
                                  "e": list(b.rotation_euler), "l": list(b.location)} for b in arm.pose.bones}
        arm["mcs_pose_position"] = arm.data.pose_position
    arm.data.pose_position = "POSE"
    rot = Quaternion((1.0, 0.0, 0.0), proj.deform_angle)
    if pb.rotation_mode == "QUATERNION":
        pb.rotation_quaternion = pb.rotation_quaternion @ rot
    elif pb.rotation_mode == "AXIS_ANGLE":
        raise McsError(f"L'os {bone} utilise le mode axe-angle, non géré par le test.")
    else:
        e = pb.rotation_euler.copy()
        e.x += proj.deform_angle
        pb.rotation_euler = e
    return bone, bone in weight_bones(proj)


def pose_reset(proj):
    arm = require_armature(proj)
    data = arm.get(KEY_POSE)
    if data is None:
        raise McsError("Aucun test de pose à annuler.")
    for name, vals in data.items():
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pb.rotation_quaternion = vals["q"]
        pb.rotation_euler = vals["e"]
        pb.location = vals["l"]
        pb.rotation_mode = vals["mode"]
    arm.data.pose_position = arm.get("mcs_pose_position", "POSE")
    del arm[KEY_POSE]
    if "mcs_pose_position" in arm:
        del arm["mcs_pose_position"]


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_rig_link(bpy.types.Operator):
    bl_idname = "mio_chain.rig_link"
    bl_label = "Lier à l'armature"
    bl_description = "Ajoute (ou corrige) le modificateur Armature de chaque composant, sans le reparenter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            arm = require_armature(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        objs = [o for o, r in component_objects(proj)]
        for obj in objs:
            ensure_modifier(obj, arm)
        bad = [o.name for o in objs if not any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
        if bad:
            self.report({"ERROR"}, "Liaison non vérifiée : " + ", ".join(bad))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(objs)} composant(s) liés à {arm.name}.")
        return {"FINISHED"}


class MIO_OT_rig_weights(bpy.types.Operator):
    bl_idname = "mio_chain.rig_weights"
    bl_label = "Générer les poids"
    bl_description = "Applique la méthode choisie ; les poids précédents sont sauvegardés et restaurables"
    bl_options = {"REGISTER", "UNDO"}

    group: bpy.props.EnumProperty(items=[("CHAIN", "Chaîne", ""), ("PENDANT", "Pendentif", "")], options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        try:
            notes = generate(context, proj, self.group)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        objs = group_targets(proj, self.group)
        issues = [i for i in analyse(proj, [(o, "") for o in objs], require_modifier=False) if i[0] == "ERROR"]
        store_report(proj, analyse(proj))
        if issues:
            self.report({"ERROR"}, "Poids générés mais vérification en échec : " + " ".join(i[1] for i in issues[:3]))
            return {"CANCELLED"}
        self.report({"INFO"}, "Poids générés et vérifiés. " + " ; ".join(notes))
        return {"FINISHED"}


class MIO_OT_rig_restore(bpy.types.Operator):
    bl_idname = "mio_chain.rig_restore"
    bl_label = "Restaurer les poids précédents"
    bl_description = "Revient aux poids sauvegardés avant la dernière génération"
    bl_options = {"REGISTER", "UNDO"}

    group: bpy.props.EnumProperty(items=[("CHAIN", "Chaîne", ""), ("PENDANT", "Pendentif", "")], options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        done = []
        for obj in group_targets(proj, self.group):
            if KEY_BACKUP in obj:
                try:
                    restore(obj)
                except McsError as exc:
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
                done.append(obj.name)
        if not done:
            self.report({"WARNING"}, "Aucune sauvegarde de poids pour ce groupe.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Poids restaurés : " + ", ".join(done))
        return {"FINISHED"}


class MIO_OT_rig_check(bpy.types.Operator):
    bl_idname = "mio_chain.rig_check"
    bl_label = "Vérifier le rigging"
    bl_description = "Contrôle armature, liaisons, groupes, sommets sans poids et transformations"

    def execute(self, context):
        proj = get_project(context)
        issues = analyse(proj)
        store_report(proj, issues)
        errors = [i for i in issues if i[0] == "ERROR"]
        if errors:
            self.report({"WARNING"}, f"{len(errors)} erreur(s) bloquante(s) de rigging.")
        else:
            self.report({"INFO"}, "Rigging vérifié : aucune erreur bloquante.")
        return {"FINISHED"}


class MIO_OT_pose_test(bpy.types.Operator):
    bl_idname = "mio_chain.pose_test"
    bl_label = "Tester la déformation"
    bl_description = "Tourne un os pour observer la déformation ; « Remettre la pose » annule exactement"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            bone, used = pose_test(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        proj.deform_confirmed = False
        msg = f"Os {bone} tourné de {math.degrees(proj.deform_angle):.0f}°."
        if used:
            self.report({"INFO"}, msg + " Observez le bijou.")
        else:
            self.report({"WARNING"}, msg + " Aucun sommet du bijou n'est pondéré sur cet os : rien ne bougera.")
        return {"FINISHED"}


class MIO_OT_pose_reset(bpy.types.Operator):
    bl_idname = "mio_chain.pose_reset"
    bl_label = "Remettre la pose"
    bl_description = "Restaure la pose de l'armature d'avant le test"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            pose_reset(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Pose restaurée.")
        return {"FINISHED"}


class MIO_OT_deform_confirm(bpy.types.Operator):
    bl_idname = "mio_chain.deform_confirm"
    bl_label = "J'ai vérifié la déformation"
    bl_description = "Confirme votre contrôle visuel ; il sera invalidé si la géométrie ou les poids changent"

    def execute(self, context):
        proj = get_project(context)
        proj.deform_confirmed = True
        proj.deform_confirmed_sig = rig_signature(proj)
        return {"FINISHED"}


CLASSES = (MIO_OT_rig_link, MIO_OT_rig_weights, MIO_OT_rig_restore, MIO_OT_rig_check, MIO_OT_pose_test,
           MIO_OT_pose_reset, MIO_OT_deform_confirm)
