"""Interface : onglet « Mio Chain » de la barre latérale de la vue 3D."""

import json
import os

import bpy

from . import colors
from . import materials
from . import presets
from . import rigging
from . import sollumz_bridge as szb
from . import status
from . import svg
from . import teef
from .prefs import addon_prefs
from .utils import (
    ROLE_LABELS,
    SEVERITY_ICONS,
    STATUS_ICONS,
    draw_issues,
    draw_wrapped,
    get_project,
    part_meshes,
    project_scene,
    triangle_count,
)

INSTRUCTIONS = {
    "1": "Importez le SVG en courbes, sélectionnez-les, vérifiez leurs couches, puis préparez-les.",
    "2": "Importez votre chaîne .obj ou ajoutez une chaîne de la scène, et désignez le pendentif.",
    "3": "En Edit Mode, sélectionnez des faces, choisissez le type et le mode, puis appliquez.",
    "4": "Réglez les paramètres du matériau actif et gérez vos presets (argent, or, diamant, glow…).",
    "5": "Crée Color 1 (#FF8000, alpha 1) et Color 2 (#000000, alpha 0) en Face Corner / Byte Color.",
    "6": "Peignez vous-même les zones de glow dans Color 1. Rien n'est rempli automatiquement.",
    "7": "Crée mio_chain (copie unique du bijou, 100 % sur SKEL_Spine3) et le met à la place de SKEL_ROOT.",
    "8": "Structure teef_000_u > teef_012_u > mio_chain : noms, LOD, vérification puis export Sollumz.",
    "A": "Section séparée : votre display, une copie indépendante du bijou, la caméra et le rendu.",
}


def draw_structure(layout, proj):
    """Hiérarchie réelle : armature > drawable > mesh(es), comme dans l'Outliner."""
    root, drawable = proj.ref_root, proj.ref_drawable
    box = layout.box()
    col = box.column(align=True)
    col.label(text=f"{root.name}  ({len(root.data.bones)} os)", icon="ARMATURE_DATA")
    if drawable is not None:
        col.label(text=f"    {drawable.name}", icon="EMPTY_AXIS")
        for child in drawable.children:
            col.label(text=f"        {child.name}", icon="MESH_DATA" if child == proj.final_obj else "OUTLINER_OB_MESH")


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mio Chain"
    step = None

    def draw_header(self, context):
        if self.step:
            st, _ = status.compute(context, get_project(context), self.step)
            self.layout.label(text="", icon=STATUS_ICONS[st])

    def draw_status(self, context, proj):
        st, issues = status.compute(context, proj, self.step)
        self.layout.label(text=f"Statut : {st}", icon=STATUS_ICONS[st])
        draw_wrapped(self.layout, context, INSTRUCTIONS[self.step])
        draw_issues(self.layout, context, issues)


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
        info = szb.detect()
        layout.label(text=f"Sollumz {info.version_str if info.installed else 'absent'}"
                          + ("" if info.ok else " — indisponible"), icon="CHECKMARK" if info.ok else "CANCEL")
        for e in info.errors + info.warnings:
            draw_wrapped(layout, context, e, icon="ERROR")
        prefs = addon_prefs(context)
        box = layout.box()
        box.label(text="Dossier Teef (extrait de Teef.zip)", icon="FILE_FOLDER")
        row = box.row(align=True)
        if prefs:
            row.prop(prefs, "teef_dir", text="")
        row.operator("mio_chain.teef_check", text="", icon="VIEWZOOM")
        ok, data, issues = status.cached("teef", lambda: status.teef_status(context))
        box.label(text="Fichiers vérifiés" if ok else "Dossier Teef non valide", icon="CHECKMARK" if ok else "ERROR")
        if not ok:
            draw_issues(box, context, issues, limit=4)
        col = layout.column(align=True)
        for key, label, fn in status.STEPS:
            st, _ = status.compute(context, proj, key)
            col.label(text=(f"{key}. " if key.isdigit() else "") + f"{label} — {st}", icon=STATUS_ICONS[st])


