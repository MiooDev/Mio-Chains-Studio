"""Aperçu sur mon display : scène séparée, copie indépendante du bijou, repère enregistré, rendu.

Le display est ajouté (append) dans une scène à part : ses matériaux, lumières, caméras et réglages
de rendu ne sont pas modifiés. Le bijou y est une COPIE (maillages et matériaux propres) : modifier
l'aperçu ne touche jamais le modèle destiné à FiveM. Rien de cette scène n'entre dans l'export.
"""

import json
import os
import time

import bpy
from mathutils import Euler, Matrix, Vector

from .prefs import addon_prefs, save_user_prefs
from .utils import (
    McsError,
    TAG_DISPLAY,
    TAG_PREVIEW,
    TAG_PROJECT,
    abspath,
    get_project,
    hash_strings,
    part_meshes,
    parts_signature,
    project_scene,
    tag,
    world_bounds,
)

KIND = "mcs_preview_kind"       # copy / root / marker / collection / material
SRC = "mcs_preview_src"         # nom de l'objet ou du matériau source


def marker_key(path):
    return os.path.normcase(os.path.normpath(abspath(path)))


def _check_file(proj):
    path = abspath(proj.display_path)
    if not path:
        raise McsError("Choisissez le fichier .blend du display.")
    if not os.path.isfile(path):
        raise McsError(f"Fichier du display introuvable : {path}")
    if not path.lower().endswith(".blend"):
        raise McsError("Le display doit être un fichier .blend.")
    if bpy.data.filepath and os.path.normcase(path) == os.path.normcase(bpy.data.filepath):
        raise McsError("Le display ne peut pas être le fichier du projet lui-même.")
    return path


def analyse(proj):
    path = _check_file(proj)
    try:
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            scenes, collections, worlds = list(src.scenes), list(src.collections), list(src.worlds)
    except (OSError, RuntimeError) as exc:
        raise McsError(f"Fichier du display illisible : {exc}") from exc
    previous = {(i.kind, i.name): i.use for i in proj.display_items}
    proj.display_items.clear()
    for kind, names in (("SCENE", scenes), ("COLLECTION", collections), ("WORLD", worlds)):
        for name in names:
            item = proj.display_items.add()
            item.name, item.kind = name, kind
            item.use = previous.get((kind, name), kind != "COLLECTION")
    if scenes and proj.display_scene_name not in scenes:
        proj.display_scene_name = scenes[0]
    return scenes, collections, worlds


def preview_objects(proj, kind=None):
    pid = proj.project_id
    return [o for o in bpy.data.objects
            if o.get(TAG_PROJECT) == pid and o.get(TAG_PREVIEW) and (kind is None or o.get(KIND) == kind)]


def _remove_obj(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)


def unload(proj):
    """Retire la scène d'aperçu et uniquement les éléments chargés ou créés par l'addon."""
    pid = proj.project_id
    scene = proj.preview_scene
    for obj in list(bpy.data.objects):
        if obj.get(TAG_PROJECT) == pid and (obj.get(TAG_DISPLAY) or obj.get(TAG_PREVIEW)):
            _remove_obj(obj)
    for coll in list(bpy.data.collections):
        if coll.get(TAG_PROJECT) == pid and (coll.get(TAG_DISPLAY) or coll.get(TAG_PREVIEW)):
            bpy.data.collections.remove(coll)
    if scene is not None and scene.get(TAG_PROJECT) == pid:
        bpy.data.scenes.remove(scene)
    proj.preview_scene = None
    proj.preview_marker = None
    proj.preview_root = None
    proj.display_loaded_path = ""
    proj.preview_signature = ""


def _relative_to(path, base_dir):
    """Chemin « //… » d'un fichier .blend, résolu depuis le dossier de ce fichier (et non du projet)."""
    rel = path[2:]
    if os.sep == "/":
        rel = rel.replace("\\", "/")
    return os.path.normpath(os.path.join(base_dir, rel))


