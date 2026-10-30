"""Préférences de l'addon : seuils, encodeurs DDS, repères de display enregistrés."""

import json
import os

import bpy
from bpy.props import IntProperty, StringProperty


def addon_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def default_presets_dir():
    return bpy.utils.user_resource("CONFIG", path=os.path.join("mio_chain_studio", "prereglages"), create=True)


class MCS_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    tri_warning: IntProperty(
        name="Seuil d'avertissement triangles",
        description="Seuil personnel : au-delà, un avertissement s'affiche. Ce n'est pas une limite officielle de FiveM",
        default=15000, min=100,
    )
    texture_warning: IntProperty(
        name="Seuil d'avertissement texture (px)",
        description="Côté maximal d'une texture avant avertissement. Seuil personnel, pas une limite officielle",
        default=2048, min=16,
    )
    texconv_path: StringProperty(
        name="texconv (DirectXTex)",
        description="Chemin de texconv.exe (outil Microsoft gratuit). Vide = recherche dans le PATH",
        subtype="FILE_PATH",
    )
    magick_path: StringProperty(
        name="ImageMagick",
        description="Chemin de magick (ImageMagick). Vide = recherche dans le PATH",
        subtype="FILE_PATH",
    )
    presets_dir: StringProperty(
        name="Dossier des préréglages",
        description="Dossier où sont enregistrés les préréglages de matériaux (JSON)",
        subtype="DIR_PATH",
    )
    display_markers: StringProperty(
        name="Repères de display enregistrés",
        description="Données internes (JSON) : repère de placement par fichier display",
        default="{}",
        options={"HIDDEN"},
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="Seuils d'avertissement (personnels, modifiables) :")
        col.prop(self, "tri_warning")
        col.prop(self, "texture_warning")
        col.separator()
        col.label(text="Encodeurs DDS (au moins un est nécessaire pour convertir l'atlas) :")
        col.prop(self, "texconv_path")
        col.prop(self, "magick_path")
        col.separator()
        col.prop(self, "presets_dir")
        markers = self.markers()
        col.label(text=f"Repères de display enregistrés : {len(markers)}")
        for path in list(markers)[:8]:
            col.label(text=path, icon="EMPTY_AXIS")

    # Repères enregistrés -------------------------------------------------
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

    def presets_folder(self):
        path = bpy.path.abspath(self.presets_dir) if self.presets_dir else default_presets_dir()
        os.makedirs(path, exist_ok=True)
        return path


def save_user_prefs():
    """Enregistre les préférences si l'enregistrement automatique est désactivé."""
    prefs = bpy.context.preferences
    if not prefs.use_preferences_save:
        try:
            bpy.ops.wm.save_userpref()
        except RuntimeError:
            pass
