"""Section 4 : effets (émissif vérifié dans la définition Sollumz du shader) et couleurs de sommets."""

import bpy
import numpy as np

from . import sollumz_bridge as szb
from .materials import component_materials
from .utils import McsError, ROLE_LABELS, component_objects, get_project

EMISSIVE_PARAM = "emissiveMultiplier"
KEY_BEFORE = "mcs_shader_before_emissive"


def emissive_shaders():
    """Shaders de la famille ped dont la définition Sollumz contient emissiveMultiplier."""
    return szb.shaders_with_param(EMISSIVE_PARAM, prefix="ped")


def role_material(proj, role):
    for obj, r, i, mat in component_materials(proj, (role,)):
        return mat
    return None


def is_emissive(mat):
    return szb.param_node(mat, EMISSIVE_PARAM) is not None


def set_emissive(proj, role, enable):
    szb.require()
    mat = role_material(proj, role)
    if mat is None:
        raise McsError(f"{ROLE_LABELS[role]} : aucun matériau Sollumz (section 3).")
    if enable:
        if not is_emissive(mat):
            candidates = emissive_shaders()
            if not candidates:
                raise McsError("Aucun shader ped émissif dans cette version de Sollumz.")
            mat[KEY_BEFORE] = szb.material_shader(mat)
            target = candidates[0]
            szb.change_shader(mat, target)
            setattr(proj, f"shader_{role}", target)
        node = szb.param_node(mat, EMISSIVE_PARAM)
        if node is None:
            raise McsError(f"Le shader {szb.material_shader(mat)} n'expose pas {EMISSIVE_PARAM}.")
        node.outputs[0].default_value = proj.emissive_multiplier
    else:
        before = mat.get(KEY_BEFORE)
        if not before:
            raise McsError(f"{mat.name} n'a pas été rendu émissif par l'addon ; changez son shader en section 3.")
        szb.change_shader(mat, before)
        setattr(proj, f"shader_{role}", before)
        del mat[KEY_BEFORE]
    for obj, r, i, m in component_materials(proj, (role,)):
        szb.update_mesh_attributes(obj, m)
    return mat


def emissive_value(mat):
    node = szb.param_node(mat, EMISSIVE_PARAM)
    return node.outputs[0].default_value if node else None


# ---------------------------------------------------------------------------
# Couleurs de sommets
# ---------------------------------------------------------------------------

def _to_bytes(color):
    return tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in color)


def used_color_indices(obj):
    used = set()
    for mat in obj.data.materials:
        shader = szb.find_shader(szb.material_shader(mat)) if szb.is_sollumz_material(mat) else None
        if shader is not None:
            used |= set(shader.used_colors_indices)
    return sorted(used)