class MIO_PT_step1(_Base, bpy.types.Panel):
    bl_label = "1. Préparation des SVG"
    bl_idname = "MIO_PT_step1"
    bl_options = {"DEFAULT_CLOSED"}
    step = "1"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        col = layout.column(align=True)
        col.label(text="Épaisseurs réelles (mètres) :")
        col.prop(proj, "thickness_1")
        col.prop(proj, "thickness_2")
        col.prop(proj, "thickness_3")
        col.prop(proj, "layer_gap")
        layout.prop(proj, "stack_axis")
        srcs, skipped = svg.sources_from_selection(context, proj)
        box = layout.box()
        box.label(text=f"Courbes sélectionnées : {len(srcs)}", icon="OUTLINER_OB_CURVE")
        row = box.row(align=True)
        row.operator("mio_chain.svg_detect", icon="SORTSIZE")
        for n in (1, 2, 3, 0):
            row.operator("mio_chain.svg_assign", text=str(n) if n else "∅").layer = n
        for src in srcs[:15]:
            r = box.row(align=True)
            black = [m.name for m in src.data.materials if m and svg.is_black(m, proj.black_threshold)]
            r.label(text=src.name + ("  (noir : matériau retiré, forme gardée)" if black else ""),
                    icon="SHADING_SOLID" if black else "CURVE_DATA")
            r.prop(src, "mio_svg_layer", text="")
        if len(srcs) > 15:
            box.label(text=f"… et {len(srcs) - 15} autre(s).")
        counts = {n: sum(1 for s in srcs if s.mio_svg_layer == n) for n in (0, 1, 2, 3)}
        box.label(text=f"Couche 1 : {counts[1]}   Couche 2 : {counts[2]}   Couche 3 : {counts[3]}   "
                       f"Non affectées : {counts[0]}")
        r = layout.row()
        r.scale_y = 1.4
        r.operator("mio_chain.svg_prepare", icon="MOD_SOLIDIFY")
        layout.operator("mio_chain.svg_show_sources", icon="HIDE_OFF")
        sub = layout.box()
        sub.label(text="Avancé")
        sub.prop(proj, "black_threshold")
        sub.prop(proj, "height_tolerance")


class MIO_PT_step2(_Base, bpy.types.Panel):
    bl_label = "2. Chaîne et composants"
    bl_idname = "MIO_PT_step2"
    bl_options = {"DEFAULT_CLOSED"}
    step = "2"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        box = layout.box()
        box.prop(proj, "chain_path")
        row = box.row(align=True)
        row.prop(proj, "chain_forward")
        row.prop(proj, "chain_up")
        box.prop(proj, "chain_scale")
        box.operator("mio_chain.chain_import", icon="IMPORT")
        row = layout.row(align=True)
        row.operator("mio_chain.part_add", text="Sélection = chaîne", icon="LINKED").role = "CHAIN"
        row.operator("mio_chain.part_add", text="Sélection = pendentif", icon="FONT_DATA").role = "PENDANT"
        box = layout.box()
        box.label(text="Composants du bijou :")
        for i, part in enumerate(proj.parts):
            r = box.row(align=True)
            obj = part.obj
            label = obj.name if obj else "(objet supprimé)"
            tris = sum(triangle_count(o.data) for o, rr in part_meshes(proj) if o == obj or (obj and o in obj.children_recursive))
            r.label(text=f"{ROLE_LABELS[part.role]} : {label} ({tris} tri.)",
                    icon="LINKED" if part.role == "CHAIN" else "FONT_DATA")
            if obj is not None:
                r.operator("mio_chain.select_object", text="", icon="RESTRICT_SELECT_OFF").name = obj.name
            r.operator("mio_chain.part_remove", text="", icon="X").index = i


