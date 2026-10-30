"""Interface : onglet « Mio Chain » de la barre latérale de la vue 3D."""

import json
import math
import os

import bpy

from . import atlas
from . import dds
from . import effects
from . import sollumz_bridge as szb
from . import status
from .materials import component_materials, unique_materials
from .prefs import addon_prefs
from .utils import (
    ROLE_LABELS,
    ROLE_PROP,
    ROLES_ALL,
    SEVERITY_ICONS,
    STATUS_ICONS,
    component_objects,
    draw_issues,
    draw_wrapped,
    get_project,
    project_scene,
    triangle_count,
)

INSTRUCTIONS = {
    "1": "Vérifiez Sollumz, enregistrez le .blend et fixez les noms des fichiers du bijou.",
    "2": "Écrivez le texte, créez le pendentif, importez ou choisissez la chaîne, puis ajustez la position.",
    "3": "Choisissez les shaders, associez les textures, puis préparez l'atlas, le DDS et le YTD.",
    "4": "Facultatif : émissif. Préparez les couleurs de sommets exigées par les shaders ped.",
    "5": "Choisissez l'armature du ped, liez le bijou, générez les poids, vérifiez puis testez la déformation.",
    "A": "Chargez votre display dans une scène à part, placez le bijou sur son repère, puis faites le rendu.",
    "6": "Créez la copie d'export puis lancez la vérification. Corrigez toutes les erreurs bloquantes.",
    "7": "Exportez avec Sollumz : les fichiers produits sont relus et contrôlés.",
    "8": "Étapes manuelles dans CodeWalker puis FiveM. Cochez chaque point après l'avoir vérifié.",
}


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mio Chain"
    step = None

    def draw_header(self, context):
        if self.step:
            st, _ = status.compute(context, get_project(context), self.step)
            self.layout.label(text="", icon=STATUS_ICONS[st])

    def draw_status(self, context, proj, layout=None):
        layout = layout or self.layout
        st, issues = status.compute(context, proj, self.step)
        row = layout.row()
        row.label(text=f"Statut : {st}", icon=STATUS_ICONS[st])
        draw_wrapped(layout, context, INSTRUCTIONS[self.step])
        draw_issues(layout, context, issues)


def _obj_row(layout, proj, role, assign=True):
    row = layout.row(align=True)
    row.prop(proj, ROLE_PROP[role], text=ROLE_LABELS[role])
    if assign:
        row.operator("mio_chain.role_assign", text="", icon="EYEDROPPER").role = role
    obj = getattr(proj, ROLE_PROP[role])
    if obj is not None:
        row.operator("mio_chain.select_object", text="", icon="RESTRICT_SELECT_OFF").name = obj.name
        row.operator("mio_chain.role_clear", text="", icon="X").role = role


# ---------------------------------------------------------------------------

class MIO_PT_main(_Base, bpy.types.Panel):
    bl_label = "Mio Chain Studio"
    bl_idname = "MIO_PT_main"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        if context.scene != project_scene(context):
            box = layout.box()
            box.label(text="Vous êtes dans la scène d'aperçu.", icon="SCENE_DATA")
            box.operator("mio_chain.back_to_project", icon="LOOP_BACK")
        col = layout.column(align=True)
        for key, label, fn in status.STEPS:
            st, _ = status.compute(context, proj, key)
            prefix = f"{key}. " if key.isdigit() else ""
            col.label(text=f"{prefix}{label} — {st}", icon=STATUS_ICONS[st])
        info = szb.detect()
        layout.label(text=f"Sollumz : {info.version_str if info.installed else 'absent'}"
                          f"{'' if info.ok else ' (indisponible)'}",
                     icon="CHECKMARK" if info.ok else "CANCEL")


