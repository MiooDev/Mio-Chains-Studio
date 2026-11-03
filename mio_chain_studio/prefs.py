"""Préférences de l'addon : dossier Teef mémorisé, presets, seuils, repères de display."""

import json
import os

import bpy
from bpy.props import IntProperty, StringProperty


def addon_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def default_presets_dir():
    return bpy.utils.user_resource("CONFIG", path=os.path.join("mio_chain_studio", "presets"), create=True)


def textures_dir():
    """Dossier de configuration où l'addon garde vos textures par défaut (copie : l'original peut bouger)."""
    return bpy.utils.user_resource("CONFIG", path=os.path.join("mio_chain_studio", "textures"), create=True)


def save_user_prefs():
    """Enregistre les préférences si Blender ne le fait pas automatiquement."""
    if not bpy.context.preferences.use_preferences_save:
        try:
            bpy.ops.wm.save_userpref()
        except RuntimeError:
            pass


class MCS_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    teef_dir: StringProperty(
        name="Dossier Teef",
        description="Dossier « Teef » extrait de Teef.zip (mémorisé pour les projets suivants)",
        subtype="DIR_PATH",
    )
    presets_dir: StringProperty(
        name="Dossier des presets",
        description="Dossier des presets de matériaux (JSON). Vide = dossier de configuration de Blender",
        subtype="DIR_PATH",
    )
    tri_warning: IntProperty(
        name="Seuil d'avertissement triangles",
        description="Seuil personnel ; ce n'est pas une limite officielle de FiveM",
        default=15000, min=100,
    )
    display_markers: StringProperty(default="{}", options={"HIDDEN"})
    default_bump: StringProperty(
        name="Normal map par défaut",
        description="BumpSampler utilisé à la place de teef_normal_001.dds : mode Personnalisé sans Bump choisi, "
                    "et presets qui utilisent celle de Teef. Vide = teef_normal_001.dds",
        subtype="FILE_PATH",
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "teef_dir")
        col.prop(self, "presets_dir")
        col.label(text=f"Presets enregistrés dans : {self.presets_folder()}")
        col.prop(self, "default_bump")
        col.operator("mio_chain.default_bump_choose", icon="FILEBROWSER")
        col.prop(self, "tri_warning")
        col.label(text=f"Repères de display enregistrés : {len(self.markers())}")

    def presets_folder(self):
        path = bpy.path.abspath(self.presets_dir) if self.presets_dir else default_presets_dir()
        os.makedirs(path, exist_ok=True)
        return path

    def markers(self):
        try:
            data = json.loads(self.display_markers or "{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def save_marker(self, key, payload):
        data = self.markers()
        data[key] = payload
        self.display_markers = json.dumps(data)
