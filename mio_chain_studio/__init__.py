"""Mio Chain Studio — création et préparation de chaînes personnalisées FiveM avec Sollumz.

Onglet « Mio Chain » de la barre latérale de la vue 3D (touche N).
"""

import bpy
from bpy.app.handlers import persistent

from . import (
    assembly,
    atlas,
    display,
    effects,
    export,
    materials,
    pendant,
    prefs,
    props,
    rigging,
    sollumz_bridge,
    status,
    ui,
)

MODULES = (pendant, assembly, materials, atlas, effects, rigging, display, export, ui)


@persistent
def _on_load(_dummy):
    sollumz_bridge.detect(refresh=True)
    status.invalidate()


@persistent
def _on_depsgraph(_scene, _depsgraph):
    status.invalidate()


def register():
    bpy.utils.register_class(prefs.MCS_Preferences)
    props.register()
    for module in MODULES:
        for cls in module.CLASSES:
            bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    for handler, fn in ((bpy.app.handlers.load_post, _on_load), (bpy.app.handlers.depsgraph_update_post, _on_depsgraph)):
        if fn in handler:
            handler.remove(fn)
    for module in reversed(MODULES):
        for cls in reversed(module.CLASSES):
            bpy.utils.unregister_class(cls)
    props.unregister()
    bpy.utils.unregister_class(prefs.MCS_Preferences)
