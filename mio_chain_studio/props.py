"""Propriétés du projet (enregistrées dans le .blend) et propriété de couche SVG par objet."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
    FloatVectorProperty,
)

from . import sollumz_bridge as szb


def _poll_mesh(self, obj):
    return obj.type == "MESH"


def _poll_camera(self, obj):
    return obj.type == "CAMERA"


def _poll_export_mesh(self, obj):
    """Seuls les maillages de la copie d'export sont proposés comme mesh à remplacer."""
    root = self.export_root
    return obj.type == "MESH" and root is not None and obj in root.children_recursive


def _shader_search(self, context, edit_text):
    return [n for n in szb.shader_filenames("ped") if edit_text.lower() in n]


def _preset_search(self, context, edit_text):
    from . import presets
    return [n for n in presets.names() if edit_text.lower() in n.lower()]


def _preview_update(self, context):
    from . import display
    display.apply_preview_transform(self, context)


AXES = [("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""),
        ("NEGATIVE_X", "-X", ""), ("NEGATIVE_Y", "-Y", ""), ("NEGATIVE_Z", "-Z", "")]
STACK_AXES = [("POS_Z", "+Z", "Plan XY, empilement vers le haut"), ("NEG_Z", "−Z", ""),
              ("POS_Y", "+Y", "Plan XZ"), ("NEG_Y", "−Y", "Plan XZ, vers l'avant (−Y)"),
              ("POS_X", "+X", "Plan YZ"), ("NEG_X", "−X", "")]


class MCS_Part(bpy.types.PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object, name="Objet")
    role: EnumProperty(name="Rôle", items=[("CHAIN", "Chaîne", ""), ("PENDANT", "Pendentif", "")])


class MCS_ReportItem(bpy.types.PropertyGroup):
    severity: EnumProperty(items=[("ERROR", "Bloquant", ""), ("WARNING", "Avertissement", ""), ("INFO", "Info", "")])
    category: StringProperty()
    message: StringProperty()
    fix: StringProperty()
    object_name: StringProperty()


class MCS_DisplayItem(bpy.types.PropertyGroup):
    kind: EnumProperty(items=[("SCENE", "Scène", ""), ("COLLECTION", "Collection", ""), ("WORLD", "Monde", "")])
    use: BoolProperty(name="Charger", default=False)


class MCS_Project(bpy.types.PropertyGroup):
    project_id: StringProperty(options={"HIDDEN"})

    # --- 1. SVG -------------------------------------------------------------------
    thickness_1: FloatProperty(name="Couche 1", default=0.05, min=0.0001, soft_max=1.0, precision=4,
                               subtype="DISTANCE", unit="LENGTH",
                               description="Épaisseur réelle de la couche 1 (la plus proche du sol), en mètres")
    thickness_2: FloatProperty(name="Couche 2", default=0.025, min=0.0001, soft_max=1.0, precision=4,
                               subtype="DISTANCE", unit="LENGTH", description="Épaisseur réelle de la couche 2")
    thickness_3: FloatProperty(name="Couche 3", default=0.015, min=0.0001, soft_max=1.0, precision=4,
                               subtype="DISTANCE", unit="LENGTH", description="Épaisseur réelle de la couche 3")
    layer_gap: FloatProperty(name="Espace entre couches", default=0.0, min=0.0, soft_max=0.01, precision=4,
                             subtype="DISTANCE", unit="LENGTH", description="0 = les couches se touchent")
    stack_axis: EnumProperty(name="Direction d'empilement", items=STACK_AXES, default="POS_Z")
    black_threshold: FloatProperty(name="Seuil du noir", default=0.02, min=0.0, max=0.5,
                                   description="Composante sRGB maximale pour qu'un matériau soit considéré noir")
    height_tolerance: FloatProperty(name="Tolérance de hauteur", default=0.0001, min=0.0, precision=5,
                                    subtype="DISTANCE", unit="LENGTH",
                                    description="Écart en dessous duquel deux courbes sont à la même hauteur")
    svg_signature: StringProperty(options={"HIDDEN"})
    svg_report: StringProperty(options={"HIDDEN"})

    # --- 2. Composants ------------------------------------------------------------------
    parts: CollectionProperty(type=MCS_Part)
    parts_index: IntProperty()
    chain_path: StringProperty(name="Fichier OBJ", subtype="FILE_PATH", description="Chaîne à importer (.obj)")
    chain_forward: EnumProperty(name="Avant", items=AXES, default="NEGATIVE_Z",
                                description="Axe avant du fichier (réglage de l'importateur OBJ de Blender)")
    chain_up: EnumProperty(name="Haut", items=AXES, default="Y", description="Axe haut du fichier")
    chain_scale: FloatProperty(name="Échelle", default=1.0, min=0.0001, soft_max=100.0,
                               description="0,01 si le fichier est en centimètres")

    # --- 3. Matériaux -------------------------------------------------------------------
    mat_kind: EnumProperty(name="Type", default="PED", items=[
        ("PED", "Ped — sans glow", "Shader ped sans émission"),
        ("EMISSIVE", "Ped Emissive — avec glow", "Shader ped émissif (emissiveMultiplier)"),
    ])
    mat_mode: EnumProperty(name="Mode", default="CUSTOM", items=[
        ("PRESET", "Preset", "Shader, textures et paramètres viennent d'un preset enregistré"),
        ("CUSTOM", "Personnalisé", "Vous choisissez les textures"),
    ])
    shader_ped: StringProperty(name="Shader « Ped »", default="ped.sps", search=_shader_search,
                               description="Nom technique Sollumz associé à « Ped — sans glow »")
    shader_emissive: StringProperty(name="Shader « Ped Emissive »", default="ped_emissive.sps", search=_shader_search,
                                    description="Nom technique Sollumz associé à « Ped Emissive — avec glow »")
    preset_name: StringProperty(name="Preset", search=_preset_search,
                                description="Preset utilisé en mode Preset et par les boutons de l'étape 4")
    diffuse_path: StringProperty(name="DiffuseSampler", subtype="FILE_PATH",
                                 description="Texture diffuse (couleur) de votre bijou")
    bump_path: StringProperty(name="BumpSampler", subtype="FILE_PATH",
                              description="Vide = teef_normal_001.dds du dossier Teef")
    spec_path: StringProperty(name="SpecSampler", subtype="FILE_PATH",
                              description="Vide = teef_spec_000.dds du dossier Teef")
    diffuse_embedded: BoolProperty(name="Diffuse intégrée (Embedded)", default=False,
                                   description="Intégrer la texture diffuse au YDD (DDS obligatoire)")
    cube_size: FloatProperty(name="Taille du cube", default=1.0, min=0.0001, soft_max=10.0,
                             description="Taille du cube de projection (Cube Projection)")
    cube_correct_aspect: BoolProperty(name="Corriger l'aspect", default=True)
    cube_clip_to_bounds: BoolProperty(name="Limiter aux bords", default=False)
    cube_scale_to_bounds: BoolProperty(name="Ajuster aux bords", default=False)

    # --- 4. Presets ---------------------------------------------------------------------
    new_preset_name: StringProperty(name="Nom", default="argent")

    # --- 5. Color Attributes --------------------------------------------------------------
    color_targets: EnumProperty(name="Cibles", default="PARTS", items=[
        ("PARTS", "Composants du bijou", "Chaîne et pendentif désignés à l'étape 2"),
        ("SELECTED", "Objets sélectionnés", "Maillages actuellement sélectionnés"),
    ])
    glow_painted: BoolProperty(name="Zones de glow peintes et vérifiées", default=False,
                               description="À cocher vous-même après la peinture de Color 1")

    # --- 7. Rigging ---------------------------------------------------------------------
    final_obj: PointerProperty(type=bpy.types.Object, poll=_poll_mesh, name="Mesh final")
    final_signature: StringProperty(options={"HIDDEN"})

    # --- Références Teef -------------------------------------------------------------------
    teef_loaded_dir: StringProperty(options={"HIDDEN"})
    ref_root: PointerProperty(type=bpy.types.Object)
    ref_drawable: PointerProperty(type=bpy.types.Object)
    ref_model: PointerProperty(type=bpy.types.Object)

    # --- 8. Export ----------------------------------------------------------------------
    export_root: PointerProperty(type=bpy.types.Object)
    export_drawable: PointerProperty(type=bpy.types.Object)
    export_target: PointerProperty(type=bpy.types.Object, poll=_poll_export_mesh, name="Mesh à remplacer",
                                   description="Mesh de référence de la copie d'export (affiché « SKEL_ROOT » après import)")
    output_name: StringProperty(name="Nom du fichier YDD", default="teef_000_u",
                                description="Nom du fichier exporté (sans extension)")
    drawable_name: StringProperty(name="Nom du drawable", default="teef_000_u",
                                  description="Nom interne du drawable (la référence utilise teef_012_u)")
    lod_mode: EnumProperty(name="LOD", default="HIGH_ONLY", items=[
        ("HIGH_ONLY", "High uniquement", "Medium et Low vides : rien de l'ancienne chaîne n'y reste"),
        ("DUPLICATE", "High copié en Medium et Low", "Même maillage sur les trois niveaux (non optimisé)"),
    ])
    export_dir: StringProperty(name="Dossier d'export", default="//export/", subtype="DIR_PATH")
    export_cwxml: BoolProperty(name="CodeWalker XML", default=True)
    export_native: BoolProperty(name="Binaire natif", default=False, description="Nécessite PyMateria dans Sollumz")
    export_gen8: BoolProperty(name="Gen8 (Legacy)", default=True)
    export_gen9: BoolProperty(name="Gen9 (Enhanced)", default=False)
    replaced_signature: StringProperty(options={"HIDDEN"})
    report: CollectionProperty(type=MCS_ReportItem)
    report_sig: StringProperty(options={"HIDDEN"})
    report_count: IntProperty(options={"HIDDEN"})
    export_count: IntProperty(options={"HIDDEN"})
    last_export: StringProperty(options={"HIDDEN"})
    last_export_sig: StringProperty(options={"HIDDEN"})
    last_export_ok: BoolProperty(options={"HIDDEN"})

    # --- Aperçu sur mon display ------------------------------------------------------------------
    display_path: StringProperty(name="Fichier du display", subtype="FILE_PATH",
                                 description="Fichier .blend de votre display (non inclus dans Teef.zip)")
    display_mode: EnumProperty(name="Charger", default="SCENE", items=[
        ("SCENE", "Scène complète", "Conserve rendu, monde, lumières, caméras et cadrage"),
        ("COLLECTIONS", "Collections choisies", "Charge seulement les collections cochées"),
    ])
    display_items: CollectionProperty(type=MCS_DisplayItem)
    display_scene_name: StringProperty(name="Scène du display")
    display_loaded_path: StringProperty(options={"HIDDEN"})
    display_missing: StringProperty(options={"HIDDEN"})
    preview_scene: PointerProperty(type=bpy.types.Scene)
    preview_marker: PointerProperty(type=bpy.types.Object, name="Repère")
    preview_root: PointerProperty(type=bpy.types.Object)
    preview_anchor: EnumProperty(name="Point du bijou", default="CENTER", update=_preview_update, items=[
        ("CENTER", "Centre du bijou", "Le centre de la boîte englobante est posé sur le repère"),
        ("TOP", "Haut du bijou", "Le haut (centre) de la boîte englobante est posé sur le repère"),
    ])
    preview_loc: FloatVectorProperty(name="Position", size=3, subtype="TRANSLATION", unit="LENGTH",
                                     update=_preview_update)
    preview_rot: FloatVectorProperty(name="Rotation", size=3, subtype="EULER", update=_preview_update)
    preview_scale: FloatProperty(name="Échelle", default=1.0, min=0.001, soft_max=100.0, update=_preview_update)
    preview_keep_materials: BoolProperty(name="Garder les matériaux de l'aperçu", default=True,
                                         description="À l'actualisation, réutiliser les matériaux d'aperçu déjà modifiés")
    preview_signature: StringProperty(options={"HIDDEN"})
    render_camera: PointerProperty(type=bpy.types.Object, poll=_poll_camera, name="Caméra")
    render_res_x: IntProperty(name="Largeur", default=1920, min=16)
    render_res_y: IntProperty(name="Hauteur", default=1080, min=16)
    render_percent: IntProperty(name="%", default=100, min=1, max=100, subtype="PERCENTAGE")
    render_dir: StringProperty(name="Dossier de sortie", default="//rendus/", subtype="DIR_PATH")
    render_mode: EnumProperty(name="Mode", default="QUICK", items=[
        ("QUICK", "Aperçu rapide", "Échantillons réduits et 50 % de la résolution, réglages restaurés"),
        ("FINAL", "Rendu final", "Réglages de rendu du display tels quels"),
    ])
    quick_samples: IntProperty(name="Échantillons (rapide)", default=16, min=1, max=512)

    def shader_for_kind(self, kind=None):
        return self.shader_emissive if (kind or self.mat_kind) == "EMISSIVE" else self.shader_ped


CLASSES = (MCS_Part, MCS_ReportItem, MCS_DisplayItem, MCS_Project)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mio_chain = PointerProperty(type=MCS_Project)
    bpy.types.Scene.mio_chain_source = PointerProperty(type=bpy.types.Scene)
    bpy.types.Object.mio_svg_layer = IntProperty(
        name="Couche", min=0, max=3, default=0,
        description="Couche SVG de cette courbe (1 = la plus proche du sol, 0 = non affectée)")


def unregister():
    del bpy.types.Object.mio_svg_layer
    del bpy.types.Scene.mio_chain_source
    del bpy.types.Scene.mio_chain
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