def resolve_images(new_images, display_path, before_images):
    """Retrouve les textures du display : chemin relatif au display, sinon même fichier déjà utilisé dans le projet.

    Retourne (retrouvées par chemin relatif, reprises du projet).
    """
    display_dir = os.path.dirname(display_path)
    project_files = {}
    for img in before_images:
        if img.packed_file is None and img.source == "FILE" and img.filepath:
            path = abspath(img.filepath)
            if os.path.isfile(path):
                project_files.setdefault(os.path.basename(path).lower(), path)
    by_relative, from_project = [], []
    for img in new_images:
        if img.packed_file is not None or img.source not in {"FILE", "SEQUENCE", "TILED"} or not img.filepath:
            continue
        if os.path.exists(abspath(img.filepath)):
            continue
        target, found_by = None, None
        if img.filepath.startswith("//"):
            candidate = _relative_to(img.filepath, display_dir)
            if os.path.exists(candidate):
                target, found_by = candidate, by_relative
        if target is None:
            name = os.path.basename(img.filepath.replace("\\", "/")).lower()
            if name in project_files:
                target, found_by = project_files[name], from_project
        if target is not None:
            img.filepath = target
            img.reload()
            found_by.append(img.name)
    return by_relative, from_project


def missing_display_images(proj):
    """Images du display dont le fichier reste introuvable."""
    out = []
    for name in json.loads(proj.display_image_names or "[]"):
        img = bpy.data.images.get(name)
        if img is not None and img.packed_file is None and img.filepath and not os.path.exists(abspath(img.filepath)):
            out.append(f"Image : {img.name} ({img.filepath})")
    return out


def _scan_missing(new_images, new_libs):
    missing = []
    for img in new_images:
        if img.packed_file is None and img.source in {"FILE", "SEQUENCE", "TILED"} and img.filepath:
            if not os.path.exists(abspath(img.filepath)):
                missing.append(f"Image : {img.name} ({img.filepath})")
    for lib in new_libs:
        if not os.path.isfile(abspath(lib.filepath)):
            missing.append(f"Bibliothèque liée : {lib.filepath}")
    return missing


