"""Étapes 3 et 4 : matériaux Sollumz appliqués aux seules faces sélectionnées, Value Parameters, presets.

« Ped — sans glow » et « Ped Emissive — avec glow » correspondent à des shaders réels de Sollumz,
réglables (par défaut ped.sps et ped_emissive.sps, dont les entrées ont été vérifiées dans Sollumz 2.9.0).
"""

import json
import os

import bmesh
import bpy
import numpy as np

from . import presets
from . import sollumz_bridge as szb
from . import teef
from .utils import (
    McsError,
    abspath,
    get_project,
    hash_strings,
    same_path,
    tag,
)

SAMPLERS = presets.SAMPLERS
REQUIRED_EMBEDDED = ("BumpSampler", "SpecSampler")

# Value Parameters de base (votre réglage du matériau MCS_glow). umGlobalParams vaut 0,0025, valeur de
# Sollumz que le panneau affiche arrondie à « 0.002 ». Seuls les paramètres présents dans le shader sont posés.
BASE_VALUE_PARAMS = {
    "umGlobalParams": [0.0025, 0.0025, 7.0, 7.0],
    "envEffFatThickness": [25.0, 25.0],
    "specularIntensityMult": [1997.0],
    "specularFalloffMult": [1997.0],
    "specularFresnel": [0.45],
    "bumpiness": [1.3],
    "emissiveMultiplier": [1.0],
    "detailSettings": [0.0, 0.0, 24.0],
    "StubbleControl": [2.0, 0.6],
}


def base_params_for(shader):
    """Value Parameters de base limités à ceux que le shader possède réellement."""
    definition = szb.find_shader(shader)
    if definition is None:
        return {}
    return {k: list(v) for k, v in BASE_VALUE_PARAMS.items() if k in definition.parameter_map}


# ---------------------------------------------------------------------------
# Description du matériau à appliquer
# ---------------------------------------------------------------------------

def spec_from_ui(proj):
    """Description complète (même format qu'un preset) selon le mode Preset ou Personnalisé."""
    shader = proj.shader_for_kind()
    if proj.mat_mode == "PRESET":
        if not proj.preset_name:
            raise McsError("Choisissez un preset.")
        data = presets.load(proj.preset_name)
        if data["shader"] != shader:
            raise McsError(f"Le preset « {proj.preset_name} » utilise {data['shader']} alors que le type choisi "
                           f"correspond à {shader}. Changez de type ou de preset.")
    else:
        data = {"version": presets.FORMAT, "shader": shader, "textures": {}, "params": base_params_for(shader)}
        if not proj.diffuse_path:
            raise McsError("Choisissez la texture DiffuseSampler.")
        data["textures"]["DiffuseSampler"] = {"path": abspath(proj.diffuse_path),
                                              "embedded": proj.diffuse_embedded, "colorspace": "sRGB"}
        data["textures"]["BumpSampler"] = {"path": abspath(proj.bump_path) if proj.bump_path else teef.path_of("bump"),
                                           "embedded": True, "colorspace": "Non-Color"}
        data["textures"]["SpecSampler"] = {"path": abspath(proj.spec_path) if proj.spec_path else teef.path_of("spec"),
                                           "embedded": True, "colorspace": None}
    # Exigences quel que soit le mode : Bump et Spec intégrés, Bump en Non-Color.
    for sampler in REQUIRED_EMBEDDED:
        if sampler in data["textures"]:
            data["textures"][sampler]["embedded"] = True
    if "BumpSampler" in data["textures"]:
        data["textures"]["BumpSampler"]["colorspace"] = "Non-Color"
    return data


def validate(data, preset_name=None):
    shader = data["shader"]
    if szb.find_shader(shader) is None:
        raise McsError(f"Shader « {shader} » inconnu de Sollumz.")
    available = set(szb.shader_texture_params(shader))
    for sampler in SAMPLERS:
        if sampler not in available:
            raise McsError(f"Le shader {shader} n'a pas d'entrée {sampler}.")
        tex = data["textures"].get(sampler)
        if not tex or not tex.get("path"):
            where = f" dans le preset « {preset_name} »" if preset_name else ""
            raise McsError(f"Texture {sampler} non définie{where}.")
        if not os.path.isfile(tex["path"]):
            hint = (" Relocalisez-la avec « Relocaliser » (étape 4)." if preset_name else
                    " Vérifiez le dossier Teef ou choisissez un autre fichier.")
            raise McsError(f"{sampler} : fichier introuvable ({tex['path']}).{hint}")
        if tex.get("embedded") and not tex["path"].lower().endswith(".dds"):
            raise McsError(f"{sampler} est intégrée (Embedded) mais n'est pas un DDS : Sollumz n'intègre que des DDS.")