def write_colors(mesh, index, color):
    """Remplit l'attribut couleur Sollumz d'indice `index` (Coin de face ▶ Couleur octet) avec `color`."""
    name = szb.color_attr_name(index)
    attr = mesh.color_attributes.get(name)
    if attr is not None and (attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR"):
        mesh.color_attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.color_attributes.new(name, "BYTE_COLOR", "CORNER")
    values = np.tile(np.array(color, dtype=np.float32), len(attr.data))
    attr.data.foreach_set("color_srgb", values)
    return attr


def read_colors(mesh, index):
    attr = mesh.color_attributes.get(szb.color_attr_name(index))
    if attr is None or len(attr.data) == 0:
        return None
    vals = np.empty(len(attr.data) * 4, dtype=np.float32)
    attr.data.foreach_get("color_srgb", vals)
    return np.round(vals.reshape(-1, 4) * 255).astype(np.int32)


def colors_issues(proj, objs=None):
    """Compare les attributs couleur réels aux valeurs demandées."""
    issues = []
    expected = {0: _to_bytes(proj.vcol0), 1: _to_bytes(proj.vcol1)}
    for obj, role in objs if objs is not None else component_objects(proj):
        for idx in used_color_indices(obj):
            got = read_colors(obj.data, idx)
            name = szb.color_attr_name(idx)
            if got is None:
                issues.append(("ERROR", f"{obj.name} : attribut « {name} » absent.", "Appliquez les couleurs de sommets."))
                continue
            attr = obj.data.color_attributes[name]
            if attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR":
                issues.append(("WARNING", f"{obj.name} : « {name} » n'est pas au format Coin de face ▶ Couleur octet.", ""))
            want = expected.get(idx)
            if want is not None and not (np.abs(got - np.array(want)) <= 1).all():
                issues.append(("WARNING", f"{obj.name} : « {name} » ne vaut pas {want} partout.",
                               "Appliquez de nouveau les couleurs de sommets."))
    return issues


def apply_colors(proj, objs=None):
    szb.require()
    count = 0
    for obj, role in objs if objs is not None else component_objects(proj):
        indices = used_color_indices(obj)
        if not indices:
            continue
        for idx in indices:
            color = proj.vcol0 if idx == 0 else proj.vcol1 if idx == 1 else None
            if color is not None:
                write_colors(obj.data, idx, tuple(color))
        count += 1
    if count == 0:
        raise McsError("Aucun composant avec un shader Sollumz utilisant des couleurs de sommets.")
    return count


def colors_from_reference(proj):
    ref = proj.ref_model
    if ref is None or ref.type != "MESH":
        raise McsError("Choisissez un modèle de référence (section 2) importé avec Sollumz.")
    found = {}
    for idx in (0, 1):
        got = read_colors(ref.data, idx)
        if got is None:
            continue
        rows, counts = np.unique(got, axis=0, return_counts=True)
        best = int(np.argmax(counts))
        found[idx] = (tuple(int(v) for v in rows[best]), counts[best] / len(got))
    if not found:
        raise McsError(f"{ref.name} n'a pas d'attributs « Color 1 » / « Color 2 ».")
    if 0 in found:
        proj.vcol0 = tuple(v / 255 for v in found[0][0])
    if 1 in found:
        proj.vcol1 = tuple(v / 255 for v in found[1][0])
    return found


class MIO_OT_emissive_set(bpy.types.Operator):
    bl_idname = "mio_chain.emissive_set"
    bl_label = "Émissif"
    bl_description = "Passe le matériau sur un shader ped émissif (ou revient au shader précédent)"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.StringProperty(options={"HIDDEN"})
    enable: bpy.props.BoolProperty(options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        try:
            mat = set_emissive(proj, self.role, self.enable)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if self.enable:
            value = emissive_value(mat)
            if value is None:
                self.report({"ERROR"}, "Paramètre émissif introuvable après conversion.")
                return {"CANCELLED"}
            self.report({"INFO"}, f"{mat.name} : {szb.material_shader(mat)}, {EMISSIVE_PARAM} = {value:g}.")
        else:
            self.report({"INFO"}, f"{mat.name} : retour à {szb.material_shader(mat)}.")
        return {"FINISHED"}


class MIO_OT_vertex_colors_apply(bpy.types.Operator):
    bl_idname = "mio_chain.vertex_colors_apply"
    bl_label = "Appliquer les couleurs de sommets"
    bl_description = "Remplit les attributs « Color 1 / Color 2 » exigés par le shader avec les valeurs choisies"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            count = apply_colors(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        issues = colors_issues(proj)
        if issues:
            self.report({"ERROR"}, "Vérification en échec : " + " ".join(m for s, m, f in issues))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Couleurs de sommets appliquées et vérifiées sur {count} objet(s).")
        return {"FINISHED"}


class MIO_OT_vertex_colors_from_ref(bpy.types.Operator):
    bl_idname = "mio_chain.vertex_colors_from_ref"
    bl_label = "Lire depuis la référence"
    bl_description = "Relève la valeur la plus fréquente des attributs couleur du modèle de référence"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            found = colors_from_reference(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        parts = [f"Color {i + 1} = {v} ({share:.0%} des coins)" for i, (v, share) in sorted(found.items())]
        self.report({"INFO"}, "Référence : " + " ; ".join(parts))
        return {"FINISHED"}


CLASSES = (MIO_OT_emissive_set, MIO_OT_vertex_colors_apply, MIO_OT_vertex_colors_from_ref)