class MIO_PT_step1(_Base, bpy.types.Panel):
    bl_label = "1. Préparer le projet"
    bl_idname = "MIO_PT_step1"
    bl_options = {"DEFAULT_CLOSED"}
    step = "1"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        row = layout.row(align=True)
        row.operator("mio_chain.init_project", icon="COLLECTION_NEW")
        row.operator("mio_chain.check_deps", text="", icon="FILE_REFRESH")
        box = layout.box()
        box.label(text="Noms des fichiers", icon="SORTALPHA")
        col = box.column(align=True)
        col.prop(proj, "component")
        col.prop(proj, "drawable_index")
        col.prop(proj, "drawable_suffix")
        col.prop(proj, "texture_variant")
        col.prop(proj, "texture_suffix")
        col.prop(proj, "file_prefix")
        sub = box.column(align=True)
        sub.scale_y = 0.8
        sub.label(text=f"YDD : {proj.ydd_name()}")
        sub.label(text=f"Drawable : {proj.drawable_name()}")
        sub.label(text=f"Texture diffuse : {proj.texture_name()}")
        sub.label(text=f"YTD : {proj.ytd_name()}")
        draw_wrapped(box, context, "Motifs tirés de votre référence teef_012_u / teef_diff_012_a_uni.", icon="INFO")
        layout.prop(proj, "ref_model")
        draw_wrapped(layout, context, "Vidéo de référence inaccessible depuis l'environnement de développement : "
                                      "ses réglages n'ont pas été repris (voir docs/INFORMATIONS_MANQUANTES.md).",
                     icon="QUESTION")


class MIO_PT_step2(_Base, bpy.types.Panel):
    bl_label = "2. Créer et assembler le bijou"
    bl_idname = "MIO_PT_step2"
    bl_options = {"DEFAULT_CLOSED"}
    step = "2"

    def draw(self, context):
        self.draw_status(context, get_project(context))


class MIO_PT_step2_text(_Base, bpy.types.Panel):
    bl_label = "Pendentif texte"
    bl_parent_id = "MIO_PT_step2"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        layout.prop(proj, "text")
        col = layout.column(align=True)
        col.prop(proj, "font")
        col.prop(proj, "font_path")
        col = layout.column(align=True)
        col.prop(proj, "text_size")
        col.prop(proj, "letter_spacing")
        col.prop(proj, "word_spacing")
        col.prop(proj, "thickness")
        col.prop(proj, "bevel_depth")
        col.prop(proj, "bevel_resolution")
        col.prop(proj, "curve_resolution")
        box = layout.box()
        box.prop(proj, "use_plate")
        if proj.use_plate:
            col = box.column(align=True)
            for p in ("plate_margin", "plate_thickness", "plate_corner_radius", "plate_corner_segments", "plate_text_inset"):
                col.prop(proj, p)
        box = layout.box()
        box.prop(proj, "use_bail")
        if proj.use_bail:
            box.prop(proj, "bail_offset")
            box.prop(proj, "bail_rotation")
            col = box.column(align=True)
            for p in ("bail_radius", "bail_wire", "bail_segments", "bail_wire_segments"):
                col.prop(proj, p)
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("mio_chain.pendant_create", icon="FONT_DATA")
        op = row.operator("mio_chain.pendant_create", text="Mettre à jour le pendentif", icon="FILE_REFRESH")
        op.update_only = True
        parts = component_objects(proj, ("texte", "plaque", "beliere"))
        if parts:
            box = layout.box()
            total = 0
            for obj, role in parts:
                n = triangle_count(obj)
                total += n
                box.label(text=f"{ROLE_LABELS[role]} : {n} triangles")
            box.label(text=f"Total pendentif : {total} triangles", icon="MESH_DATA")
        if proj.text_source is not None:
            layout.operator("mio_chain.select_object", text="Sélectionner la source du texte",
                            icon="OUTLINER_OB_FONT").name = proj.text_source.name