class MIO_PT_step3(_Base, bpy.types.Panel):
    bl_label = "3. Matériaux sur les faces sélectionnées"
    bl_idname = "MIO_PT_step3"
    bl_options = {"DEFAULT_CLOSED"}
    step = "3"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        layout.prop(proj, "mat_kind", expand=True)
        shader = proj.shader_for_kind()
        layout.label(text=f"Shader Sollumz : {shader}", icon="SHADING_RENDERED")
        layout.prop(proj, "mat_mode", expand=True)
        box = layout.box()
        if proj.mat_mode == "PRESET":
            box.prop(proj, "preset_name")
            if proj.preset_name:
                try:
                    data = presets.load(proj.preset_name)
                    complete, missing, absent = presets.status(data)
                    box.label(text=f"Shader du preset : {data['shader']}",
                              icon="CHECKMARK" if data["shader"] == shader else "ERROR")
                    box.label(text="Preset complet" if complete else "Preset incomplet (voir étape 4)",
                              icon="CHECKMARK" if complete else "ERROR")
                except Exception as exc:
                    draw_wrapped(box, context, str(exc), icon="ERROR")
        else:
            box.prop(proj, "diffuse_path")
            box.prop(proj, "diffuse_embedded")
            box.prop(proj, "bump_path")
            box.prop(proj, "spec_path")
            for label, path in (("Bump", proj.bump_path or teef.path_of("bump")),
                                ("Spec", proj.spec_path or teef.path_of("spec"))):
                exists = bool(path) and os.path.isfile(bpy.path.abspath(path))
                box.label(text=f"{label} : {os.path.basename(path) if path else 'dossier Teef non défini'}",
                          icon="CHECKMARK" if exists else "ERROR")
        box.label(text="Bump et Spec : Embedded ; Bump en Non-Color (forcé).", icon="INFO")
        col = layout.box().column(align=True)
        col.label(text="Cube Projection (faces sélectionnées)")
        col.prop(proj, "cube_size")
        col.prop(proj, "cube_correct_aspect")
        col.prop(proj, "cube_clip_to_bounds")
        col.prop(proj, "cube_scale_to_bounds")
        r = layout.row()
        r.scale_y = 1.4
        r.enabled = context.mode == "EDIT_MESH"
        r.operator("mio_chain.apply_faces", icon="MATERIAL")
        if context.mode != "EDIT_MESH":
            layout.label(text="Passez en Edit Mode et sélectionnez des faces.", icon="EDITMODE_HLT")
        sub = layout.box()
        sub.label(text="Correspondance des choix (avancé)")
        sub.prop(proj, "shader_ped")
        sub.prop(proj, "shader_emissive")


class MIO_PT_step4(_Base, bpy.types.Panel):
    bl_label = "4. Value Parameters et presets"
    bl_idname = "MIO_PT_step4"
    bl_options = {"DEFAULT_CLOSED"}
    step = "4"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        obj = context.active_object
        mat = obj.active_material if obj else None
        box = layout.box()
        if not szb.is_sollumz_material(mat):
            box.label(text="Matériau actif : aucun matériau Sollumz.", icon="INFO")
        else:
            box.label(text=f"{mat.name} — {szb.material_shader(mat)}", icon="MATERIAL")
            for name, node in materials.value_parameters(mat):
                col = box.column(align=True)
                col.label(text=name)
                row = col.row(align=True)
                for out in node.outputs:
                    row.prop(out, "default_value", text=out.name)
            for node in szb.texture_nodes(mat):
                if node.name not in presets.SAMPLERS:
                    continue
                r = box.row(align=True)
                img = node.image
                r.label(text=f"{node.name} : {os.path.basename(img.filepath) if img and img.filepath else '—'}")
                r.prop(node.texture_properties, "embedded", text="Embedded")
                if img is not None:
                    r.prop(img.colorspace_settings, "name", text="")
            box.operator("mio_chain.params_base", icon="LOOP_BACK")
        draw_wrapped(layout, context, "Mode Personnalisé : les nouveaux matériaux reçoivent ces valeurs de base "
                                      "(specularIntensityMult et specularFalloffMult 1997, specularFresnel 0,45, "
                                      "bumpiness 1,3, emissiveMultiplier 1).", icon="INFO")
        box = layout.box()
        box.label(text="Presets (enregistrés dans la configuration de Blender)", icon="PRESET")
        box.prop(proj, "preset_name")
        if proj.preset_name:
            try:
                complete, missing, absent = presets.status(presets.load(proj.preset_name))
                box.label(text="Complet" if complete else "Incomplet", icon="CHECKMARK" if complete else "ERROR")
                for sampler in absent:
                    r = box.row()
                    r.label(text=f"{sampler} : non défini", icon="ERROR")
                    r.operator("mio_chain.preset_relocate", text="Choisir").sampler = sampler
                for sampler, path in missing:
                    r = box.row()
                    r.label(text=f"{sampler} introuvable : {os.path.basename(path)}", icon="ERROR")
                    r.operator("mio_chain.preset_relocate", text="Relocaliser").sampler = sampler
            except Exception as exc:
                draw_wrapped(box, context, str(exc), icon="ERROR")
        row = box.row(align=True)
        row.operator("mio_chain.preset_apply", icon="CHECKMARK")
        row.operator("mio_chain.preset_duplicate", text="Dupliquer", icon="DUPLICATE")
        row.operator("mio_chain.preset_delete", text="Supprimer", icon="TRASH")
        box.prop(proj, "new_preset_name")
        box.operator("mio_chain.preset_save", icon="FILE_TICK")