def material_key(data):
    return hash_strings([json.dumps(data, sort_keys=True)])


# ---------------------------------------------------------------------------
# Images : espace colorimétrique sans effet de bord
# ---------------------------------------------------------------------------

def _image_users_outside(img, mat):
    for m in bpy.data.materials:
        if m == mat or m.node_tree is None:
            continue
        for n in m.node_tree.nodes:
            if n.bl_idname == "ShaderNodeTexImage" and n.image == img:
                return True
    return False


def get_image(path, colorspace, mat):
    """Image du fichier `path` dans l'espace demandé, sans modifier une image partagée avec d'autres matériaux."""
    candidates = [i for i in bpy.data.images if same_path(i.filepath, path)]
    for img in candidates:
        if colorspace is None or img.colorspace_settings.name == colorspace:
            return img
    for img in candidates:
        if not _image_users_outside(img, mat):
            img.colorspace_settings.name = colorspace
            return img
    try:
        img = bpy.data.images.load(path, check_existing=False)
    except RuntimeError as exc:
        raise McsError(f"Image illisible ({os.path.basename(path)}) : {exc}") from exc
    if colorspace:
        img.colorspace_settings.name = colorspace
    return img


def configure_material(mat, data):
    shader = data["shader"]
    if szb.material_shader(mat) != shader:
        szb.change_shader(mat, shader)
    for node in szb.texture_nodes(mat):
        tex = data["textures"].get(node.name)
        if tex is None:
            continue
        node.image = get_image(tex["path"], tex.get("colorspace"), mat)
        node.texture_properties.embedded = bool(tex.get("embedded"))
    for name, values in data.get("params", {}).items():
        node = szb.param_node(mat, name)
        if node is not None and len(values) == len(node.outputs):
            for out, v in zip(node.outputs, values):
                out.default_value = v


def get_or_create_material(proj, data, label):
    key = material_key(data)
    for mat in bpy.data.materials:
        if mat.get("mcs_mat_key") == key and mat.get("mcs_project") == proj.project_id and szb.is_sollumz_material(mat):
            configure_material(mat, data)
            return mat, False
    mat = szb.create_material(data["shader"], f"MCS_{label}")
    tag(mat, proj, role="materiau", mcs_mat_key=key)
    configure_material(mat, data)
    return mat, True


# ---------------------------------------------------------------------------
# Application aux faces sélectionnées
# ---------------------------------------------------------------------------

def _uv_array(mesh, name):
    layer = mesh.uv_layers.get(name)
    if layer is None:
        return None
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uv)
    return uv.reshape(-1, 2)


def apply_to_selected_faces(context, proj):
    szb.require()
    obj = context.edit_object
    if obj is None or obj.type != "MESH":
        raise McsError("Passez en Edit Mode sur le maillage et sélectionnez les faces à traiter.")
    data = spec_from_ui(proj)
    validate(data, proj.preset_name if proj.mat_mode == "PRESET" else None)
    bm = bmesh.from_edit_mesh(obj.data)
    if not any(f.select for f in bm.faces):
        raise McsError("Aucune face sélectionnée.")
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        me = obj.data
        n = len(me.polygons)
        sel = np.empty(n, dtype=bool)
        me.polygons.foreach_get("select", sel)
        mat_before = np.empty(n, dtype=np.int32)
        me.polygons.foreach_get("material_index", mat_before)
        uv_name = szb.uv_map_name(0)
        if uv_name not in me.uv_layers:
            if len(me.uv_layers):
                me.uv_layers[0].name = uv_name       # renommage seulement : valeurs inchangées
            else:
                me.uv_layers.new(name=uv_name)
        uv_before = _uv_array(me, uv_name)
        label = proj.preset_name if proj.mat_mode == "PRESET" else ("glow" if proj.mat_kind == "EMISSIVE" else "ped")
        mat, created = get_or_create_material(proj, data, label)
        slots = list(me.materials)
        if mat in slots:
            idx = slots.index(mat)
        else:
            me.materials.append(mat)
            idx = len(me.materials) - 1
        new_idx = mat_before.copy()
        new_idx[sel] = idx
        me.polygons.foreach_set("material_index", new_idx)
        szb.sz("tools.meshhelper").mesh_add_missing_uv_maps(me)   # ex. UVMap 1 exigée par ped_emissive
        me.uv_layers.active = me.uv_layers[uv_name]
    finally:
        bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.cube_project(cube_size=proj.cube_size, correct_aspect=proj.cube_correct_aspect,
                            clip_to_bounds=proj.cube_clip_to_bounds, scale_to_bounds=proj.cube_scale_to_bounds)
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        problems = verify_application(obj, sel, mat_before, uv_before, idx, mat)
    finally:
        bpy.ops.object.mode_set(mode="EDIT")
    if problems:
        raise McsError("Vérification en échec : " + " ".join(problems))
    return mat, created, int(sel.sum())