def load(context, proj, force=False):
    path = _check_file(proj)
    if proj.preview_scene is not None:
        if not force:
            raise McsError("Le display est déjà chargé : cliquez « Actualiser le bijou », ou « Recharger » "
                           "pour tout recharger.")
        unload(proj)
    scenes, collections, worlds = analyse(proj)         # toujours relire le fichier choisi
    if proj.display_mode == "SCENE" and proj.display_scene_name not in scenes and scenes:
        proj.display_scene_name = scenes[0]
    src_scene = project_scene(context)
    images_before, libs_before = set(bpy.data.images), set(bpy.data.libraries)
    objects_before = set(bpy.data.objects)
    try:
        if proj.display_mode == "SCENE":
            if not proj.display_scene_name:
                raise McsError("Le fichier du display ne contient aucune scène.")
            with bpy.data.libraries.load(path, link=False) as (src, dst):
                if proj.display_scene_name not in src.scenes:
                    raise McsError(f"Scène « {proj.display_scene_name} » absente du display.")
                dst.scenes = [proj.display_scene_name]
            scene = dst.scenes[0]
        else:
            colls = [i.name for i in proj.display_items if i.kind == "COLLECTION" and i.use]
            worlds = [i.name for i in proj.display_items if i.kind == "WORLD" and i.use][:1]
            if not colls:
                raise McsError("Cochez au moins une collection du display à charger.")
            with bpy.data.libraries.load(path, link=False) as (src, dst):
                dst.collections = colls
                dst.worlds = worlds
            scene = bpy.data.scenes.new("MCS_Apercu")
            for coll in dst.collections:
                if coll is not None:
                    scene.collection.children.link(coll)
            if dst.worlds and dst.worlds[0] is not None:
                scene.world = dst.worlds[0]
    except (OSError, RuntimeError) as exc:
        raise McsError(f"Chargement du display impossible : {exc}") from exc

    scene.name = f"MCS_Apercu_{scene.name}" if not scene.name.startswith("MCS_Apercu") else scene.name
    tag(scene, proj, role="apercu", generated=True)
    scene.mio_chain_source = src_scene
    for obj in bpy.data.objects:
        if obj not in objects_before:
            tag(obj, proj, role="display", generated=False, **{TAG_DISPLAY: 1})
    for coll in scene.collection.children_recursive:
        tag(coll, proj, role="display", generated=False, **{TAG_DISPLAY: 1})
    new_images = [i for i in bpy.data.images if i not in images_before]
    by_relative, from_project = resolve_images(new_images, path, images_before)
    proj.display_image_names = json.dumps([i.name for i in new_images])
    missing = _scan_missing(new_images, [l for l in bpy.data.libraries if l not in libs_before])
    proj.display_missing = json.dumps(missing)
    notes = []
    if by_relative:
        notes.append(f"{len(by_relative)} texture(s) retrouvée(s) depuis le dossier du display")
    if from_project:
        notes.append(f"{len(from_project)} texture(s) reprise(s) de votre projet (même fichier)")
    proj.display_textures_note = (", ".join(notes) + ".") if notes else ""
    proj.preview_scene = scene
    proj.display_loaded_path = path

    r = scene.render
    proj.render_res_x, proj.render_res_y, proj.render_percent = r.resolution_x, r.resolution_y, r.resolution_percentage
    cams = [o for o in scene.objects if o.type == "CAMERA"]
    proj.render_camera = scene.camera if scene.camera in cams else (cams[0] if cams else None)

    prefs = addon_prefs(context)
    saved = prefs.markers().get(marker_key(path)) if prefs else None
    if saved and (proj.display_mode != "SCENE" or saved.get("scene") in (None, proj.display_scene_name)):
        m = saved["matrix"]
        set_marker(proj, Matrix([m[0:4], m[4:8], m[8:12], m[12:16]]))
        origin = "position mémorisée"
    else:
        matrix, origin = auto_marker(scene)
        set_marker(proj, matrix)
    placed = 0
    if part_meshes(proj):
        placed = len(refresh(context, proj))
    return scene, missing, origin, placed


MARKER_WORDS = ("repere", "repère", "marker", "bijou", "jewel", "collier", "necklace", "chaine", "chaîne", "chain")


def auto_marker(scene):
    """Repère automatique : un vide du display nommé comme un repère, sinon le curseur 3D de sa scène."""
    scene.view_layers[0].update()      # positions monde des objets tout juste ajoutés
    for obj in scene.objects:
        if obj.type == "EMPTY" and any(w in obj.name.lower() for w in MARKER_WORDS) and not obj.get(TAG_PREVIEW):
            return obj.matrix_world.copy(), f"vide « {obj.name} » du display"
    return scene.cursor.matrix.copy(), "curseur 3D du display"


def set_marker(proj, matrix):
    scene = proj.preview_scene
    if scene is None:
        raise McsError("Chargez d'abord le display.")
    marker = proj.preview_marker
    if marker is None:
        marker = bpy.data.objects.new("MCS_Repere_Bijou", None)
        marker.empty_display_type = "ARROWS"
        marker.empty_display_size = 0.05
        tag(marker, proj, role="repere", **{TAG_PREVIEW: 1, KIND: "marker"})
        scene.collection.objects.link(marker)
        proj.preview_marker = marker
    marker.matrix_world = matrix
    return marker


def save_marker(context, proj):
    marker = proj.preview_marker
    if marker is None:
        raise McsError("Définissez d'abord le repère.")
    prefs = addon_prefs(context)
    if prefs is None:
        raise McsError("Préférences de l'addon indisponibles.")
    key = marker_key(proj.display_loaded_path or proj.display_path)
    prefs.save_marker(key, {
        "matrix": [v for row in marker.matrix_world for v in row],
        "scene": proj.display_scene_name if proj.display_mode == "SCENE" else None,
        "unit_scale": proj.preview_scene.unit_settings.scale_length,
        "saved": time.strftime("%Y-%m-%d %H:%M"),
    })
    save_user_prefs()
    back = prefs.markers().get(key)
    if not back or back["matrix"][3] != marker.matrix_world[0][3]:
        raise McsError("Enregistrement du repère non vérifié.")
    return key


