"""Étapes 5 et 6 : Color Attributes attendus par Sollumz et préparation de la peinture du glow.

Noms vérifiés dans Sollumz 2.9.0 (tools.meshhelper.get_color_attr_name) : indice 0 → « Color 1 »
(Colour0 à l'export), indice 1 → « Color 2 » (Colour1). Les octets d'un attribut Byte Color sont en sRGB :
on écrit donc color_srgb, ce qui donne exactement #FF8000 et #000000 dans l'interface de Blender.
"""

import bpy
import numpy as np

from . import sollumz_bridge as szb
from .utils import McsError, get_project, part_meshes

TARGETS = (
    # (indice Sollumz, RGB sRGB 0-255, alpha 0-1)
    (0, (0xFF, 0x80, 0x00), 1.0),
    (1, (0x00, 0x00, 0x00), 0.0),
)
GLOW_NOTE = (
    "Pour préparer les zones de glow :\n"
    "1. Activer Color 1 dans les Color Attributes.\n"
    "2. Passer en Vertex Paint.\n"
    "3. Mettre la couleur principale du pinceau sur #FFBAFF et la couleur secondaire sur noir.\n"
    "4. Revenir en Edit Mode et sélectionner les faces qui doivent glow.\n"
    "5. Revenir en Vertex Paint, activer le masque de sélection des faces si nécessaire, "
    "puis utiliser Ctrl + X pour remplir la sélection."
)
SHORTCUT_NOTE = ("Vérifié dans le keymap par défaut de Blender 5.2 : en Vertex Paint, Ctrl + X lance "
                 "« Set Vertex Colors » (paint.vertex_color_set). Si votre keymap diffère, utilisez le menu "
                 "Paint ▸ Set Vertex Colors.")


def target_bytes(index):
    for idx, rgb, alpha in TARGETS:
        if idx == index:
            return np.array(list(rgb) + [round(alpha * 255)], dtype=np.int32)
    raise KeyError(index)


def target_objects(context, proj):
    if proj.color_targets == "SELECTED":
        objs = [o for o in context.selected_objects if o.type == "MESH"]
    else:
        objs = [o for o, r in part_meshes(proj)]
    if not objs:
        raise McsError("Aucun maillage ciblé : désignez les composants (étape 2) ou sélectionnez des maillages.")
    return objs


def read_bytes(attr):
    vals = np.empty(len(attr.data) * 4, dtype=np.float32)
    attr.data.foreach_get("color_srgb", vals)
    return np.round(vals.reshape(-1, 4) * 255).astype(np.int32)


def existing_paint(objs):
    """Objets dont un attribut concerné contient déjà des couleurs différentes de la valeur cible (peinture)."""
    painted = []
    for obj in objs:
        for idx, rgb, alpha in TARGETS:
            attr = obj.data.color_attributes.get(szb.color_attr_name(idx))
            if attr is None or attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR" or not len(attr.data):
                continue
            if not (read_bytes(attr) == target_bytes(idx)).all():
                painted.append(f"{obj.name} › {attr.name}")
    return painted


def configure(objs):
    """Crée ou remplit Color 1 et Color 2 ; seul un attribut de mauvais domaine ou type est remplacé."""
    replaced = []
    for obj in objs:
        me = obj.data
        for idx, rgb, alpha in TARGETS:
            name = szb.color_attr_name(idx)
            attr = me.color_attributes.get(name)
            if attr is not None and (attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR"):
                replaced.append(f"{obj.name} › {name} ({attr.domain}/{attr.data_type})")
                me.color_attributes.remove(attr)
                attr = None
            if attr is None:
                attr = me.color_attributes.new(name, "BYTE_COLOR", "CORNER")
            value = np.array([c / 255 for c in rgb] + [alpha], dtype=np.float32)
            attr.data.foreach_set("color_srgb", np.tile(value, len(attr.data)))
    return replaced


def issues_for(objs):
    """Contrôle domaine, type et présence ; les valeurs peintes (glow) ne sont pas une erreur."""
    issues = []
    for obj in objs:
        for idx, rgb, alpha in TARGETS:
            name = szb.color_attr_name(idx)
            attr = obj.data.color_attributes.get(name)
            if attr is None:
                issues.append(("ERROR", f"{obj.name} : « {name} » absent.", "Cliquez « Configurer les Color Attributes »."))
            elif attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR":
                issues.append(("ERROR", f"{obj.name} : « {name} » en {attr.domain}/{attr.data_type} au lieu de "
                                        "Face Corner / Byte Color.", "Cliquez « Configurer les Color Attributes »."))
    return issues


def verify_exact(objs):
    """Après configuration : valeurs exactes partout."""
    problems = []
    for obj in objs:
        for idx, rgb, alpha in TARGETS:
            attr = obj.data.color_attributes.get(szb.color_attr_name(idx))
            if attr is None or not (read_bytes(attr) == target_bytes(idx)).all():
                problems.append(f"{obj.name} › {szb.color_attr_name(idx)}")
    return problems


class MIO_OT_colors_configure(bpy.types.Operator):
    bl_idname = "mio_chain.colors_configure"
    bl_label = "Configurer les Color Attributes"
    bl_description = ("Color 1 = #FF8000 alpha 1, Color 2 = #000000 alpha 0, en Face Corner / Byte Color. "
                      "Efface les couleurs peintes de ces deux attributs")
    bl_options = {"REGISTER", "UNDO"}

    confirmed: bpy.props.BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        proj = get_project(context)
        try:
            painted = existing_paint(target_objects(context, proj))
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if painted:
            self.confirmed = True
            return context.window_manager.invoke_confirm(
                self, event, title="Effacer la peinture existante ?",
                message="Couleurs peintes détectées : " + ", ".join(painted[:4]) + (" …" if len(painted) > 4 else ""),
                confirm_text="Réinitialiser")
        return self.execute(context)

    def execute(self, context):
        proj = get_project(context)
        szb.require()
        try:
            objs = target_objects(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        painted = existing_paint(objs)
        if painted and not self.confirmed:
            self.report({"ERROR"}, "Couleurs déjà peintes (" + ", ".join(painted[:4]) + ") : confirmez la réinitialisation.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        replaced = configure(objs)
        problems = verify_exact(objs) + [m for s, m, f in issues_for(objs)]
        if problems:
            self.report({"ERROR"}, "Vérification en échec : " + ", ".join(problems))
            return {"CANCELLED"}
        msg = f"Color 1 et Color 2 configurés sur {len(objs)} maillage(s)."
        if replaced:
            msg += " Remplacés (mauvais domaine ou type) : " + ", ".join(replaced)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_glow_paint_mode(bpy.types.Operator):
    bl_idname = "mio_chain.glow_paint_mode"
    bl_label = "Activer Color 1 et passer en Vertex Paint"
    bl_description = "Rend Color 1 actif sur le maillage actif et passe en Vertex Paint (rien n'est peint)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Sélectionnez le maillage à peindre.")
            return {"CANCELLED"}
        name = szb.color_attr_name(0)
        attr = obj.data.color_attributes.get(name)
        if attr is None:
            self.report({"ERROR"}, f"« {name} » absent : configurez d'abord les Color Attributes (étape 5).")
            return {"CANCELLED"}
        obj.data.color_attributes.active_color = attr
        bpy.ops.object.mode_set(mode="VERTEX_PAINT")
        self.report({"INFO"}, f"{name} actif sur {obj.name}, mode Vertex Paint.")
        return {"FINISHED"}


CLASSES = (MIO_OT_colors_configure, MIO_OT_glow_paint_mode)