class MIO_PT_step2_chain(_Base, bpy.types.Panel):
    bl_label = "Chaîne et composants"
    bl_parent_id = "MIO_PT_step2"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        box = layout.box()
        box.label(text="Importer une chaîne (.obj)", icon="IMPORT")
        box.prop(proj, "chain_path")
        row = box.row(align=True)
        row.prop(proj, "chain_forward")
        row.prop(proj, "chain_up")
        box.prop(proj, "chain_scale")
        box.prop(proj, "chain_join")
        box.operator("mio_chain.chain_import", icon="IMPORT")
        layout.label(text="Rôles (pipette = objet actif) :")
        for role in ROLES_ALL:
            _obj_row(layout, proj, role)
        meshes = [o for o, r in component_objects(proj, ("chaine",))]
        if meshes:
            tris = sum(triangle_count(o) for o in meshes)
            from .assembly import world_bounds
            lo, hi = world_bounds(meshes)
            d = hi - lo
            layout.label(text=f"Chaîne : {tris} triangles, {d.x * 100:.1f} × {d.y * 100:.1f} × {d.z * 100:.1f} cm",
                         icon="MESH_DATA")
        layout.prop(proj, "ref_model")


class MIO_PT_step2_assembly(_Base, bpy.types.Panel):
    bl_label = "Assemblage"
    bl_parent_id = "MIO_PT_step2"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        pivot, root = proj.pendant_pivot, proj.jewel_root
        if pivot is None or root is None:
            draw_wrapped(layout, context, "Créez le pendentif ou initialisez le projet pour obtenir les repères.")
            return
        box = layout.box()
        box.label(text="Pendentif par rapport à la chaîne", icon="EMPTY_ARROWS")
        box.prop(pivot, "location", text="Position")
        box.prop(pivot, "rotation_euler", text="Rotation")
        box.prop(pivot, "scale", text="Échelle")
        box.operator("mio_chain.pendant_snap", icon="SNAP_ON")
        box = layout.box()
        box.label(text="Bijou entier (composants solidaires)", icon="OBJECT_ORIGIN")
        box.prop(root, "location", text="Position")
        box.prop(root, "rotation_euler", text="Rotation")
        box.prop(root, "scale", text="Échelle")
        draw_wrapped(layout, context, "Les objets restent séparés : rien n'est joint avant la copie d'export.",
                     icon="INFO")


class MIO_PT_step3(_Base, bpy.types.Panel):
    bl_label = "3. Matériaux et textures"
    bl_idname = "MIO_PT_step3"
    bl_options = {"DEFAULT_CLOSED"}
    step = "3"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        col = layout.column(align=True)
        for role in ROLES_ALL:
            if getattr(proj, ROLE_PROP[role]) is not None:
                col.prop(proj, f"shader_{role}", text=ROLE_LABELS[role])
        layout.prop(proj, "show_all_shaders")
        layout.operator("mio_chain.materials_setup", icon="MATERIAL")
        for mat, role in unique_materials(proj):
            box = layout.box()
            row = box.row()
            row.label(text=f"{mat.name} — {szb.material_shader(mat)}", icon="MATERIAL")
            row.operator("mio_chain.preset_save", text="", icon="FILE_TICK").material = mat.name
            row.operator("mio_chain.preset_load", text="", icon="PRESET").material = mat.name
            used = szb.shader_texture_params(szb.material_shader(mat))
            for node in szb.texture_nodes(mat):
                if node.name not in used:
                    continue
                r = box.row(align=True)
                img = node.image
                if img is not None and img.filepath:
                    w, h = img.size
                    r.label(text=f"{node.name} : {szb.texture_name_of_image(img)} ({w}×{h})", icon="IMAGE_DATA")
                else:
                    r.label(text=f"{node.name} : —", icon="IMAGE")
                op = r.operator("mio_chain.texture_assign", text="", icon="FILEBROWSER")
                op.material, op.sampler = mat.name, node.name
                if img is not None:
                    r.prop(node.texture_properties, "embedded", text="", icon="PACKAGE")
                    op = r.operator("mio_chain.texture_clear", text="", icon="X")
                    op.material, op.sampler = mat.name, node.name
        layout.prop(proj, "preset_name")


