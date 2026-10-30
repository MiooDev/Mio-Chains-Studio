"""Section 3 : matériaux Sollumz, textures, préréglages réutilisables."""

import json
import os

import bpy

from . import sollumz_bridge as szb
from .prefs import addon_prefs
from .utils import (
    McsError,
    ROLE_LABELS,
    abspath,
    component_objects,
    get_project,
    is_power_of_two,
    tag,
)

NON_COLOR_SAMPLERS = {"BumpSampler", "SpecSampler"}


def _carry_over_image(mat):
    """Image reliée à la couleur de base d'un matériau non Sollumz (ex. matériau .mtl de l'OBJ)."""
    if mat is None or mat.node_tree is None:
        return None
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            sock = node.inputs.get("Base Color")
            if sock and sock.is_linked:
                src = sock.links[0].from_node
                if src.bl_idname == "ShaderNodeTexImage" and src.image and src.image.filepath:
                    return src.image
    return None


def setup_materials(proj):
    """Crée ou convertit les matériaux de chaque composant selon le shader choisi."""
    szb.require()
    done = []
    objs = component_objects(proj)
    if not objs:
        raise McsError("Aucun composant : créez le pendentif ou définissez la chaîne.")
    for obj, role in objs:
        filename = proj.shader_for(role)
        if szb.find_shader(filename) is None:
            raise McsError(f"Shader « {filename} » inconnu de Sollumz ({ROLE_LABELS[role]}).")
        mesh = obj.data
        if len(mesh.materials) == 0:
            mesh.materials.append(None)
        for i, mat in enumerate(mesh.materials):
            if szb.is_sollumz_material(mat):
                if szb.material_shader(mat) != filename:
                    szb.change_shader(mat, filename)
                    done.append(f"{obj.name} : {mat.name} → {filename}")
                continue
            carried = _carry_over_image(mat)
            suffix = f"_{i}" if len(mesh.materials) > 1 else ""
            new = szb.create_material(filename, f"MCS_{role}{suffix}")
            tag(new, proj, role=role)
            if carried is not None:
                node = new.node_tree.nodes.get("DiffuseSampler")
                if node is not None:
                    node.image = carried
            mesh.materials[i] = new
            done.append(f"{obj.name} : nouveau matériau {new.name} ({filename})")
        for mat in mesh.materials:
            szb.update_mesh_attributes(obj, mat)
    return done


def component_materials(proj, roles=None):
    """[(objet, rôle, index, matériau)] pour les matériaux Sollumz des composants."""
    result = []
    for obj, role in component_objects(proj) if roles is None else component_objects(proj, roles):
        for i, mat in enumerate(obj.data.materials):
            if szb.is_sollumz_material(mat):
                result.append((obj, role, i, mat))
    return result


def unique_materials(proj):
    seen, result = set(), []
    for obj, role, i, mat in component_materials(proj):
        if mat.name not in seen:
            seen.add(mat.name)
            result.append((mat, role))
    return result


def image_is_real(image):
    return image is not None and bool(image.filepath)


def image_file_ok(image):
    if image is None:
        return False
    if image.packed_file is not None:
        return True
    return bool(image.filepath) and os.path.isfile(abspath(image.filepath))


def texture_issues(mat, prefs):
    """Problèmes de textures d'un matériau Sollumz : [(sévérité, message, correction)]."""
    issues = []
    used = set(szb.shader_texture_params(szb.material_shader(mat)))
    for node in szb.texture_nodes(mat):
        if node.name not in used:
            continue
        img = node.image
        label = f"{mat.name} › {node.name}"
        if not image_is_real(img):
            sev = "ERROR" if node.name == "DiffuseSampler" else "INFO"
            msg = f"{label} : aucune texture." + ("" if sev == "ERROR" else " Laissée vide (comme dans votre référence).")
            issues.append((sev, msg, "Choisissez une image." if sev == "ERROR" else ""))
            continue
        if not image_file_ok(img):
            issues.append(("ERROR", f"{label} : fichier introuvable ({abspath(img.filepath)}).",
                           "Corrigez le chemin ou choisissez une autre image."))
            continue
        w, h = img.size
        if w == 0 or h == 0:
            issues.append(("ERROR", f"{label} : image illisible.", "Vérifiez le fichier."))
            continue
        if not (is_power_of_two(w) and is_power_of_two(h)):
            issues.append(("WARNING", f"{label} : {w}×{h} n'est pas une puissance de deux.",
                           "Redimensionnez (ex. 512, 1024) avant la conversion DDS."))
        limit = prefs.texture_warning if prefs else 2048
        if max(w, h) > limit:
            issues.append(("WARNING", f"{label} : {w}×{h} dépasse votre seuil de {limit} px.", ""))
        if node.texture_properties.embedded and not abspath(img.filepath).lower().endswith(".dds") \
                and img.packed_file is None:
            issues.append(("ERROR", f"{label} : texture intégrée au YDD mais pas au format DDS.",
                           "Sollumz n'intègre que des DDS : convertissez-la ou décochez « intégrée »."))
    return issues


