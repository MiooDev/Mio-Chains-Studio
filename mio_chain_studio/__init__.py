"""Mio Chain Studio — préparer ses propres pendentifs et chaînes pour FiveM avec Sollumz.

Onglet « Mio Chain » de la barre latérale de la vue 3D (touche N).
"""

import bpy
from bpy.app.handlers import persistent

from . import (
    colors,
    components,
    display,
    export,
    materials,
    prefs,
    props,
    rigging,
    sollumz_bridge,
    status,
    svg,
    teef,
    ui,
)

MODULES = (svg, components, materials, colors, rigging, teef, export, display, ui)


def _rna_name(cls):
    if issubclass(cls, bpy.types.Operator):
        category, name = cls.bl_idname.split(".", 1)
        return f"{category.upper()}_OT_{name}"
    return getattr(cls, "bl_idname", None) or cls.__name__


def check_conflicts():
    """Éléments de Mio Chain Studio remplacés par un autre addon qui utilise les mêmes identifiants."""
    out = []
    for module in (props,) + MODULES:
        for cls in module.CLASSES:
            registered = getattr(bpy.types, _rna_name(cls), None)
            if registered is not None and registered is not cls:
                out.append(f"{_rna_name(cls)} → {getattr(registered, '__module__', '?')}")
    prop = bpy.types.Scene.bl_rna.properties.get("mio_chain")
    fixed = getattr(prop, "fixed_type", None)
    if prop is None or fixed is None or fixed.identifier != props.MCS_Project.__name__:
        out.append(f"Scene.mio_chain → {fixed.identifier if fixed else 'absent'}")
    return out


@persistent
def _on_load(_dummy):
    sollumz_bridge.detect(refresh=True)
    status.invalidate()


@persistent
def _on_depsgraph(_scene, _depsgraph):
    status.invalidate()


def register():
    taken = check_conflicts_before()
    if taken:
        print("Mio Chain Studio : identifiants déjà utilisés par un autre addon :", ", ".join(taken))
    bpy.utils.register_class(prefs.MCS_Preferences)
    props.register()
    for module in MODULES:
        for cls in module.CLASSES:
            bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def check_conflicts_before():
    """Avant l'enregistrement : identifiants déjà pris par un autre module."""
    taken = []
    for module in MODULES:
        for cls in module.CLASSES:
            existing = getattr(bpy.types, _rna_name(cls), None)
            if existing is not None and not getattr(existing, "__module__", "").startswith(__package__):
                taken.append(f"{_rna_name(cls)} ({existing.__module__})")
    if "mio_chain" in bpy.types.Scene.bl_rna.properties:
        taken.append("Scene.mio_chain")
    return taken


def unregister():
    for handler, fn in ((bpy.app.handlers.load_post, _on_load), (bpy.app.handlers.depsgraph_update_post, _on_depsgraph)):
        if fn in handler:
            handler.remove(fn)
    for module in reversed(MODULES):
        for cls in reversed(module.CLASSES):
            bpy.utils.unregister_class(cls)
    props.unregister()
    bpy.utils.unregister_class(prefs.MCS_Preferences)