class MIO_PT_step3_atlas(_Base, bpy.types.Panel):
    bl_label = "Atlas, DDS et YTD"
    bl_parent_id = "MIO_PT_step3"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        draw_wrapped(layout, context, "L'atlas regroupe les IMAGES dans une seule texture. Les matériaux et "
                                      "shaders restent distincts et pointent vers l'atlas à l'export.", icon="INFO")
        layout.prop(proj, "use_atlas")
        row = layout.row(align=True)
        row.prop(proj, "atlas_size")
        row.prop(proj, "atlas_padding")
        row = layout.row(align=True)
        row.prop(proj, "atlas_normal")
        row.prop(proj, "atlas_spec")
        layout.operator("mio_chain.atlas_build", icon="TEXTURE")
        if proj.atlas_layout:
            state, ok = status.cached("atlas_state", lambda: atlas.atlas_state(proj))
            layout.label(text=f"Atlas : {state}", icon="CHECKMARK" if ok else "ERROR")
            if proj.atlas_image:
                layout.label(text=f"{os.path.basename(proj.atlas_image.filepath)} "
                                  f"({proj.atlas_image.size[0]}×{proj.atlas_image.size[1]})")
        box = layout.box()
        box.label(text="Conversion DDS", icon="FILE_IMAGE")
        enc = dds.find_encoders()
        box.label(text="Encodeur : " + (", ".join(n for n, p in enc) if enc else "aucun"),
                  icon="CHECKMARK" if enc else "ERROR")
        if not enc:
            draw_wrapped(box, context, "Sans encodeur, l'image reste en PNG : convertissez-la vous-même, puis "
                                       "indiquez le .dds ci-dessous. Une simple extension .dds n'est pas une conversion.")
        row = box.row(align=True)
        row.prop(proj, "dds_format")
        row.prop(proj, "dds_mipmaps")
        box.operator("mio_chain.dds_convert", icon="EXPORT")
        if proj.use_atlas:
            row = box.row(align=True)
            row.prop(proj, "dds_path")
            row.operator("mio_chain.dds_use_file", text="", icon="VIEWZOOM")
        for kind, name, path, info, issues in status.cached("dds_status", lambda: atlas.dds_status(proj)):
            if info:
                box.label(text=f"{name}.dds : {info['format']} {info['width']}×{info['height']}, {info['mips']} mip",
                          icon="CHECKMARK" if not issues else "ERROR")
            else:
                box.label(text=f"{name} : pas de DDS", icon="RADIOBUT_OFF")
        box = layout.box()
        box.label(text=f"YTD Sollumz : {proj.ytd_name()}", icon="TEXTURE_DATA")
        box.prop(proj, "export_ytd")
        box.operator("mio_chain.ytd_prepare", icon="ADD")
        txd = szb.find_txd(project_scene(context), proj.ytd_name()) if szb.detect().ok else None
        if txd is not None:
            box.label(text="Contenu : " + (", ".join(t.name for t in txd.textures) or "vide"))