def assign_texture(proj, mat_name, sampler, filepath):
    mat = bpy.data.materials.get(mat_name)
    if not szb.is_sollumz_material(mat):
        raise McsError(f"Matériau Sollumz « {mat_name} » introuvable.")
    node = mat.node_tree.nodes.get(sampler)
    if node is None or node.bl_idname != "ShaderNodeTexImage":
        raise McsError(f"Le shader de {mat_name} n'a pas d'entrée {sampler}.")
    path = abspath(filepath)
    if not os.path.isfile(path):
        raise McsError(f"Image introuvable : {path}")
    try:
        img = bpy.data.images.load(path, check_existing=True)
    except RuntimeError as exc:
        raise McsError(f"Image illisible : {exc}") from exc
    if sampler in NON_COLOR_SAMPLERS:
        img.colorspace_settings.name = "Non-Color"
    node.image = img
    return img


# ---------------------------------------------------------------------------
# Préréglages
# ---------------------------------------------------------------------------

def preset_path(name):
    prefs = addon_prefs()
    folder = prefs.presets_folder() if prefs else bpy.utils.user_resource("CONFIG", path="mio_chain_studio", create=True)
    safe = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe:
        raise McsError("Nom de préréglage invalide.")
    return os.path.join(folder, safe + ".json")