def selected_loops(me, sel):
    """Masque des coins de face appartenant aux faces sélectionnées."""
    starts = np.empty(len(me.polygons), dtype=np.int32)
    totals = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("loop_start", starts)
    me.polygons.foreach_get("loop_total", totals)
    mask = np.zeros(len(me.loops), dtype=bool)
    for p in np.nonzero(sel)[0]:
        mask[starts[p]:starts[p] + totals[p]] = True
    return mask


def verify_application(obj, sel, mat_before, uv_before, idx, mat):
    me = obj.data
    problems = []
    after = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("material_index", after)
    if not (after[sel] == idx).all():
        problems.append("des faces sélectionnées n'ont pas reçu le matériau.")
    if not (after[~sel] == mat_before[~sel]).all():
        problems.append("des faces non sélectionnées ont changé de matériau.")
    uv_after = _uv_array(me, szb.uv_map_name(0))
    if uv_before is not None and uv_after is not None:
        if not np.allclose(uv_after[~selected_loops(me, sel)], uv_before[~selected_loops(me, sel)]):
            problems.append("des UV de faces non sélectionnées ont changé.")
    for node in szb.texture_nodes(mat):
        if node.name in REQUIRED_EMBEDDED and not node.texture_properties.embedded:
            problems.append(f"{node.name} n'est pas Embedded.")
        if node.name == "BumpSampler" and (node.image is None or node.image.colorspace_settings.name != "Non-Color"):
            problems.append("l'image BumpSampler n'est pas en Non-Color.")
    return problems


# ---------------------------------------------------------------------------
# Value Parameters
# ---------------------------------------------------------------------------

def value_parameters(mat):
    """[(nom, nœud)] des paramètres numériques du shader réellement présents dans le matériau."""
    shader = szb.find_shader(szb.material_shader(mat)) if szb.is_sollumz_material(mat) else None
    if shader is None:
        return []
    out = []
    for p in shader.parameters:
        if str(getattr(p.type, "value", p.type)).lower() == "texture" or getattr(p, "hidden", False):
            continue
        node = szb.param_node(mat, p.name)
        if node is not None:
            out.append((p.name, node))
    return out


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_apply_faces(bpy.types.Operator):
    bl_idname = "mio_chain.apply_faces"
    bl_label = "Appliquer aux faces sélectionnées"
    bl_description = ("Crée ou réutilise le matériau Sollumz, l'assigne aux faces sélectionnées uniquement, "
                      "règle les textures (Bump et Spec Embedded, Bump en Non-Color) et projette leurs UV en cube")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == "MESH"

    def execute(self, context):
        proj = get_project(context)
        try:
            mat, created, count = apply_to_selected_faces(context, proj)
        except McsError as exc:
            if context.mode != "EDIT_MESH" and context.active_object and context.active_object.type == "MESH":
                bpy.ops.object.mode_set(mode="EDIT")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        verb = "créé" if created else "réutilisé"
        self.report({"INFO"}, f"{mat.name} ({szb.material_shader(mat)}) {verb}, appliqué à {count} face(s), "
                              "UV projetées en cube sur ces faces uniquement.")
        return {"FINISHED"}


class MIO_OT_preset_save(bpy.types.Operator):
    bl_idname = "mio_chain.preset_save"
    bl_label = "Enregistrer comme preset"
    bl_description = "Enregistre shader, textures, Embedded, espaces colorimétriques et paramètres du matériau actif"

    overwrite: bpy.props.BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        proj = get_project(context)
        try:
            exists = os.path.exists(presets.path_of(proj.new_preset_name))
        except McsError:
            exists = False
        if exists:
            self.overwrite = True
            return context.window_manager.invoke_confirm(self, event, title="Remplacer le preset ?",
                                                         message=f"« {proj.new_preset_name} » existe déjà.")
        return self.execute(context)

    def execute(self, context):
        proj = get_project(context)
        obj = context.active_object
        mat = obj.active_material if obj else None
        if not szb.is_sollumz_material(mat):
            self.report({"ERROR"}, "Le matériau actif n'est pas un matériau Sollumz.")
            return {"CANCELLED"}
        try:
            if os.path.exists(presets.path_of(proj.new_preset_name)) and not self.overwrite:
                raise McsError(f"Le preset « {proj.new_preset_name} » existe déjà.")
            data = presets.capture(mat)
            path = presets.save(proj.new_preset_name, data)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        complete, missing, absent = presets.status(data)
        msg = f"Preset enregistré : {path}"
        if not complete:
            self.report({"WARNING"}, msg + " — incomplet : " + ", ".join(absent + [s for s, p in missing]))
        else:
            self.report({"INFO"}, msg)
        proj.preset_name = presets.safe_name(proj.new_preset_name)
        return {"FINISHED"}