class MIO_PT_step5(_Base, bpy.types.Panel):
    bl_label = "5. Color Attributes"
    bl_idname = "MIO_PT_step5"
    bl_options = {"DEFAULT_CLOSED"}
    step = "5"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        layout.prop(proj, "color_targets", expand=True)
        layout.label(text="Color 1 : #FF8000, alpha 1 — Color 2 : #000000, alpha 0")
        draw_wrapped(layout, context, "Ce bouton efface les couleurs peintes de Color 1 et Color 2 "
                                      "(confirmation demandée). Les autres attributs sont conservés.", icon="ERROR")
        r = layout.row()
        r.scale_y = 1.3
        r.operator("mio_chain.colors_configure", icon="COLOR")


class MIO_PT_step6(_Base, bpy.types.Panel):
    bl_label = "6. Note pour le glow"
    bl_idname = "MIO_PT_step6"
    bl_options = {"DEFAULT_CLOSED"}
    step = "6"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        if status.uses_glow(proj):
            box = layout.box()
            draw_wrapped(box, context, colors.GLOW_NOTE, icon="LIGHT_SUN")
            draw_wrapped(box, context, colors.SHORTCUT_NOTE, icon="INFO")
            layout.operator("mio_chain.glow_paint_mode", icon="VPAINT_HLT")
            obj = context.active_object
            if obj is not None and obj.type == "MESH":
                layout.prop(obj.data, "use_paint_mask", text="Masque de sélection des faces")
            draw_wrapped(layout, context, "Ne relancez pas l'étape 5 après la peinture : elle effacerait votre travail.",
                         icon="ERROR")
            layout.prop(proj, "glow_painted")
        else:
            layout.label(text="Choisissez « Ped Emissive » à l'étape 3 pour afficher le rappel.")


class MIO_PT_step7(_Base, bpy.types.Panel):
    bl_label = "7. Rigging sur SKEL_Spine3"
    bl_idname = "MIO_PT_step7"
    bl_options = {"DEFAULT_CLOSED"}
    step = "7"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        if proj.ref_root is None:
            layout.operator("mio_chain.teef_load", icon="IMPORT")
        else:
            draw_structure(layout, proj)
        r = layout.row()
        r.scale_y = 1.4
        r.operator("mio_chain.rig_spine3", icon="GROUP_VERTEX")
        final = proj.final_obj
        if final is not None:
            from .export import final_placed
            where = (f"sous {final.parent.name} (structure d'export)" if final_placed(proj)
                     else "hors structure : cliquez « Placer mio_chain dans la structure »")
            layout.label(text=f"{final.name} : {where}", icon="MESH_DATA")
            layout.label(text=f"{len(final.data.vertices)} sommets, {triangle_count(final.data)} triangles")
            layout.operator("mio_chain.weight_paint", icon="WPAINT_HLT")


