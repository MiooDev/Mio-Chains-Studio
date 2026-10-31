"""Pont vers Sollumz installé (aucun système d'export GTA indépendant).

Toutes les opérations GTA (matériaux, dictionnaires de textures, export) passent par
les fonctions et opérateurs de la version de Sollumz réellement installée.
Vérifié avec Sollumz 2.9.0 (dernière version publiée) ; une autre version déclenche un avertissement.
"""

import importlib
import os
import sys
from dataclasses import dataclass, field

import addon_utils
import bpy

TESTED_VERSION = (2, 9, 0)
SOLLUMZ_MODULE_NAMES = ("sollumz", "sollumz_dev")

DWD = "sollumz_drawable_dictionary"
DRAWABLE = "sollumz_drawable"
MODEL = "sollumz_drawable_model"
LOD_HIGH = "sollumz_high"
MATERIAL_SHADER = "sollumz_material_shader"


@dataclass
class SollumzInfo:
    installed: bool = False
    enabled: bool = False
    module: str = ""
    version: tuple = ()
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    native_available: bool = False
    cwxml_available: bool = False

    @property
    def ok(self):
        return self.enabled and not self.errors

    @property
    def version_str(self):
        return ".".join(str(v) for v in self.version) if self.version else "?"


_cache = {"info": None}


def _find_module_name():
    for mod in addon_utils.modules(refresh=False):
        short = mod.__name__.rsplit(".", 1)[-1]
        if short in SOLLUMZ_MODULE_NAMES:
            return mod
    return None


def detect(refresh=False):
    if _cache["info"] is not None and not refresh:
        return _cache["info"]
    info = SollumzInfo()
    mod = _find_module_name()
    if mod is None:
        info.errors.append("Sollumz n'est pas installé. Installez Sollumz 2.9.0 (Préférences > Extensions).")
        _cache["info"] = info
        return info
    info.installed = True
    info.module = mod.__name__
    info.version = tuple(addon_utils.module_bl_info(mod).get("version", ()))
    info.enabled = info.module in bpy.context.preferences.addons
    if not info.enabled:
        info.errors.append("Sollumz est installé mais désactivé. Activez-le dans Préférences > Extensions.")
    else:
        if info.version[:2] != TESTED_VERSION[:2]:
            info.warnings.append(
                f"Sollumz {info.version_str} détecté ; Mio Chain Studio a été testé avec "
                f"{'.'.join(map(str, TESTED_VERSION))}. Vérifiez chaque étape."
            )
        if not hasattr(bpy.ops, "sollumz") or not hasattr(bpy.types.Object, "sollum_type"):
            info.errors.append("Sollumz est activé mais ses opérateurs ne sont pas enregistrés.")
        try:
            from szio.gta5 import AssetFormat, AssetTarget, AssetVersion, is_provider_available
            info.cwxml_available = is_provider_available(AssetTarget(AssetFormat.CWXML, AssetVersion.GEN8))
            info.native_available = is_provider_available(AssetTarget(AssetFormat.NATIVE, AssetVersion.GEN8))
        except Exception as exc:  # dépendance szio absente ou incompatible
            info.errors.append(f"Dépendance szio de Sollumz introuvable ou incompatible ({exc}). "
                               "Installez les dépendances depuis les préférences de Sollumz.")
        for sub in ("ydr.shader_materials", "ydr.operators.materials", "tools.meshhelper"):
            try:
                sz(sub, info)
            except Exception as exc:
                info.errors.append(f"Module Sollumz '{sub}' introuvable dans cette version ({exc}).")
    _cache["info"] = info
    return info


def sz(sub, info=None):
    info = info or detect()
    return importlib.import_module(f"{info.module}.{sub}")


def require():
    from .utils import McsError
    info = detect()
    if not info.ok:
        raise McsError(" ".join(info.errors) or "Sollumz indisponible.")
    return info


# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

def shader_filenames(prefix=""):
    try:
        mats = sz("ydr.shader_materials").shadermats
    except Exception:
        return []
    names = sorted(s.value for s in mats)
    return [n for n in names if n.startswith(prefix)] if prefix else names


def find_shader(filename):
    try:
        return sz("ydr.shader_materials").ShaderManager.find_shader(filename)
    except Exception:
        return None


def shaders_with_param(param, prefix="ped"):
    result = []
    for name in shader_filenames(prefix):
        shader = find_shader(name)
        if shader is not None and param in shader.parameter_map:
            result.append(name)
    return result


def is_sollumz_material(mat):
    return mat is not None and getattr(mat, "sollum_type", "") == MATERIAL_SHADER


def material_shader(mat):
    return mat.shader_properties.filename if is_sollumz_material(mat) else ""