class MIO_OT_preset_apply(bpy.types.Operator):
    bl_idname = "mio_chain.preset_apply"
    bl_label = "Appliquer un preset"
    bl_description = "Applique le preset choisi au matériau actif (shader, textures, paramètres)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        obj = context.active_object
        mat = obj.active_material if obj else None
        if not szb.is_sollumz_material(mat):
            self.report({"ERROR"}, "Le matériau actif n'est pas un matériau Sollumz.")
            return {"CANCELLED"}
        try:
            data = presets.load(proj.preset_name)
            complete, missing, absent = presets.status(data)
            if missing:
                raise McsError("Textures introuvables : " + ", ".join(f"{s} ({p})" for s, p in missing) +
                               ". Relocalisez-les avant d'appliquer.")
            configure_material(mat, data)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        mat["mcs_mat_key"] = material_key(data)
        self.report({"INFO"}, f"Preset « {proj.preset_name} » appliqué à {mat.name}.")
        return {"FINISHED"}


class MIO_OT_preset_duplicate(bpy.types.Operator):
    bl_idname = "mio_chain.preset_duplicate"
    bl_label = "Dupliquer le preset"
    bl_description = "Copie le preset choisi sous le nom indiqué"

    def execute(self, context):
        proj = get_project(context)
        new = proj.new_preset_name if proj.new_preset_name != proj.preset_name else f"{proj.preset_name}_copie"
        try:
            path = presets.duplicate(proj.preset_name, new)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        proj.preset_name = presets.safe_name(new)
        self.report({"INFO"}, f"Preset dupliqué : {path}")
        return {"FINISHED"}


class MIO_OT_preset_delete(bpy.types.Operator):
    bl_idname = "mio_chain.preset_delete"
    bl_label = "Supprimer le preset"
    bl_description = "Supprime définitivement le fichier du preset choisi"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Supprimer le preset ?",
                                                     message=f"« {get_project(context).preset_name} » sera supprimé.")

    def execute(self, context):
        proj = get_project(context)
        try:
            presets.delete(proj.preset_name)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Preset « {proj.preset_name} » supprimé.")
        proj.preset_name = ""
        return {"FINISHED"}


class MIO_OT_preset_relocate(bpy.types.Operator):
    bl_idname = "mio_chain.preset_relocate"
    bl_label = "Relocaliser"
    bl_description = "Indique le nouvel emplacement d'une texture manquante du preset"

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
            presets.relocate(proj.preset_name, self.sampler, self.filepath)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{self.sampler} relocalisée : {self.filepath}")
        return {"FINISHED"}


class MIO_OT_params_base(bpy.types.Operator):
    bl_idname = "mio_chain.params_base"
    bl_label = "Appliquer les Value Parameters de base"
    bl_description = ("Remet les Value Parameters du matériau actif aux valeurs de base "
                      "(specularIntensityMult 1997, specularFalloffMult 1997, specularFresnel 0,45, bumpiness 1,3…)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        mat = obj.active_material if obj else None
        if not szb.is_sollumz_material(mat):
            self.report({"ERROR"}, "Le matériau actif n'est pas un matériau Sollumz.")
            return {"CANCELLED"}
        params = base_params_for(szb.material_shader(mat))
        applied = []
        for name, values in params.items():
            node = szb.param_node(mat, name)
            if node is not None and len(values) == len(node.outputs):
                for out, v in zip(node.outputs, values):
                    out.default_value = v
                applied.append(name)
        if not applied:
            self.report({"ERROR"}, f"Aucun paramètre de base ne correspond au shader {szb.material_shader(mat)}.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{mat.name} : {len(applied)} Value Parameters de base appliqués.")
        return {"FINISHED"}


CLASSES = (MIO_OT_apply_faces, MIO_OT_params_base, MIO_OT_preset_save, MIO_OT_preset_apply, MIO_OT_preset_duplicate,
           MIO_OT_preset_delete, MIO_OT_preset_relocate)