def unit_factor(proj, context):
    src = project_scene(context).unit_settings.scale_length
    dst = proj.preview_scene.unit_settings.scale_length if proj.preview_scene else 1.0
    return src / dst if dst else 1.0


def anchor_matrix(proj):
    """Point du bijou posé sur le repère : centre ou haut de sa boîte englobante (axes du monde)."""
    b = world_bounds([o for o, r in part_meshes(proj)])
    if b is None:
        return Matrix.Identity(4)
    lo, hi = b
    z = hi[2] if proj.preview_anchor == "TOP" else (lo[2] + hi[2]) / 2
    return Matrix.Translation(Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, z)))


def apply_preview_transform(proj, context=None):
    root = proj.preview_root
    if root is None or proj.preview_scene is None:
        return
    try:
        f = unit_factor(proj, context or bpy.context)
    except (AttributeError, ReferenceError):
        f = 1.0
    root.matrix_basis = Matrix.LocRotScale(Vector(proj.preview_loc), Euler(proj.preview_rot),
                                           Vector([proj.preview_scale * f] * 3))


def _preview_collection(proj):
    scene = proj.preview_scene
    for coll in scene.collection.children:
        if coll.get(TAG_PROJECT) == proj.project_id and coll.get(KIND) == "collection":
            return coll
    coll = bpy.data.collections.new("MCS_Apercu_Bijou")
    tag(coll, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "collection"})
    scene.collection.children.link(coll)
    return coll


def _preview_material(proj, mat):
    if mat is None:
        return None
    if proj.preview_keep_materials:
        for m in bpy.data.materials:
            if m.get(TAG_PROJECT) == proj.project_id and m.get(TAG_PREVIEW) and m.get(SRC) == mat.name:
                return m
    copy = mat.copy()
    copy.name = f"Apercu_{mat.name}"
    tag(copy, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "material", SRC: mat.name})
    return copy


def preview_signature(proj):
    return hash_strings([parts_signature(proj), proj.preview_anchor])


def refresh(context, proj):
    """Crée ou remplace la copie du bijou dans la scène d'aperçu, sans recharger le display."""
    if proj.preview_scene is None:
        raise McsError("Chargez d'abord le display.")
    if proj.preview_marker is None:
        set_marker(proj, auto_marker(proj.preview_scene)[0])
    comps = part_meshes(proj)
    if not comps:
        raise McsError("Aucun composant de bijou à placer.")
    for obj in preview_objects(proj, "copy"):
        _remove_obj(obj)
    coll = _preview_collection(proj)
    root = proj.preview_root
    if root is None:
        root = bpy.data.objects.new("MCS_Apercu_Racine", None)
        root.empty_display_size = 0.02
        tag(root, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "root"})
        coll.objects.link(root)
        proj.preview_root = root
    root.parent = proj.preview_marker
    root.matrix_parent_inverse = Matrix.Identity(4)
    apply_preview_transform(proj, context)

    anchor_inv = anchor_matrix(proj).inverted()
    arm = proj.ref_root
    prev_pose = arm.data.pose_position if arm is not None else None
    if arm is not None:
        arm.data.pose_position = "REST"
    pscene = project_scene(context)
    view_layer = context.view_layer if context.scene == pscene else pscene.view_layers[0]
    view_layer.update()
    try:
        dg = view_layer.depsgraph
        copies = []
        for obj, role in comps:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            mesh.name = f"Apercu_{obj.name}"
            tag(mesh, proj, role="apercu", **{TAG_PREVIEW: 1})
            for i, mat in enumerate(mesh.materials):
                mesh.materials[i] = _preview_material(proj, mat)
            copy = bpy.data.objects.new(f"Apercu_{obj.name}", mesh)
            tag(copy, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "copy", SRC: obj.name, "mcs_src_role": role})
            coll.objects.link(copy)
            copy.parent = root
            copy.matrix_parent_inverse = Matrix.Identity(4)
            copy.matrix_basis = anchor_inv @ obj.matrix_world
            copies.append(copy)
    finally:
        if arm is not None:
            arm.data.pose_position = prev_pose
    proj.preview_scene.view_layers[0].update()
    proj.preview_signature = preview_signature(proj)
    # Vérification : une copie par composant, aucune donnée partagée avec les sources.
    expected = {o.name for o, r in comps}
    got = [c.get(SRC) for c in preview_objects(proj, "copy")]
    if sorted(got) != sorted(expected):
        raise McsError(f"Copies d'aperçu incohérentes : {got} au lieu de {sorted(expected)}.")
    for c in copies:
        src = bpy.data.objects[c[SRC]]
        if c.data == src.data or any(m is not None and m in src.data.materials[:] for m in c.data.materials):
            raise McsError(f"{c.name} partage des données avec la source.")
    return copies


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------