class MIO_PT_step4(_Base, bpy.types.Panel):
    bl_label = "4. Effets"
    bl_idname = "MIO_PT_step4"
    bl_options = {"DEFAULT_CLOSED"}
    step = "4"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        box = layout.box()
        box.label(text="Émissif (lumineux)", icon="LIGHT_SUN")
        shaders = effects.emissive_shaders() if szb.detect().ok else []
        draw_wrapped(box, context, "Shader ped avec le paramètre emissiveMultiplier dans Sollumz : "
                                   + (", ".join(shaders) or "aucun") + ". Il utilise aussi la map UVMap 1.")
        box.prop(proj, "emissive_multiplier")
        for role in ROLES_ALL:
            mat = effects.role_material(proj, role)
            if mat is None:
                continue
            row = box.row(align=True)
            value = effects.emissive_value(mat)
            row.label(text=f"{ROLE_LABELS[role]} : " + (f"émissif ({value:g})" if value is not None else "normal"))
            op = row.operator("mio_chain.emissive_set", text="Activer" if value is None else "Appliquer la valeur")
            op.role, op.enable = role, True
            if value is not None:
                op = row.operator("mio_chain.emissive_set", text="", icon="X")
                op.role, op.enable = role, False
        draw_wrapped(box, context, "Dans Blender, Sollumz montre une émission approximative. L'intensité réelle "
                                   "dépend du jeu (jour, nuit, éclairage) : à vérifier dans FiveM.", icon="INFO")
        box = layout.box()
        box.label(text="Couleurs de sommets", icon="VPAINT_HLT")
        box.prop(proj, "use_vertex_colors")
        col = box.column(align=True)
        col.prop(proj, "vcol0")
        col.prop(proj, "vcol1")
        draw_wrapped(box, context, "Les shaders ped lisent « Color 1 » et « Color 2 ». Valeurs par défaut lues dans "
                                   "votre référence ; leur signification exacte n'est pas documentée ici.")
        row = box.row(align=True)
        row.operator("mio_chain.vertex_colors_from_ref", icon="EYEDROPPER")
        row.operator("mio_chain.vertex_colors_apply", icon="CHECKMARK")


class MIO_PT_step5(_Base, bpy.types.Panel):
    bl_label = "5. Préparer le rigging"
    bl_idname = "MIO_PT_step5"
    bl_options = {"DEFAULT_CLOSED"}
    step = "5"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        layout.prop(proj, "ref_armature")
        layout.prop(proj, "ref_weights_mesh")
        arm = proj.ref_armature
        if arm is not None:
            layout.label(text=f"{len(arm.data.bones)} os dans {arm.name}", icon="ARMATURE_DATA")
        layout.operator("mio_chain.rig_link", icon="LINKED")
        for group, prop, bone_prop in (("CHAIN", "weight_method_chain", "bone_chain"),
                                       ("PENDANT", "weight_method_pendant", "bone_pendant")):
            box = layout.box()
            box.prop(proj, prop)
            method = getattr(proj, prop)
            if method == "SINGLE_BONE" and arm is not None:
                box.prop_search(proj, bone_prop, arm.data, "bones", text="Os")
            elif method == "TRANSFER":
                draw_wrapped(box, context, "Copie les poids de la surface la plus proche du maillage source "
                                           "(modificateur Data Transfer appliqué), puis garde 4 influences normalisées.")
            elif method == "RIGID_ATTACH":
                draw_wrapped(box, context, "Tout le pendentif reprend les poids de la chaîne au point d'attache : "
                                           "il suit la chaîne sans se déformer. Pondérez la chaîne d'abord.")
            row = box.row(align=True)
            row.operator("mio_chain.rig_weights", text="Générer", icon="MOD_VERTEX_WEIGHT").group = group
            row.operator("mio_chain.rig_restore", text="Restaurer", icon="LOOP_BACK").group = group
        layout.prop(proj, "max_influences")
        layout.operator("mio_chain.rig_check", icon="VIEWZOOM")
        if proj.rig_report:
            box = layout.box()
            for it in proj.rig_report[:12]:
                draw_wrapped(box, context, it.message, icon=SEVERITY_ICONS[it.severity])
        box = layout.box()
        box.label(text="Vérification visuelle", icon="POSE_HLT")
        if arm is not None:
            box.prop_search(proj, "deform_bone", arm.data, "bones")
        box.prop(proj, "deform_angle")
        row = box.row(align=True)
        row.operator("mio_chain.pose_test", icon="PLAY")
        row.operator("mio_chain.pose_reset", icon="LOOP_BACK")
        box.operator("mio_chain.deform_confirm", icon="CHECKBOX_HLT")