def texture_nodes(mat):
    if mat is None or mat.node_tree is None:
        return []
    return [n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage"]


def shader_texture_params(filename):
    shader = find_shader(filename)
    if shader is None:
        return []
    return [p.name for p in shader.parameters
            if str(getattr(p.type, "value", p.type)).lower() == "texture" and not getattr(p, "hidden", False)]


def param_node(mat, name):
    if mat is None or mat.node_tree is None:
        return None
    node = mat.node_tree.nodes.get(name)
    return node if node is not None and node.bl_idname == "SOLLUMZ_NT_SHADER_Parameter" else None


def texture_name_of_image(image):
    """Règle de Sollumz 2.9 : nom de texture = nom du fichier image, sans extension, en minuscules."""
    if image is None or not image.filepath:
        return ""
    return os.path.splitext(bpy.path.basename(image.filepath))[0].lower()


def create_material(filename, name):
    mat = sz("ydr.shader_materials").create_shader(filename)
    mat.name = name
    return mat


def change_shader(mat, filename):
    """Change le shader d'un matériau Sollumz en conservant images et paramètres homonymes."""
    images = {n.name: (n.image, n.texture_properties.embedded) for n in texture_nodes(mat)}
    params = {}
    for n in mat.node_tree.nodes:
        if n.bl_idname == "SOLLUMZ_NT_SHADER_Parameter":
            params[n.name] = [o.default_value for o in n.outputs]
    name = mat.name
    sz("ydr.shader_materials").create_shader(filename, in_place_material=mat)
    mat.name = name
    for n in texture_nodes(mat):
        if n.name in images:
            n.image, n.texture_properties.embedded = images[n.name]
    for n in mat.node_tree.nodes:
        if n.bl_idname == "SOLLUMZ_NT_SHADER_Parameter" and n.name in params:
            old = params[n.name]
            if len(old) == len(n.outputs):
                for out, value in zip(n.outputs, old):
                    out.default_value = value


def update_mesh_attributes(obj, mat):
    """Ajoute les UV et attributs couleur exigés par le shader (fonction de Sollumz)."""
    sz("ydr.operators.materials").post_create_shader_update_object(obj, mat)


def uv_map_name(index):
    return sz("tools.meshhelper").get_uv_map_name(index)


def color_attr_name(index):
    return sz("tools.meshhelper").get_color_attr_name(index)


# ---------------------------------------------------------------------------
# Hiérarchie Drawable et LOD
# ---------------------------------------------------------------------------

LOD_LEVELS = (("sollumz_high", "High"), ("sollumz_medium", "Medium"), ("sollumz_low", "Low"),
              ("sollumz_verylow", "Very Low"))


def lod_meshes(obj):
    """{niveau: maillage} des LOD Sollumz de l'objet (None si vide ; vide si Sollumz est inactif)."""
    lods = getattr(obj, "sz_lods", None)
    if lods is None:
        return {}
    return {lvl: lods.get_lod(lvl).mesh for lvl, label in LOD_LEVELS}


def set_lods(obj, meshes):
    """Fixe les LOD : `meshes` = {niveau: maillage ou None}. Le niveau High est le maillage de l'objet."""
    obj.sollum_type = MODEL
    lods = obj.sz_lods
    for lvl, label in LOD_LEVELS:
        lods.get_lod(lvl).mesh = meshes.get(lvl)
    lods.active_lod_level = LOD_HIGH


# ---------------------------------------------------------------------------
# Import (opérateur sollumz.import_assets de la version installée)
# ---------------------------------------------------------------------------

def import_ydd_with_external_skeleton(context, ydd_path, yft_path, collection):
    """Importe un YDD avec un squelette YFT externe (mode « Saved » de Sollumz, chemin explicite).

    Retourne la liste des nouveaux objets. Paramètres vérifiés dans Sollumz 2.9.0 :
    use_custom_settings, dwd_import_external_skeleton="SAVED", dwd_import_external_skeleton_saved_path,
    split_by_group, textures_mode.
    """
    before = set(bpy.data.objects)
    directory = os.path.dirname(ydd_path) + os.sep
    with context.temp_override(collection=collection):
        result = bpy.ops.sollumz.import_assets(
            directory=directory,
            files=[{"name": os.path.basename(ydd_path)}],
            use_custom_settings=True,
            dwd_import_external_skeleton="SAVED",
            dwd_import_external_skeleton_saved_path=yft_path,
            split_by_group=False,
            textures_mode="PACK",
        )
    new = [o for o in bpy.data.objects if o not in before]
    return result, new


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_assets(context, scene, root_obj, directory, formats, versions):
    """Lance l'opérateur d'export de Sollumz sur `root_obj` uniquement, dans la scène du projet."""
    view_layer = context.view_layer if context.scene == scene else scene.view_layers[0]
    for obj in view_layer.objects:
        if obj.select_get(view_layer=view_layer):
            obj.select_set(False, view_layer=view_layer)
    selected = []
    for obj in [root_obj] + list(root_obj.children_recursive):
        if obj.name in view_layer.objects:
            obj.hide_set(False, view_layer=view_layer)
            obj.select_set(True, view_layer=view_layer)
            selected.append(obj)
    view_layer.objects.active = root_obj
    kwargs = dict(
        directory=directory,
        direct_export=True,
        use_custom_settings=True,
        limit_to_selected=True,
        exclude_skeleton=True,
        apply_transforms=False,
        target_formats=set(formats),
        target_versions=set(versions),
        export_ytds=False,
        export_ytyps=False,
        export_ymaps=False,
    )
    with context.temp_override(scene=scene, view_layer=view_layer, selected_objects=selected,
                               active_object=root_obj, object=root_obj):
        return bpy.ops.sollumz.export_assets(**kwargs)