class MIO_PT_step8(_Base, bpy.types.Panel):
    bl_label = "8. Structure d'export et export"
    bl_idname = "MIO_PT_step8"
    bl_options = {"DEFAULT_CLOSED"}
    step = "8"

    def draw(self, context):
        layout = self.layout
        proj = get_project(context)
        self.draw_status(context, proj)
        row = layout.row(align=True)
        row.operator("mio_chain.teef_load", icon="IMPORT")
        op = row.operator("mio_chain.teef_load", text="", icon="FILE_REFRESH")
        op.force = True
        if proj.ref_root is not None:
            draw_structure(layout, proj)
        box = layout.box()
        box.prop(proj, "output_name")
        box.prop(proj, "drawable_name")
        box.prop(proj, "lod_mode")
        if proj.ref_root is not None:
            from .export import exported_lods, final_placed
            if final_placed(proj):
                box.label(text="LOD exportés : " + ", ".join(exported_lods(proj.final_obj)), icon="CHECKMARK")
            else:
                box.prop(proj, "export_target")
        r = box.row()
        r.scale_y = 1.3
        r.operator("mio_chain.export_place", icon="UV_SYNC_SELECT")
        layout.operator("mio_chain.export_check", icon="VIEWZOOM")
        current = None
        for it in proj.report:
            label = {"ERROR": "Erreurs bloquantes", "WARNING": "Avertissements", "INFO": "Informations"}[it.severity]
            if label != current:
                current = label
                layout.label(text=label, icon=SEVERITY_ICONS[it.severity])
                rep = layout.box()
            draw_wrapped(rep, context, f"[{it.category}] {it.message}" + (f" → {it.fix}" if it.fix else ""))
        box = layout.box()
        box.prop(proj, "export_dir")
        info = szb.detect()
        row = box.row(align=True)
        row.prop(proj, "export_cwxml")
        sub = row.row()
        sub.enabled = info.native_available
        sub.prop(proj, "export_native")
        row = box.row(align=True)
        row.prop(proj, "export_gen8")
        row.prop(proj, "export_gen9")
        r = box.row()
        r.scale_y = 1.4
        r.operator("mio_chain.export", icon="EXPORT")
        if proj.last_export:
            data = json.loads(proj.last_export)
            res = layout.box()
            res.label(text="Dernier export :", icon="FILE")
            for line in data.get("lines", [])[:10]:
                draw_wrapped(res, context, line)
            for err in data.get("errors", []):
                draw_wrapped(res, context, err, icon="CANCEL")
            if data.get("formats") == ["CWXML"]:
                draw_wrapped(res, context, "Restant : convertir le XML en .ydd dans CodeWalker.", icon="INFO")
            res.operator("mio_chain.open_folder", icon="FILE_FOLDER").path = proj.export_dir
        draw_wrapped(layout, context, "Un export Blender réussi ne valide pas le bijou dans FiveM.", icon="ERROR")


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
        box.label(text="Repère", icon="EMPTY_ARROWS")
        row = box.row(align=True)
        row.operator("mio_chain.marker_set", text="Objet actif").source = "ACTIVE"
        row.operator("mio_chain.marker_set", text="Curseur 3D").source = "CURSOR"
        box.operator("mio_chain.marker_save", icon="FILE_TICK")
        box.prop(proj, "preview_anchor")
        box.prop(proj, "preview_loc")
        box.prop(proj, "preview_rot")
        box.prop(proj, "preview_scale")
        box.prop(proj, "preview_keep_materials")
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("mio_chain.preview_refresh", text="Placer le bijou", icon="IMPORT")
        row.operator("mio_chain.preview_refresh", text="Actualiser la copie", icon="FILE_REFRESH")
        box = layout.box()
        box.prop(proj, "render_camera")
        row = box.row(align=True)
        row.prop(proj, "render_res_x")
        row.prop(proj, "render_res_y")
        box.prop(proj, "render_percent")
        box.prop(proj, "render_dir")
        box.prop(proj, "render_mode", expand=True)
        if proj.render_mode == "QUICK":
            box.prop(proj, "quick_samples")
        row = box.row(align=True)
        row.operator("mio_chain.view_camera", icon="CAMERA_DATA")
        row.operator("mio_chain.render", icon="RENDER_STILL")


CLASSES = (MIO_PT_main, MIO_PT_step1, MIO_PT_step2, MIO_PT_step3, MIO_PT_step4, MIO_PT_step5, MIO_PT_step6,
           MIO_PT_step7, MIO_PT_step8, MIO_PT_display)