class MIO_PT_display(_Base, bpy.types.Panel):
    bl_label = "Aperçu sur mon display"
    bl_idname = "MIO_PT_display"
    bl_options = {"DEFAULT_CLOSED"}
    step = "A"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        row = layout.row(align=True)
        row.prop(proj, "display_path", text="")
        row.operator("mio_chain.display_analyse", text="", icon="VIEWZOOM")
        layout.prop(proj, "display_mode", expand=True)
        if proj.display_mode == "SCENE":
            layout.prop_search(proj, "display_scene_name", proj, "display_items", text="Scène")
        else:
            box = layout.box()
            for it in proj.display_items:
                if it.kind in {"COLLECTION", "WORLD"}:
                    box.prop(it, "use", text=f"{'Collection' if it.kind == 'COLLECTION' else 'Monde'} : {it.name}")
        row = layout.row(align=True)
        row.operator("mio_chain.display_load", icon="APPEND_BLEND")
        op = row.operator("mio_chain.display_load", text="Recharger", icon="FILE_REFRESH")
        op.force = True
        if proj.preview_scene is None:
            return
        box = layout.box()
        box.label(text="Repère de placement", icon="EMPTY_ARROWS")
        row = box.row(align=True)
        row.operator("mio_chain.marker_set", text="Objet actif").source = "ACTIVE"
        row.operator("mio_chain.marker_set", text="Curseur 3D").source = "CURSOR"
        box.operator("mio_chain.marker_save", icon="FILE_TICK")
        box.prop(proj, "preview_anchor")
        box = layout.box()
        box.label(text="Bijou sur le display", icon="OUTLINER_OB_GROUP_INSTANCE")
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("mio_chain.preview_refresh", text="Placer le bijou sur le display", icon="IMPORT")
        row.operator("mio_chain.preview_refresh", text="Actualiser l'aperçu", icon="FILE_REFRESH")
        box.prop(proj, "preview_loc")
        box.prop(proj, "preview_rot")
        box.prop(proj, "preview_scale")
        box.prop(proj, "preview_keep_materials")
        draw_wrapped(box, context, "Le placement ne déforme pas la chaîne. Pour qu'elle épouse le display, "
                                   "utilisez l'opération distincte ci-dessous (aperçu uniquement).", icon="INFO")
        sub = box.box()
        sub.prop(proj, "wrap_target")
        row = sub.row(align=True)
        row.prop(proj, "wrap_method", text="")
        row.prop(proj, "wrap_offset")
        row = sub.row(align=True)
        row.operator("mio_chain.wrap", icon="MOD_SHRINKWRAP")
        op = row.operator("mio_chain.wrap", text="", icon="X")
        op.remove = True
        box = layout.box()
        box.label(text="Rendu", icon="RENDER_STILL")
        box.prop(proj, "render_camera")
        row = box.row(align=True)
        row.prop(proj, "render_res_x")
        row.prop(proj, "render_res_y")
        box.prop(proj, "render_percent")
        box.prop(proj, "render_dir")
        box.prop(proj, "render_mode", expand=True)
        if proj.render_mode == "QUICK":
            box.prop(proj, "quick_samples")
        box.label(text=f"Moteur du display : {proj.preview_scene.render.engine}")
        row = box.row(align=True)
        row.operator("mio_chain.view_camera", icon="CAMERA_DATA")
        row.operator("mio_chain.render", icon="RENDER_STILL")