def _samples_setting(scene):
    if scene.render.engine == "CYCLES":
        return scene.cycles, "samples"
    eevee = getattr(scene, "eevee", None)
    if eevee is not None and hasattr(eevee, "taa_render_samples") and "EEVEE" in scene.render.engine:
        return eevee, "taa_render_samples"
    return None, None


def render(context, proj):
    scene = proj.preview_scene
    if scene is None:
        raise McsError("Chargez d'abord le display.")
    cam = proj.render_camera
    if cam is None or cam.name not in scene.objects:
        raise McsError("Choisissez une caméra de la scène d'aperçu.")
    if not preview_objects(proj, "copy"):
        raise McsError("Placez d'abord le bijou sur le display.")
    out_dir = abspath(proj.render_dir)
    if not out_dir or (proj.render_dir.startswith("//") and not bpy.data.filepath):
        raise McsError("Enregistrez le .blend ou choisissez un dossier de sortie absolu.")
    os.makedirs(out_dir, exist_ok=True)
    r = scene.render
    saved = dict(camera=scene.camera, x=r.resolution_x, y=r.resolution_y, p=r.resolution_percentage,
                 path=r.filepath, fmt=r.image_settings.file_format)
    owner, attr = _samples_setting(scene)
    saved_samples = getattr(owner, attr) if owner else None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    mode = "rapide" if proj.render_mode == "QUICK" else "final"
    target = os.path.join(out_dir, f"{proj.output_name.strip().replace('^', '_') or 'bijou'}_{mode}_{stamp}")
    try:
        scene.camera = cam
        r.resolution_x, r.resolution_y = proj.render_res_x, proj.render_res_y
        r.resolution_percentage = proj.render_percent
        if proj.render_mode == "QUICK":
            r.resolution_percentage = max(1, proj.render_percent // 2)
            if owner:
                setattr(owner, attr, proj.quick_samples)
        r.image_settings.file_format = "PNG"
        r.filepath = target
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        scene.camera = saved["camera"]
        r.resolution_x, r.resolution_y, r.resolution_percentage = saved["x"], saved["y"], saved["p"]
        r.filepath = saved["path"]
        r.image_settings.file_format = saved["fmt"]
        if owner:
            setattr(owner, attr, saved_samples)
    out = target + ".png"
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise McsError(f"Le rendu n'a pas produit de fichier : {out}")
    return out


# ---------------------------------------------------------------------------
# Opérateurs
# ---------------------------------------------------------------------------

class MIO_OT_display_analyse(bpy.types.Operator):
    bl_idname = "mio_chain.display_analyse"
    bl_label = "Analyser le display"
    bl_description = "Liste les scènes, collections et mondes du fichier sans rien charger"

    def execute(self, context):
        proj = get_project(context)
        try:
            scenes, colls, worlds = analyse(proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(scenes)} scène(s), {len(colls)} collection(s), {len(worlds)} monde(s).")
        return {"FINISHED"}


class MIO_OT_display_load(bpy.types.Operator):
    bl_idname = "mio_chain.display_load"
    bl_label = "Charger le display"
    bl_description = "Ajoute le display dans une scène séparée (sans modifier son contenu)"
    bl_options = {"REGISTER", "UNDO"}

    force: bpy.props.BoolProperty(name="Recharger", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        if self.force:
            return context.window_manager.invoke_confirm(self, event, title="Recharger le display ?",
                                                         message="La scène d'aperçu et ses copies seront recréées.")
        return self.execute(context)

    def execute(self, context):
        proj = get_project(context)
        try:
            scene, missing, origin, placed = load(context, proj, self.force)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        msg = f"Display chargé (« {scene.name} »), repère : {origin}."
        if proj.display_textures_note:
            msg += " " + proj.display_textures_note
        msg += f" Bijou placé ({placed} pièce(s))." if placed else " Désignez le bijou (étape 2) puis « Actualiser le bijou »."
        if missing:
            msg += f" {len(missing)} ressource(s) externe(s) manquante(s) dans le display."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MIO_OT_marker_set(bpy.types.Operator):
    bl_idname = "mio_chain.marker_set"
    bl_label = "Définir le repère"
    bl_description = "Place le repère du bijou sur l'objet actif du display ou sur le curseur 3D"
    bl_options = {"REGISTER", "UNDO"}

    source: bpy.props.EnumProperty(items=[("ACTIVE", "Objet actif", ""), ("CURSOR", "Curseur 3D", "")],
                                   options={"HIDDEN"})

    def execute(self, context):
        proj = get_project(context)
        scene = proj.preview_scene
        if scene is None:
            self.report({"ERROR"}, "Chargez d'abord le display.")
            return {"CANCELLED"}
        if self.source == "ACTIVE":
            obj = context.active_object
            if obj is None or obj.name not in scene.objects or obj.get(TAG_PREVIEW):
                self.report({"ERROR"}, "Sélectionnez dans la scène d'aperçu un objet du display (ex. un vide au cou).")
                return {"CANCELLED"}
            matrix = obj.matrix_world.copy()
        else:
            matrix = scene.cursor.matrix.copy()
        set_marker(proj, matrix)
        if proj.preview_root is not None:
            proj.preview_root.parent = proj.preview_marker
        self.report({"INFO"}, "Repère défini. Enregistrez-le pour les projets suivants.")
        return {"FINISHED"}


class MIO_OT_marker_save(bpy.types.Operator):
    bl_idname = "mio_chain.marker_save"
    bl_label = "Mémoriser cette position"
    bl_description = "Mémorise ce repère pour ce fichier display (réutilisé à chaque chargement)"

    def execute(self, context):
        proj = get_project(context)
        try:
            key = save_marker(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Repère enregistré pour {os.path.basename(key)}.")
        return {"FINISHED"}


class MIO_OT_preview_refresh(bpy.types.Operator):
    bl_idname = "mio_chain.preview_refresh"
    bl_label = "Actualiser le bijou"
    bl_description = "Remplace la copie du bijou par l'état actuel du projet, sans recharger le display"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        proj = get_project(context)
        try:
            copies = refresh(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Aperçu à jour : {len(copies)} copie(s) placée(s) ensemble sur le repère.")
        return {"FINISHED"}


class MIO_OT_display_find_textures(bpy.types.Operator):
    bl_idname = "mio_chain.display_find_textures"
    bl_label = "Rechercher les textures manquantes…"
    bl_description = ("Choisissez votre dossier de textures : Blender y cherche (sous-dossiers compris) les fichiers "
                      "manquants par leur nom (Fichier ▸ Données externes ▸ Rechercher les fichiers manquants)")
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        proj = get_project(context)
        folder = abspath(self.directory)
        if not os.path.isdir(folder):
            self.report({"ERROR"}, f"Dossier introuvable : {folder}")
            return {"CANCELLED"}
        before = len(missing_display_images(proj))
        bpy.ops.file.find_missing_files(directory=folder + os.sep)
        for name in json.loads(proj.display_image_names or "[]"):
            img = bpy.data.images.get(name)
            if img is not None and img.filepath and os.path.exists(abspath(img.filepath)):
                img.reload()
        missing = missing_display_images(proj)
        proj.display_missing = json.dumps(missing)
        found = before - len(missing)
        if missing:
            self.report({"WARNING"}, f"{found} texture(s) retrouvée(s), {len(missing)} encore introuvable(s).")
        else:
            self.report({"INFO"}, f"{found} texture(s) retrouvée(s) : plus aucune texture manquante.")
        return {"FINISHED"}


class MIO_OT_preview_move(bpy.types.Operator):
    bl_idname = "mio_chain.preview_move"
    bl_label = "Déplacer le bijou"
    bl_description = "Ouvre le display et sélectionne le repère qui porte le bijou : déplacez-le avec G, R et S"

    def execute(self, context):
        proj = get_project(context)
        marker = proj.preview_marker
        if proj.preview_scene is None or marker is None:
            self.report({"ERROR"}, "Chargez d'abord le display.")
            return {"CANCELLED"}
        if context.window is not None:
            context.window.scene = proj.preview_scene
        view_layer = proj.preview_scene.view_layers[0]
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in view_layer.objects:
            o.select_set(False, view_layer=view_layer)
        marker.hide_set(False, view_layer=view_layer)
        marker.select_set(True, view_layer=view_layer)
        view_layer.objects.active = marker
        self.report({"INFO"}, "Bijou sélectionné : G pour déplacer, R pour tourner, S pour l'échelle, "
                              "puis « Mémoriser cette position ».")
        return {"FINISHED"}


class MIO_OT_view_camera(bpy.types.Operator):
    bl_idname = "mio_chain.view_camera"
    bl_label = "Voir par la caméra"
    bl_description = "Ouvre la scène d'aperçu et regarde par la caméra choisie"

    def execute(self, context):
        proj = get_project(context)
        scene, cam = proj.preview_scene, proj.render_camera
        if scene is None or cam is None:
            self.report({"ERROR"}, "Chargez le display et choisissez une caméra.")
            return {"CANCELLED"}
        if context.window is None:
            self.report({"ERROR"}, "Aucune fenêtre Blender (mode sans interface).")
            return {"CANCELLED"}
        context.window.scene = scene
        scene.camera = cam
        done = False
        for area in context.window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                done = True
        if not done:
            self.report({"WARNING"}, "Scène d'aperçu ouverte, mais aucune vue 3D trouvée.")
        return {"FINISHED"}


class MIO_OT_back_to_project(bpy.types.Operator):
    bl_idname = "mio_chain.back_to_project"
    bl_label = "Revenir au projet"
    bl_description = "Réaffiche la scène du projet (modèle destiné à FiveM)"

    def execute(self, context):
        if context.window is not None:
            context.window.scene = project_scene(context)
        return {"FINISHED"}


class MIO_OT_render(bpy.types.Operator):
    bl_idname = "mio_chain.render"
    bl_label = "Lancer le rendu"
    bl_description = "Rend la scène d'aperçu avec la caméra du display et enregistre l'image (Blender est occupé pendant le rendu)"

    mode: bpy.props.EnumProperty(items=[("CURRENT", "Réglage actuel", ""), ("QUICK", "Rapide", ""),
                                        ("FINAL", "Final", "")], default="CURRENT", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        proj = get_project(context)
        if self.mode != "CURRENT":
            proj.render_mode = self.mode
        try:
            out = render(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stale = proj.preview_signature != preview_signature(proj)
        msg = f"Rendu enregistré : {out}"
        if stale:
            self.report({"WARNING"}, msg + " (aperçu périmé : actualisez-le avant le rendu final).")
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


CLASSES = (MIO_OT_display_analyse, MIO_OT_display_load, MIO_OT_marker_set, MIO_OT_marker_save,
           MIO_OT_preview_refresh, MIO_OT_display_find_textures, MIO_OT_preview_move, MIO_OT_view_camera, MIO_OT_back_to_project, MIO_OT_render)
