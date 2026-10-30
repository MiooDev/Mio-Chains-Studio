"""Propriétés du projet, enregistrées dans le .blend (scène du projet)."""

import math

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import sollumz_bridge as szb


def _poll_mesh(self, obj):
    return obj.type == "MESH"


def _poll_armature(self, obj):
    return obj.type == "ARMATURE"


def _poll_chain(self, obj):
    return obj.type in {"MESH", "EMPTY"}


def _poll_camera(self, obj):
    return obj.type == "CAMERA"


def _shader_search(self, context, edit_text):
    prefix = "" if self.show_all_shaders else "ped"
    return [n for n in szb.shader_filenames(prefix) if edit_text.lower() in n]


def _preview_transform_update(self, context):
    from . import display
    display.apply_preview_transform(self)


AXES = [
    ("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""),
    ("NEGATIVE_X", "-X", ""), ("NEGATIVE_Y", "-Y", ""), ("NEGATIVE_Z", "-Z", ""),
]

# Composants de ped (nom de fichier GTA). Seul « teef » est confirmé par votre fichier de référence.
COMPONENTS = [
    ("teef", "teef", "Accessoires / cou (composant de votre fichier de référence teef_012_u)"),
    ("accs", "accs", "Sous-haut"),
    ("jbib", "jbib", "Haut"),
    ("uppr", "uppr", "Torse / bras"),
    ("hand", "hand", "Sacs / mains"),
]


class MCS_ReportItem(bpy.types.PropertyGroup):
    severity: EnumProperty(items=[("ERROR", "Bloquant", ""), ("WARNING", "Avertissement", ""), ("INFO", "Info", "")])
    category: StringProperty()
    message: StringProperty()
    fix: StringProperty()
    object_name: StringProperty()


class MCS_DisplayItem(bpy.types.PropertyGroup):
    kind: EnumProperty(items=[("SCENE", "Scène", ""), ("COLLECTION", "Collection", ""), ("WORLD", "Monde", "")])
    use: BoolProperty(name="Charger", default=False)


def _cw_check_update(self, context):
    from .utils import get_project
    proj = get_project(context)
    proj.cw_confirm_export_count = proj.export_count


class MCS_ManualCheck(bpy.types.PropertyGroup):
    label: StringProperty()
    detail: StringProperty()
    done: BoolProperty(name="Vérifié", default=False, update=_cw_check_update,
                       description="Cochez après avoir vérifié vous-même ce point")


class MCS_Project(bpy.types.PropertyGroup):
    project_id: StringProperty(options={"HIDDEN"})

    # --- Collections et objets -------------------------------------------
    coll_root: PointerProperty(type=bpy.types.Collection)
    coll_sources: PointerProperty(type=bpy.types.Collection)
    coll_jewel: PointerProperty(type=bpy.types.Collection)
    coll_export: PointerProperty(type=bpy.types.Collection)

    text_source: PointerProperty(type=bpy.types.Object, name="Source du texte",
                                 description="Objet texte modifiable à partir duquel le pendentif est généré")
    pendant_text: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Texte",
                                  description="Maillage 3D du texte du pendentif")
    plate: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Plaque",
                           description="Plaque placée derrière le texte")
    bail: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Bélière",
                          description="Anneau qui relie le pendentif à la chaîne")
    chain: PointerProperty(type=bpy.types.Object, poll=_poll_chain, name="Chaîne",
                           description="Maillage de la chaîne (ou vide parent de plusieurs maillages)")
    pendant_pivot: PointerProperty(type=bpy.types.Object, name="Pivot du pendentif")
    jewel_root: PointerProperty(type=bpy.types.Object, name="Racine du bijou")
    ref_armature: PointerProperty(type=bpy.types.Object, poll=_poll_armature, name="Armature de référence",
                                  description="Armature du ped (ex. squelette mp_m_freemode_01 importé avec Sollumz)")
    ref_weights_mesh: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Maillage source des poids",
                                      description="Maillage de référence déjà pondéré (groupes nommés comme les os)")
    ref_model: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Modèle de référence",
                               description="Bijou vanilla ou corps du ped servant de repère de taille et de position")
    export_root: PointerProperty(type=bpy.types.Object)

    # --- Pendentif texte ---------------------------------------------------
    text: StringProperty(name="Texte", default="NO RULES", description="Texte du pendentif")
    font: PointerProperty(type=bpy.types.VectorFont, name="Police",
                          description="Police déjà chargée dans Blender")
    font_path: StringProperty(name="Fichier de police", subtype="FILE_PATH",
                              description="Charger une police .ttf/.otf (prioritaire sur la police choisie)")
    text_size: FloatProperty(name="Taille", default=0.012, min=0.001, soft_max=0.1, subtype="DISTANCE", unit="LENGTH",
                             precision=4, description="Hauteur de référence des caractères")
    letter_spacing: FloatProperty(name="Espacement des lettres", default=1.0, min=0.0, soft_max=3.0,
                                  description="1 = espacement normal de la police")
    word_spacing: FloatProperty(name="Espacement des mots", default=1.0, min=0.0, soft_max=3.0)
    thickness: FloatProperty(name="Épaisseur", default=0.002, min=0.0001, soft_max=0.02, subtype="DISTANCE",
                             unit="LENGTH", precision=4, description="Épaisseur totale du texte")
    bevel_depth: FloatProperty(name="Biseau", default=0.0002, min=0.0, soft_max=0.003, subtype="DISTANCE",
                               unit="LENGTH", precision=4, description="Arrondi des arêtes (0 = aucun)")
    bevel_resolution: IntProperty(name="Résolution du biseau", default=1, min=0, max=6,
                                  description="Segments du biseau : chaque palier ajoute beaucoup de triangles")
    curve_resolution: IntProperty(name="Finesse des courbes", default=3, min=1, max=12,
                                  description="Segments par courbe de lettre (3 suffit souvent ; 12 est lourd)")
    use_plate: BoolProperty(name="Plaque derrière le texte", default=False)
    plate_margin: FloatProperty(name="Marge", default=0.002, min=0.0, soft_max=0.02, subtype="DISTANCE",
                                unit="LENGTH", precision=4, description="Débord de la plaque autour du texte")
    plate_thickness: FloatProperty(name="Épaisseur de la plaque", default=0.0015, min=0.0001, soft_max=0.01,
                                   subtype="DISTANCE", unit="LENGTH", precision=4)
    plate_corner_radius: FloatProperty(name="Rayon des coins", default=0.0015, min=0.0, soft_max=0.01,
                                       subtype="DISTANCE", unit="LENGTH", precision=4)
    plate_corner_segments: IntProperty(name="Segments des coins", default=3, min=1, max=12)
    plate_text_inset: FloatProperty(name="Enfoncement du texte", default=0.0002, min=0.0, soft_max=0.002,
                                    subtype="DISTANCE", unit="LENGTH", precision=4,
                                    description="Le texte pénètre légèrement la plaque pour éviter un interstice")
    use_bail: BoolProperty(name="Bélière", default=True)
    bail_offset: FloatVectorProperty(name="Décalage", size=3, default=(0.0, 0.0, 0.0), subtype="TRANSLATION",
                                     unit="LENGTH", precision=4,
                                     description="Décalage par rapport au haut du pendentif (repère du texte)")
    bail_rotation: FloatVectorProperty(name="Rotation", size=3, default=(0.0, math.radians(90.0), 0.0),
                                       subtype="EULER", description="Par défaut, l'anneau laisse passer la chaîne")
    bail_radius: FloatProperty(name="Rayon", default=0.0025, min=0.0002, soft_max=0.02, subtype="DISTANCE",
                               unit="LENGTH", precision=4)
    bail_wire: FloatProperty(name="Épaisseur du fil", default=0.0006, min=0.0001, soft_max=0.005,
                             subtype="DISTANCE", unit="LENGTH", precision=4)
    bail_segments: IntProperty(name="Segments", default=16, min=6, max=64)
    bail_wire_segments: IntProperty(name="Segments du fil", default=6, min=3, max=32)
    pendant_settings_hash: StringProperty(options={"HIDDEN"})

    # --- Chaîne ------------------------------------------------------------
    chain_path: StringProperty(name="Fichier OBJ", subtype="FILE_PATH", description="Chaîne à importer (.obj)")
    chain_forward: EnumProperty(name="Avant", items=AXES, default="NEGATIVE_Z",
                                description="Axe avant du fichier OBJ (réglage de l'importateur de Blender)")
    chain_up: EnumProperty(name="Haut", items=AXES, default="Y", description="Axe haut du fichier OBJ")
    chain_scale: FloatProperty(name="Échelle", default=1.0, min=0.0001, soft_max=100.0,
                               description="Facteur d'échelle à l'import (0,01 si le fichier est en cm)")
    chain_join: BoolProperty(name="Joindre les objets importés", default=False,
                             description="Sinon, ils sont rangés sous un vide « chaîne » sans être fusionnés")

    # --- Noms ----------------------------------------------------------------
    component: EnumProperty(name="Composant", items=COMPONENTS, default="teef")
    drawable_index: IntProperty(name="Numéro", default=0, min=0, max=999)
    drawable_suffix: StringProperty(name="Suffixe du drawable", default="u",
                                    description="« u » dans votre référence teef_012_u")
    texture_variant: StringProperty(name="Variante de texture", default="a",
                                    description="Lettre de variante (« a » dans teef_diff_012_a_uni)")
    texture_suffix: StringProperty(name="Suffixe de texture", default="uni",
                                   description="« uni » dans votre référence teef_diff_012_a_uni")
    file_prefix: StringProperty(name="Préfixe de fichier", default="",
                                description="Facultatif, ajouté devant les noms de fichiers (ex. mp_m_freemode_01_monpack^)")

    # --- Matériaux -----------------------------------------------------------
    show_all_shaders: BoolProperty(name="Tous les shaders", default=False,
                                   description="Afficher aussi les shaders hors famille « ped »")
    shader_chaine: StringProperty(name="Shader chaîne", default="ped_default.sps", search=_shader_search)
    shader_texte: StringProperty(name="Shader texte", default="ped_default.sps", search=_shader_search)
    shader_plaque: StringProperty(name="Shader plaque", default="ped_default.sps", search=_shader_search)
    shader_beliere: StringProperty(name="Shader bélière", default="ped_default.sps", search=_shader_search)
    preset_name: StringProperty(name="Nom du préréglage", default="or_poli")

    # --- Atlas / DDS ---------------------------------------------------------
    use_atlas: BoolProperty(name="Utiliser l'atlas à l'export", default=False,
                            description="Les matériaux restent distincts mais leurs textures diffuses pointent vers l'atlas")
    atlas_size: EnumProperty(name="Taille", default="1024",
                             items=[(s, s, "") for s in ("256", "512", "1024", "2048", "4096")])
    atlas_padding: IntProperty(name="Marge (px)", default=8, min=0, max=64,
                               description="Bordure répétée autour de chaque tuile, contre les débordements de couleur")
    atlas_normal: BoolProperty(name="Atlas des normales", default=False,
                               description="Même disposition pour les textures BumpSampler")
    atlas_spec: BoolProperty(name="Atlas spéculaire", default=False,
                             description="Même disposition pour les textures SpecSampler")
    atlas_image: PointerProperty(type=bpy.types.Image)
    atlas_normal_image: PointerProperty(type=bpy.types.Image)
    atlas_spec_image: PointerProperty(type=bpy.types.Image)
    atlas_signature: StringProperty(options={"HIDDEN"})
    atlas_layout: StringProperty(options={"HIDDEN"})
    dds_format: EnumProperty(name="Format DDS", default="DXT5", items=[
        ("DXT1", "DXT1 / BC1", "Sans transparence, plus léger"),
        ("DXT5", "DXT5 / BC3", "Avec canal alpha (shaders cutout)"),
        ("BC7", "BC7", "Meilleure qualité, uniquement avec texconv"),
    ])
    dds_mipmaps: BoolProperty(name="Mipmaps", default=True)
    dds_path: StringProperty(name="Fichier DDS", subtype="FILE_PATH",
                             description="DDS de l'atlas (généré ou converti par un autre outil)")

    # --- Effets ----------------------------------------------------------------
    emissive_multiplier: FloatProperty(name="emissiveMultiplier", default=1.0, min=0.0, soft_max=20.0,
                                       description="Paramètre réel du shader ped_emissive (défaut Sollumz : 1)")
    use_vertex_colors: BoolProperty(name="Préparer les couleurs de sommets", default=True)
    vcol0: FloatVectorProperty(name="Color 1 (Colour0)", size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0,
                               default=(1.0, 128 / 255, 0.0, 1.0),
                               description="Valeur constante lue dans votre référence teef_012_u : 255 128 0 255")
    vcol1: FloatVectorProperty(name="Color 2 (Colour1)", size=4, subtype="COLOR_GAMMA", min=0.0, max=1.0,
                               default=(0.0, 0.0, 0.0, 0.0),
                               description="Valeur constante lue dans votre référence teef_012_u : 0 0 0 0")

    # --- Rigging ---------------------------------------------------------------
    weight_method_chain: EnumProperty(name="Chaîne", default="TRANSFER", items=[
        ("TRANSFER", "Transfert depuis la référence", "Copie les poids du maillage de référence le plus proche"),
        ("SINGLE_BONE", "Un os choisi", "Tout le maillage suit l'os que vous choisissez (rigide)"),
        ("KEEP", "Conserver l'existant", "Ne modifie pas les poids actuels"),
    ])
    weight_method_pendant: EnumProperty(name="Pendentif", default="RIGID_ATTACH", items=[
        ("RIGID_ATTACH", "Rigide, poids du point d'attache",
         "Le pendentif reprend les poids de la chaîne à l'endroit de la bélière"),
        ("TRANSFER", "Transfert depuis la référence", "Copie les poids du maillage de référence le plus proche"),
        ("SINGLE_BONE", "Un os choisi", "Tout le pendentif suit l'os choisi"),
        ("KEEP", "Conserver l'existant", "Ne modifie pas les poids actuels"),
    ])
    bone_chain: StringProperty(name="Os (chaîne)")
    bone_pendant: StringProperty(name="Os (pendentif)")
    max_influences: IntProperty(name="Influences max. par sommet", default=4, min=1, max=4,
                                description="4 = nombre d'indices d'os par sommet lus dans votre référence")
    deform_bone: StringProperty(name="Os à tester")
    deform_angle: FloatProperty(name="Angle de test", default=math.radians(25.0), subtype="ANGLE")
    deform_confirmed: BoolProperty(name="Déformation vérifiée visuellement", default=False)
    deform_confirmed_sig: StringProperty(options={"HIDDEN"})
    rig_report_sig: StringProperty(options={"HIDDEN"})
    rig_report: CollectionProperty(type=MCS_ReportItem)

    # --- Display -----------------------------------------------------------------
    display_path: StringProperty(name="Fichier du display", subtype="FILE_PATH",
                                 description="Fichier .blend de votre display de présentation")
    display_mode: EnumProperty(name="Charger", default="SCENE", items=[
        ("SCENE", "Scène complète", "Conserve rendu, monde, lumières, caméras et cadrage du display"),
        ("COLLECTIONS", "Collections choisies", "Charge seulement les collections cochées dans une nouvelle scène"),
    ])
    display_items: CollectionProperty(type=MCS_DisplayItem)
    display_scene_name: StringProperty(name="Scène du display")
    display_loaded_path: StringProperty(options={"HIDDEN"})
    display_missing: StringProperty(options={"HIDDEN"}, description="Ressources manquantes (JSON)")
    preview_scene: PointerProperty(type=bpy.types.Scene)
    preview_marker: PointerProperty(type=bpy.types.Object, name="Repère")
    preview_root: PointerProperty(type=bpy.types.Object)
    preview_anchor: EnumProperty(name="Point du bijou", default="ROOT", items=[
        ("ROOT", "Origine de la racine du bijou", "Le repère reçoit l'origine du vide racine"),
        ("TOP", "Haut du bijou", "Le repère reçoit le centre du haut de la boîte englobante"),
        ("BAIL", "Point d'attache du pendentif", "Le repère reçoit le centre de la bélière (ou le haut du pendentif)"),
    ], update=_preview_transform_update)
    preview_loc: FloatVectorProperty(name="Position", size=3, subtype="TRANSLATION", unit="LENGTH",
                                     update=_preview_transform_update)
    preview_rot: FloatVectorProperty(name="Rotation", size=3, subtype="EULER", update=_preview_transform_update)
    preview_scale: FloatProperty(name="Échelle", default=1.0, min=0.001, soft_max=100.0,
                                 update=_preview_transform_update)
    preview_keep_materials: BoolProperty(name="Garder les matériaux de l'aperçu", default=True,
                                         description="À l'actualisation, réutiliser les matériaux d'aperçu déjà modifiés")
    preview_signature: StringProperty(options={"HIDDEN"})
    wrap_target: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Surface du display",
                                 description="Surface que la chaîne de l'aperçu doit épouser")
    wrap_method: EnumProperty(name="Méthode", default="NEAREST_SURFACEPOINT", items=[
        ("NEAREST_SURFACEPOINT", "Surface la plus proche", ""),
        ("PROJECT", "Projection", ""),
        ("NEAREST_VERTEX", "Sommet le plus proche", ""),
        ("TARGET_PROJECT", "Projection sur la cible", ""),
    ])
    wrap_offset: FloatProperty(name="Distance", default=0.001, soft_min=0.0, soft_max=0.02, subtype="DISTANCE",
                               unit="LENGTH", precision=4)
    wrap_enabled: BoolProperty(options={"HIDDEN"})
    render_camera: PointerProperty(type=bpy.types.Object, poll=_poll_camera, name="Caméra")
    render_res_x: IntProperty(name="Largeur", default=1920, min=16)
    render_res_y: IntProperty(name="Hauteur", default=1080, min=16)
    render_percent: IntProperty(name="%", default=100, min=1, max=100, subtype="PERCENTAGE")
    render_dir: StringProperty(name="Dossier de sortie", default="//rendus/", subtype="DIR_PATH")
    render_mode: EnumProperty(name="Mode", default="QUICK", items=[
        ("QUICK", "Aperçu rapide", "Échantillons réduits et 50 % de la résolution, réglages restaurés ensuite"),
        ("FINAL", "Rendu final", "Réglages de rendu du display tels quels"),
    ])
    quick_samples: IntProperty(name="Échantillons (rapide)", default=16, min=1, max=512)

    # --- Export ------------------------------------------------------------------------
    export_dir: StringProperty(name="Dossier d'export", default="//export/", subtype="DIR_PATH")
    export_cwxml: BoolProperty(name="CodeWalker XML", default=True)
    export_native: BoolProperty(name="Binaire natif", default=False,
                                description="Nécessite PyMateria (Windows) dans Sollumz")
    export_gen8: BoolProperty(name="Gen8 (Legacy)", default=True,
                              description="GTA V Legacy, version sur laquelle repose FiveM")
    export_gen9: BoolProperty(name="Gen9 (Enhanced)", default=False)
    export_ytd: BoolProperty(name="Exporter le YTD", default=True,
                             description="Dictionnaire de textures Sollumz contenant le DDS diffuse")
    export_copy_sig: StringProperty(options={"HIDDEN"})
    report: CollectionProperty(type=MCS_ReportItem)
    report_sig: StringProperty(options={"HIDDEN"})
    report_count: IntProperty(options={"HIDDEN"})
    last_export_files: StringProperty(options={"HIDDEN"})
    export_count: IntProperty(options={"HIDDEN"}, description="Nombre d'exports réussis (compteur)")
    last_export_sig: StringProperty(options={"HIDDEN"})
    last_export_ok: BoolProperty(options={"HIDDEN"})

    # --- CodeWalker ------------------------------------------------------------------------
    cw_checks: CollectionProperty(type=MCS_ManualCheck)
    cw_confirm_export_count: IntProperty(options={"HIDDEN"})

    # --- Noms calculés -------------------------------------------------------------------
    def drawable_name(self):
        return f"{self.component}_{self.drawable_index:03d}_{self.drawable_suffix}".lower()

    def ydd_name(self):
        return f"{self.file_prefix}{self.drawable_name()}".lower()

    def texture_name(self):
        return f"{self.component}_diff_{self.drawable_index:03d}_{self.texture_variant}_{self.texture_suffix}".lower()

    def ytd_name(self):
        return f"{self.file_prefix}{self.texture_name()}".lower()

    def shader_for(self, role):
        return getattr(self, f"shader_{role}")


CLASSES = (MCS_ReportItem, MCS_DisplayItem, MCS_ManualCheck, MCS_Project)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mio_chain = PointerProperty(type=MCS_Project)
    bpy.types.Scene.mio_chain_source = PointerProperty(type=bpy.types.Scene,
                                                       description="Scène du projet (pour une scène d'aperçu)")


def unregister():
    del bpy.types.Scene.mio_chain_source
    del bpy.types.Scene.mio_chain
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