class MIO_PT_step6(_Base, bpy.types.Panel):
    bl_label = "6. Vérifier avant export"
    bl_idname = "MIO_PT_step6"
    bl_options = {"DEFAULT_CLOSED"}
    step = "6"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        layout.operator("mio_chain.export_copy", icon="DUPLICATE")
        layout.operator("mio_chain.check", icon="VIEWZOOM")
        current = None
        for it in proj.report:
            label = {"ERROR": "Erreurs bloquantes", "WARNING": "Avertissements", "INFO": "Informations"}[it.severity]
            if label != current:
                current = label
                layout.label(text=label, icon=SEVERITY_ICONS[it.severity])
                box = layout.box()
            row = box.row()
            col = row.column()
            draw_wrapped(col, context, f"[{it.category}] {it.message}")
            if it.fix:
                draw_wrapped(col, context, "→ " + it.fix)
            if it.object_name and bpy.data.objects.get(it.object_name):
                row.operator("mio_chain.select_object", text="", icon="RESTRICT_SELECT_OFF").name = it.object_name


class MIO_PT_step7(_Base, bpy.types.Panel):
    bl_label = "7. Exporter"
    bl_idname = "MIO_PT_step7"
    bl_options = {"DEFAULT_CLOSED"}
    step = "7"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        layout.prop(proj, "export_dir")
        info = szb.detect()
        row = layout.row(align=True)
        row.prop(proj, "export_cwxml")
        sub = row.row()
        sub.enabled = info.native_available
        sub.prop(proj, "export_native")
        row = layout.row(align=True)
        row.prop(proj, "export_gen8")
        row.prop(proj, "export_gen9")
        layout.prop(proj, "export_ytd")
        r = layout.row()
        r.scale_y = 1.4
        r.operator("mio_chain.export", icon="EXPORT")
        if proj.last_export_files:
            data = json.loads(proj.last_export_files)
            box = layout.box()
            box.label(text="Derniers fichiers produits :", icon="FILE")
            for line in data.get("lines", [])[:12]:
                draw_wrapped(box, context, line)
            for err in data.get("errors", []):
                draw_wrapped(box, context, err, icon="CANCEL")
            for warn in data.get("warnings", []):
                draw_wrapped(box, context, warn, icon="ERROR")
            if "CWXML" in data.get("formats", []) and "NATIVE" not in data.get("formats", []):
                draw_wrapped(box, context, "Restant : convertir les XML en .ydd / .ytd dans CodeWalker (section 8).",
                             icon="INFO")
            box.operator("mio_chain.open_folder", icon="FILE_FOLDER").path = proj.export_dir
        draw_wrapped(layout, context, "Un export Blender réussi ne valide pas le bijou dans FiveM.", icon="ERROR")


class MIO_PT_step8(_Base, bpy.types.Panel):
    bl_label = "8. Vérifier dans CodeWalker"
    bl_idname = "MIO_PT_step8"
    bl_options = {"DEFAULT_CLOSED"}
    step = "8"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        for it in proj.cw_checks:
            box = layout.box()
            box.prop(it, "done", text=it.label)
            draw_wrapped(box, context, it.detail)
        layout.operator("mio_chain.cw_reset", icon="FILE_REFRESH")


class MIO_OT_check_deps(bpy.types.Operator):
    bl_idname = "mio_chain.check_deps"
    bl_label = "Vérifier les dépendances"
    bl_description = "Détecte de nouveau Sollumz, szio et les encodeurs DDS"

    def execute(self, context):
        info = szb.detect(refresh=True)
        status.invalidate()
        enc = dds.find_encoders(refresh=True)
        msg = (f"Sollumz {info.version_str} " + ("OK" if info.ok else "indisponible : " + " ".join(info.errors))
               + f" ; encodeurs DDS : {', '.join(n for n, p in enc) or 'aucun'}.")
        self.report({"INFO" if info.ok else "ERROR"}, msg)
        return {"FINISHED"}


CLASSES = (MIO_OT_check_deps, MIO_PT_main, MIO_PT_step1, MIO_PT_step2, MIO_PT_step2_text, MIO_PT_step2_chain,
           MIO_PT_step2_assembly, MIO_PT_step3, MIO_PT_step3_atlas, MIO_PT_step4, MIO_PT_step5, MIO_PT_display,
           MIO_PT_step6, MIO_PT_step7, MIO_PT_step8)
