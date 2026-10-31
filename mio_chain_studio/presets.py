"""Étape 4 : presets de matériaux Sollumz (JSON dans le dossier de configuration de Blender, persistants).

Un preset enregistre le shader, les références des textures, leurs options Embedded et leur espace
colorimétrique, ainsi que les Value Parameters. Il n'est « complet » que si toutes ses textures existent.
"""

import json
import os

import bpy

from . import sollumz_bridge as szb
from .prefs import addon_prefs, default_presets_dir
from .utils import McsError, abspath

FORMAT = 2
SAMPLERS = ("DiffuseSampler", "BumpSampler", "SpecSampler")


def folder():
    prefs = addon_prefs()
    path = prefs.presets_folder() if prefs else default_presets_dir()
    os.makedirs(path, exist_ok=True)
    return path


def safe_name(name):
    clean = "".join(c for c in name.strip() if c.isalnum() or c in "-_ ").strip()
    if not clean:
        raise McsError("Nom de preset invalide (lettres, chiffres, espace, - et _).")
    return clean


def path_of(name):
    return os.path.join(folder(), safe_name(name) + ".json")


def names():
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(folder()) if f.endswith(".json"))
    except OSError:
        return []


def load(name):
    path = path_of(name)
    if not os.path.isfile(path):
        raise McsError(f"Preset « {name} » introuvable ({path}).")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise McsError(f"Preset « {name} » illisible : {exc}") from exc
    if not isinstance(data, dict) or "shader" not in data:
        raise McsError(f"Preset « {name} » invalide.")
    data.setdefault("textures", {})
    data.setdefault("params", {})
    return data


def save(name, data):
    path = path_of(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    if load(name).get("shader") != data.get("shader"):
        raise McsError(f"Écriture du preset non vérifiée : {path}")
    return path


def capture(mat):
    """Preset depuis un matériau Sollumz."""
    shader = szb.material_shader(mat)
    data = {"version": FORMAT, "shader": shader, "textures": {}, "params": {}}
    used = set(szb.shader_texture_params(shader))
    for node in szb.texture_nodes(mat):
        if node.name not in used or node.image is None or not node.image.filepath:
            continue
        data["textures"][node.name] = {
            "path": abspath(node.image.filepath),
            "embedded": bool(node.texture_properties.embedded),
            "colorspace": node.image.colorspace_settings.name,
        }
    for node in mat.node_tree.nodes:
        if node.bl_idname == "SOLLUMZ_NT_SHADER_Parameter":
            data["params"][node.name] = [float(o.default_value) for o in node.outputs]
    return data


def status(data):
    """(complet ?, [(entrée, chemin manquant)], [entrées absentes])"""
    shader = data.get("shader", "")
    available = set(szb.shader_texture_params(shader)) if szb.find_shader(shader) else set(SAMPLERS)
    missing_files, missing_entries = [], []
    for sampler in SAMPLERS:
        if sampler not in available:
            continue
        tex = data.get("textures", {}).get(sampler)
        if not tex or not tex.get("path"):
            missing_entries.append(sampler)
        elif not os.path.isfile(tex["path"]):
            missing_files.append((sampler, tex["path"]))
    return not missing_files and not missing_entries, missing_files, missing_entries


def duplicate(name, new_name):
    data = load(name)
    if os.path.exists(path_of(new_name)):
        raise McsError(f"Le preset « {new_name} » existe déjà.")
    return save(new_name, data)


def delete(name):
    path = path_of(name)
    if not os.path.isfile(path):
        raise McsError(f"Preset « {name} » introuvable.")
    os.remove(path)


def relocate(name, sampler, new_path):
    data = load(name)
    new_path = abspath(new_path)
    if not os.path.isfile(new_path):
        raise McsError(f"Fichier introuvable : {new_path}")
    tex = data["textures"].setdefault(sampler, {"embedded": sampler != "DiffuseSampler",
                                                "colorspace": "Non-Color" if sampler == "BumpSampler" else "sRGB"})
    tex["path"] = new_path
    return save(name, data)