def list_presets():
    prefs = addon_prefs()
    if prefs is None:
        return []
    folder = prefs.presets_folder()
    return sorted(os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json"))


def capture_preset(mat):
    data = {"version": 1, "shader": szb.material_shader(mat), "params": {}, "textures": {}, "embedded": {}}
    for node in mat.node_tree.nodes:
        if node.bl_idname == "SOLLUMZ_NT_SHADER_Parameter":
            data["params"][node.name] = [float(o.default_value) for o in node.outputs]
        elif node.bl_idname == "ShaderNodeTexImage" and image_is_real(node.image):
            data["textures"][node.name] = abspath(node.image.filepath)
            data["embedded"][node.name] = bool(node.texture_properties.embedded)
    return data


def apply_preset(proj, mat, data):
    """Applique un préréglage ; retourne la liste des textures introuvables."""
    shader = data.get("shader")
    if not shader or szb.find_shader(shader) is None:
        raise McsError(f"Préréglage invalide : shader « {shader} » inconnu de Sollumz.")
    if szb.material_shader(mat) != shader:
        szb.change_shader(mat, shader)
    for node in mat.node_tree.nodes:
        if node.bl_idname == "SOLLUMZ_NT_SHADER_Parameter" and node.name in data.get("params", {}):
            values = data["params"][node.name]
            if len(values) == len(node.outputs):
                for out, v in zip(node.outputs, values):
                    out.default_value = v
    missing = []
    for sampler, path in data.get("textures", {}).items():
        try:
            assign_texture(proj, mat.name, sampler, path)
            mat.node_tree.nodes[sampler].texture_properties.embedded = data.get("embedded", {}).get(sampler, False)
        except McsError:
            missing.append(path)
    return missing


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_materials_setup(bpy.types.Operator):
    bl_idname = "mio_chain.materials_setup"
    bl_label = "Créer / configurer les matériaux"
    bl_description = "Crée les matériaux Sollumz manquants et applique le shader choisi à chaque composant"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            done = setup_materials(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        mats = component_materials(proj)
        objs = component_objects(proj)
        missing = [o.name for o, r in objs if not any(szb.is_sollumz_material(m) for m in o.data.materials)]
        if missing:
            self.report({"ERROR"}, "Sans matériau Sollumz : " + ", ".join(missing))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(mats)} matériau(x) Sollumz en place. " + ("; ".join(done) if done else "Aucun changement."))
        return {"FINISHED"}


class MIO_OT_texture_assign(bpy.types.Operator):
    bl_idname = "mio_chain.texture_assign"
    bl_label = "Choisir une image"
    bl_description = "Associe un fichier image à cette entrée du shader"
    bl_options = {"REGISTER", "UNDO"}

    material: bpy.props.StringProperty(options={"HIDDEN"})
    sampler: bpy.props.StringProperty(options={"HIDDEN"})
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        proj = get_project(context)
        try:
            img = assign_texture(proj, self.material, self.sampler, self.filepath)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        w, h = img.size
        self.report({"INFO"}, f"{self.sampler} ← {os.path.basename(img.filepath)} ({w}×{h}), "
                              f"nom de texture : {szb.texture_name_of_image(img)}")
        return {"FINISHED"}


class MIO_OT_texture_clear(bpy.types.Operator):
    bl_idname = "mio_chain.texture_clear"
    bl_label = "Vider"
    bl_description = "Retire l'image de cette entrée (l'image reste dans le fichier)"
    bl_options = {"REGISTER", "UNDO"}

    material: bpy.props.StringProperty(options={"HIDDEN"})
    sampler: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        node = mat.node_tree.nodes.get(self.sampler) if mat and mat.node_tree else None
        if node is None:
            return {"CANCELLED"}
        node.image = None
        return {"FINISHED"}


class MIO_OT_preset_save(bpy.types.Operator):
    bl_idname = "mio_chain.preset_save"
    bl_label = "Enregistrer le préréglage"
    bl_description = "Enregistre shader, paramètres et chemins de textures de ce matériau (JSON)"

    material: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        mat = bpy.data.materials.get(self.material)
        if not szb.is_sollumz_material(mat):
            self.report({"ERROR"}, "Choisissez un matériau Sollumz.")
            return {"CANCELLED"}
        try:
            path = preset_path(proj.preset_name)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        data = capture_preset(mat)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        with open(path, encoding="utf-8") as f:
            ok = json.load(f).get("shader") == data["shader"]
        if not ok:
            self.report({"ERROR"}, f"Écriture du préréglage non vérifiée : {path}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Préréglage enregistré : {path}")
        return {"FINISHED"}


def _preset_items(self, context):
    items = [(n, n, "") for n in list_presets()]
    _preset_items.cache = items or [("", "(aucun préréglage)", "")]
    return _preset_items.cache


class MIO_OT_preset_load(bpy.types.Operator):
    bl_idname = "mio_chain.preset_load"
    bl_label = "Appliquer un préréglage"
    bl_description = "Applique un préréglage enregistré à ce matériau"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "preset"

    material: bpy.props.StringProperty(options={"HIDDEN"})
    preset: bpy.props.EnumProperty(name="Préréglage", items=_preset_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        proj = get_project(context)
        mat = bpy.data.materials.get(self.material)
        if not szb.is_sollumz_material(mat) or not self.preset:
            self.report({"ERROR"}, "Matériau ou préréglage invalide.")
            return {"CANCELLED"}
        try:
            with open(preset_path(self.preset), encoding="utf-8") as f:
                data = json.load(f)
            missing = apply_preset(proj, mat, data)
        except (OSError, ValueError, McsError) as exc:
            self.report({"ERROR"}, f"Préréglage illisible : {exc}")
            return {"CANCELLED"}
        if missing:
            self.report({"WARNING"}, "Préréglage appliqué, textures introuvables : " + ", ".join(missing))
        else:
            self.report({"INFO"}, f"Préréglage « {self.preset} » appliqué à {mat.name}.")
        return {"FINISHED"}


CLASSES = (MIO_OT_materials_setup, MIO_OT_texture_assign, MIO_OT_texture_clear, MIO_OT_preset_save,
           MIO_OT_preset_load)
