"""Aperçu sur mon display : scène séparée, copie indépendante du bijou, repère enregistré, rendu.

Le display est ajouté (append) dans une scène à part : ses matériaux, lumières, caméras et réglages
de rendu ne sont pas modifiés. Le bijou y est une COPIE (maillages et matériaux propres) : modifier
l'aperçu ne touche jamais le modèle destiné à FiveM. Rien de cette scène n'entre dans l'export.
"""

import json
import os
import re
import time

import bpy
from mathutils import Euler, Matrix, Vector

from .prefs import addon_prefs, save_user_prefs
from .utils import (
    McsError,
    TAG_DISPLAY,
    TAG_PREVIEW,
    TAG_PROJECT,
    TAG_REFERENCE,
    abspath,
    get_project,
    hash_strings,
    iter_tree,
    object_signature,
    part_meshes,
    project_scene,
    tag,
    world_bounds,
)

KIND = "mcs_preview_kind"       # copy / root / marker / collection / material
SRC = "mcs_preview_src"         # nom de l'objet ou du matériau source
SRC_SIG = "mcs_preview_src_sig" # empreinte du matériau source au moment de la copie

# Fichiers proposés dans les sélecteurs de textures (le DDS en premier : textures GTA / FiveM).
IMAGE_GLOB = "*.dds;*.png;*.jpg;*.jpeg;*.tga;*.tif;*.tiff;*.bmp;*.exr;*.hdr;*.webp"
IMAGE_EXTS = tuple(g[1:] for g in IMAGE_GLOB.split(";"))


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


def _placeable(obj):
    return (obj.type == "MESH" and not obj.get(TAG_PREVIEW) and not obj.get(TAG_DISPLAY)
            and not obj.get(TAG_REFERENCE))


def selected_meshes(context):
    """Maillages sélectionnés dans la scène du PROJET (même si la vue affiche le display)."""
    pscene = project_scene(context)
    view_layer = context.view_layer if context.scene == pscene else pscene.view_layers[0]
    out = []
    for obj in pscene.objects:
        try:
            if _placeable(obj) and obj.select_get(view_layer=view_layer):
                out.append(obj)
        except RuntimeError:
            continue
    return out


def uses_selection(proj):
    """La sélection du projet sert de bijou : choix « Objets sélectionnés », ou aucun composant à l'étape 2."""
    return proj.preview_source == "SELECTION" or not part_meshes(proj)


def preview_sources(proj):
    """[(objet, rôle)] posés sur le display : le bijou de l'étape 2, sinon les objets mémorisés par sélection."""
    if not uses_selection(proj):
        return part_meshes(proj)
    out, seen = [], set()
    for item in proj.preview_parts:
        obj = item.obj
        if obj is None or not obj.users_scene:
            continue
        for o in (iter_tree(obj) if obj.type == "EMPTY" else [obj]):
            if _placeable(o) and o.name not in seen:
                seen.add(o.name)
                out.append((o, "SELECTION"))
    return out


def capture_selection(context, proj):
    """Mémorise les maillages sélectionnés du projet comme bijou de l'aperçu ; renvoie leur nombre."""
    sel = selected_meshes(context)
    if sel:
        proj.preview_parts.clear()
        for obj in sel:
            proj.preview_parts.add().obj = obj
    return len(sel)


NOTHING_TO_PLACE = ("Aucune chaîne à poser : sélectionnez votre chaîne (et son pendentif) dans la scène du projet, "
                    "ou désignez-les à l'étape 2, puis recliquez « Mettre la chaîne sur le display ».")


def place(context, proj):
    """Bouton « Mettre la chaîne sur le display » : choisit quoi poser puis crée ou remplace la copie."""
    if proj.preview_scene is None:
        raise McsError("Chargez d'abord le display.")
    if uses_selection(proj):
        capture_selection(context, proj)
    if not preview_sources(proj):
        raise McsError(NOTHING_TO_PLACE)
    return refresh(context, proj)


def _remove_obj(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Camera):
            bpy.data.cameras.remove(data)


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


def _file_name(filepath):
    return os.path.basename(filepath.replace("\\", "/")).lower()


def _base_name(name):
    """Nom d'image sans le suffixe « .001 » ajouté par Blender quand le nom existe déjà dans le projet."""
    return re.sub(r"\.\d{3}$", "", name).lower()


def resolve_images(new_images, display_path, before_images):
    """Retrouve les textures du display.

    Ordre : chemin relatif au display ; même fichier déjà utilisé dans le projet ; même texture du projet
    (même nom), y compris une texture intégrée (packed) au projet, qui est alors réutilisée telle quelle.
    Retourne (retrouvées par chemin relatif, reprises du projet).
    """
    display_dir = os.path.dirname(display_path)
    project_files, project_packed, project_by_name = {}, {}, {}
    for img in before_images:
        if img.source not in {"FILE", "SEQUENCE", "TILED"}:
            continue
        if img.packed_file is not None:
            project_by_name.setdefault(img.name.lower(), img)
            if img.filepath:
                project_packed.setdefault(_file_name(img.filepath), img)
        elif img.filepath:
            path = abspath(img.filepath)
            if os.path.isfile(path):
                project_files.setdefault(os.path.basename(path).lower(), path)
                project_by_name.setdefault(img.name.lower(), img)
    by_relative, from_project = [], []
    for img in new_images:
        if img.packed_file is not None or img.source not in {"FILE", "SEQUENCE", "TILED"} or not img.filepath:
            continue
        if os.path.exists(abspath(img.filepath)):
            continue
        name = img.name
        if img.filepath.startswith("//"):
            candidate = _relative_to(img.filepath, display_dir)
            if os.path.exists(candidate):
                img.filepath = candidate
                img.reload()
                by_relative.append(name)
                continue
        file_name = _file_name(img.filepath)
        same = project_files.get(file_name)
        twin = None if same else (project_packed.get(file_name) or project_by_name.get(_base_name(img.name)))
        if twin is not None and twin.packed_file is None:
            same, twin = abspath(twin.filepath), None
        if same:
            img.filepath = same
            img.reload()
            from_project.append(name)
        elif twin is not None:
            img.user_remap(twin)          # la texture intégrée au projet remplace la copie introuvable
            from_project.append(name)
    return by_relative, from_project


def _is_missing(img):
    """Image utilisée dont le fichier est introuvable (une image remplacée par celle du projet n'a plus d'utilisateur)."""
    return (img.users > 0 and img.packed_file is None and img.source in {"FILE", "SEQUENCE", "TILED"}
            and bool(img.filepath) and not os.path.exists(abspath(img.filepath)))


def missing_image_list(proj):
    """Images du display (objets Blender) dont le fichier reste introuvable."""
    out = []
    for name in json.loads(proj.display_image_names or "[]"):
        img = bpy.data.images.get(name)
        if img is not None and _is_missing(img):
            out.append(img)
    return out


def missing_display_images(proj):
    """Images du display dont le fichier reste introuvable (texte affiché)."""
    return [f"Image : {img.name} ({img.filepath})" for img in missing_image_list(proj)]


def update_missing(proj):
    """Recalcule la liste des ressources manquantes (les bibliothèques liées absentes restent signalées)."""
    others = [m for m in json.loads(proj.display_missing or "[]") if not m.startswith("Image : ")]
    missing = missing_display_images(proj) + others
    proj.display_missing = json.dumps(missing)
    return missing


def _scan_missing(new_images, new_libs):
    missing = []
    for img in new_images:
        if _is_missing(img):
            missing.append(f"Image : {img.name} ({img.filepath})")
    for lib in new_libs:
        if not os.path.isfile(abspath(lib.filepath)):
            missing.append(f"Bibliothèque liée : {lib.filepath}")
    return missing


def load(context, proj, force=False):
    path = _check_file(proj)
    if proj.preview_scene is not None:
        if not force:
            raise McsError("Le display est déjà chargé : cliquez « Mettre la chaîne sur le display », ou « Recharger » "
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
    if preview_sources(proj):
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
    b = world_bounds([o for o, r in preview_sources(proj)])
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


_NODE_SETTINGS = ("uv_map", "layer_name", "attribute_name", "operation", "blend_type", "data_type", "interpolation",
                  "projection", "extension", "space", "clamp", "distribution", "subsurface_method")


def _socket_value(sock):
    value = getattr(sock, "default_value", None)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    try:
        return tuple(round(v, 6) for v in value)
    except TypeError:
        return str(value)


def material_signature(mat):
    """Empreinte d'un matériau : textures (fichier, espace colorimétrique), valeurs, réglages et liens des nœuds.

    Change dès que vous modifiez le matériau du projet (texture de diamants, bumpiness, Value Parameters…).
    """
    parts = [mat.name, tuple(mat.diffuse_color), mat.roughness, mat.metallic]
    tree = mat.node_tree
    if tree is not None:
        for node in sorted(tree.nodes, key=lambda n: n.name):
            parts += [node.name, node.bl_idname, node.mute]
            img = getattr(node, "image", None)
            if img is not None:
                parts += [img.name, img.filepath, img.source, img.colorspace_settings.name,
                          img.packed_file is not None]
            for attr in _NODE_SETTINGS:
                if hasattr(node, attr):
                    parts.append(getattr(node, attr))
            for sock in list(node.inputs) + list(node.outputs):
                parts.append(_socket_value(sock))
        for link in tree.links:
            parts.append(f"{link.from_node.name}.{link.from_socket.identifier}>"
                         f"{link.to_node.name}.{link.to_socket.identifier}")
    return hash_strings(parts)


def _preview_material(proj, mat):
    """Copie d'aperçu du matériau. Une copie retouchée n'est gardée que si le matériau du projet n'a pas changé."""
    if mat is None:
        return None
    sig = material_signature(mat)
    if proj.preview_keep_materials:
        for m in bpy.data.materials:
            if (m.get(TAG_PROJECT) == proj.project_id and m.get(TAG_PREVIEW) and m.get(SRC) == mat.name
                    and m.get(SRC_SIG) == sig):
                return m
    copy = mat.copy()
    copy.name = f"Apercu_{mat.name}"
    tag(copy, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "material", SRC: mat.name, SRC_SIG: sig})
    return copy


def _purge_preview_materials(proj):
    """Retire les copies d'aperçu de matériaux devenues inutiles (périmées et plus utilisées)."""
    mine = [m for m in bpy.data.materials if m.get(TAG_PROJECT) == proj.project_id and m.get(TAG_PREVIEW)]
    for m in mine:
        if m.users == 0:
            bpy.data.materials.remove(m)
    for m in bpy.data.materials:            # noms propres : « Apercu_<matériau> » sans .001 quand c'est possible
        if m.get(TAG_PROJECT) == proj.project_id and m.get(TAG_PREVIEW) and m.get(SRC):
            wanted = f"Apercu_{m[SRC]}"
            if m.name != wanted and wanted not in bpy.data.materials:
                m.name = wanted


def preview_signature(proj):
    parts = [proj.preview_anchor]
    for obj, role in preview_sources(proj):
        parts.append(role)
        parts.extend(object_signature(obj))
        if obj.type == "MESH":
            parts.extend(material_signature(m) if m else "-" for m in obj.data.materials)
    return hash_strings(parts)


def refresh(context, proj):
    """Crée ou remplace la copie du bijou dans la scène d'aperçu, sans recharger le display."""
    if proj.preview_scene is None:
        raise McsError("Chargez d'abord le display.")
    if proj.preview_marker is None:
        set_marker(proj, auto_marker(proj.preview_scene)[0])
    comps = preview_sources(proj)
    if not comps:
        raise McsError(NOTHING_TO_PLACE)
    for obj, role in comps:
        if obj.mode == "EDIT":
            obj.update_from_editmode()      # le maillage copié = ce que vous voyez en Edit Mode
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
    _purge_preview_materials(proj)
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

CLOSEUP_MARGIN = 1.3        # la chaîne occupe environ 1/1,3 du cadre en gros plan
DETAIL_MIN_PX_CM = 30       # en dessous, un diamant de 1 mm fait moins de 3 px : invisible


def _copies_corners(proj):
    pts = []
    for c in preview_objects(proj, "copy"):
        pts += [c.matrix_world @ Vector(v) for v in c.bound_box]
    return pts


def _render_size(proj):
    f = proj.render_percent / 100
    return max(1, round(proj.render_res_x * f)), max(1, round(proj.render_res_y * f))


def closeup_camera(proj):
    """Caméra « gros plan » : même angle et même objectif que la caméra du display, recadrée sur la chaîne.

    Créée dans la scène d'aperçu (jamais exportée) et recadrée à chaque utilisation ; la caméra du display
    n'est pas modifiée.
    """
    scene = proj.preview_scene
    base = proj.render_camera
    if scene is None:
        raise McsError("Chargez d'abord le display.")
    if base is None or base.type != "CAMERA" or base.name not in scene.objects:
        raise McsError("Choisissez une caméra de la scène d'aperçu (Options ▸ Rendu).")
    view_layer = scene.view_layers[0]
    view_layer.update()
    pts = _copies_corners(proj)
    if not pts:
        raise McsError("Cliquez d'abord « Mettre la chaîne sur le display ».")
    cam = next(iter(preview_objects(proj, "closeup")), None)
    data = base.data.copy()
    data.name = "MCS_Gros_Plan"
    if cam is None:
        cam = bpy.data.objects.new("MCS_Camera_Gros_Plan", data)
        tag(cam, proj, role="apercu", **{TAG_PREVIEW: 1, KIND: "closeup"})
        _preview_collection(proj).objects.link(cam)
    else:
        old = cam.data
        cam.data = data
        if old is not None and old.users == 0:
            bpy.data.cameras.remove(old)
    cam.parent = None
    loc, rot, _scale = base.matrix_world.decompose()
    cam.matrix_world = Matrix.LocRotScale(loc, rot, Vector((1.0, 1.0, 1.0)))
    center = sum(pts, Vector()) / len(pts)
    fit = [center + (p - center) * CLOSEUP_MARGIN for p in pts]
    r = scene.render
    saved = r.resolution_x, r.resolution_y, r.resolution_percentage
    try:
        r.resolution_x, r.resolution_y, r.resolution_percentage = proj.render_res_x, proj.render_res_y, 100
        view_layer.update()
        co, ortho_scale = cam.camera_fit_coords(view_layer.depsgraph, [v for p in fit for v in p])
    finally:
        r.resolution_x, r.resolution_y, r.resolution_percentage = saved
    cam.location = co
    if data.type == "ORTHO":
        data.ortho_scale = ortho_scale
    dist = (center - Vector(co)).length
    data.clip_start = min(data.clip_start, max(dist * 0.05, 1e-4))
    data.dof.focus_object = None
    data.dof.focus_distance = dist
    view_layer.update()
    return cam


def detail_estimate(proj, cam):
    """Taille de la chaîne sur l'image : (largeur px, hauteur px, px par cm) ou None. Lecture seule."""
    scene = proj.preview_scene
    if scene is None or cam is None or cam.type != "CAMERA":
        return None
    pts = _copies_corners(proj)
    if not pts:
        return None
    rx, ry = _render_size(proj)
    pm = cam.calc_matrix_camera(scene.view_layers[0].depsgraph, x=rx, y=ry)
    view = cam.matrix_world.inverted()
    xs, ys = [], []
    for p in pts:
        v = pm @ (view @ p).to_4d()
        if v.w > 1e-9:
            xs.append((v.x / v.w + 1) / 2 * rx)
            ys.append((v.y / v.w + 1) / 2 * ry)
    if not xs:
        return None
    w = max(0.0, min(max(xs), rx) - max(min(xs), 0))
    h = max(0.0, min(max(ys), ry) - max(min(ys), 0))
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    extent_cm = max(hi - lo) * scene.unit_settings.scale_length * 100
    return w, h, (max(w, h) / extent_cm if extent_cm > 1e-9 else 0.0)


def detail_message(est):
    """(texte, assez de détail ?) pour une estimation detail_estimate."""
    w, h, ppc = est
    text = f"Chaîne sur l'image : environ {w:.0f} × {h:.0f} px ({ppc:.0f} px par cm)."
    if ppc < DETAIL_MIN_PX_CM:
        return (text + " Trop petit pour voir les diamants et paillettes : activez « Gros plan sur la chaîne » "
                       "ou augmentez la résolution."), False
    return text, True


def texture_limit(scene):
    """Limite de taille des textures imposée par le display (Simplify de Cycles), sinon None."""
    if scene.render.use_simplify and scene.render.engine == "CYCLES":
        limit = getattr(getattr(scene, "cycles", None), "texture_limit_render", "OFF")
        if limit and limit != "OFF":
            return limit
    return None

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
        raise McsError("Cliquez d'abord « Mettre la chaîne sur le display ».")
    if proj.render_closeup:
        cam = closeup_camera(proj)
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
    if proj.render_closeup:
        mode += "_gros_plan"
    base_name = f"{proj.output_name.strip().replace('^', '_') or 'bijou'}_{mode}_{stamp}"
    target, n = os.path.join(out_dir, base_name), 2
    while os.path.exists(target + ".png"):          # deux rendus dans la même seconde : aucun écrasement
        target, n = os.path.join(out_dir, f"{base_name}_{n}"), n + 1
    try:
        scene.camera = cam
        r.resolution_x, r.resolution_y = proj.render_res_x, proj.render_res_y
        r.resolution_percentage = proj.render_percent       # même résolution en rapide : détails visibles
        if proj.render_mode == "QUICK" and owner:
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
    notes, enough = [], True
    est = detail_estimate(proj, cam)
    if est is not None:
        text, enough = detail_message(est)
        notes.append(("Gros plan. " if proj.render_closeup else "") + text)
    limit = texture_limit(scene)
    if limit:
        enough = False
        notes.append(f"Le display limite les textures à {limit} px (Propriétés de rendu ▸ Simplify ▸ "
                     f"Texture Limit) : les détails fins sont réduits.")
    proj.render_note = " ".join(notes)
    return out, enough


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
        msg += (f" Chaîne posée ({placed} pièce(s))." if placed else
                " Sélectionnez votre chaîne dans le projet puis cliquez « Mettre la chaîne sur le display ».")
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
    bl_label = "Mettre la chaîne sur le display"
    bl_description = ("Pose une copie de votre chaîne dans la scène du display, sur le repère : le bijou de "
                      "l'étape 2, sinon les maillages sélectionnés dans la scène du projet. Recliquez pour "
                      "l'actualiser (le display n'est pas rechargé)")
    bl_options = {"REGISTER", "UNDO"}

    show: bpy.props.BoolProperty(name="Afficher le display", default=True, options={"SKIP_SAVE"})

    def execute(self, context):
        proj = get_project(context)
        try:
            copies = place(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if self.show and context.window is not None and context.window.scene != proj.preview_scene:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            context.window.scene = proj.preview_scene
        names = ", ".join(c[SRC] for c in copies[:3]) + ("…" if len(copies) > 3 else "")
        self.report({"INFO"}, f"Chaîne posée sur le display : {len(copies)} pièce(s) ({names}).")
        return {"FINISHED"}


class MIO_OT_display_find_textures(bpy.types.Operator):
    bl_idname = "mio_chain.display_find_textures"
    bl_label = "Rechercher les textures manquantes…"
    bl_description = ("Choisissez le dossier de vos textures (ou n'importe quel fichier dedans) : Blender y cherche, "
                      "sous-dossiers compris, les fichiers manquants portant le même nom")
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})
    filepath: bpy.props.StringProperty(subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})
    # Le sélecteur montre les dossiers ET les images (DDS compris), pour reconnaître le bon dossier.
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_glob: bpy.props.StringProperty(default=IMAGE_GLOB, options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        proj = get_project(context)
        folder = abspath(self.directory) if self.directory else os.path.dirname(abspath(self.filepath))
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, f"Dossier introuvable : {folder}")
            return {"CANCELLED"}
        before = len(missing_image_list(proj))
        bpy.ops.file.find_missing_files(directory=os.path.join(folder, ""))
        for name in json.loads(proj.display_image_names or "[]"):
            img = bpy.data.images.get(name)
            if img is not None and img.filepath and os.path.exists(abspath(img.filepath)):
                img.reload()
        update_missing(proj)
        left = missing_image_list(proj)
        found = before - len(left)
        if left:
            self.report({"WARNING"}, f"{found} texture(s) retrouvée(s) ; encore introuvable(s) : "
                                     f"{', '.join(i.name for i in left[:3])}. Aucun fichier de ce nom dans le "
                                     f"dossier : utilisez « Choisir… » à côté de la texture.")
        else:
            self.report({"INFO"}, f"{found} texture(s) retrouvée(s) : plus aucune texture manquante.")
        return {"FINISHED"}


def _nearest_folder(path):
    """Dossier existant le plus proche d'un chemin introuvable (pour ouvrir le sélecteur au bon endroit)."""
    folder = os.path.dirname(path)
    while folder and not os.path.isdir(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            return ""
        folder = parent
    return folder


class MIO_OT_display_relink_texture(bpy.types.Operator):
    bl_idname = "mio_chain.display_relink_texture"
    bl_label = "Choisir le fichier…"
    bl_description = ("Indiquez vous-même le fichier de cette texture (DDS, PNG, JPG, TGA…), "
                      "même s'il porte un autre nom")
    bl_options = {"REGISTER", "UNDO"}

    image_name: bpy.props.StringProperty(options={"HIDDEN"})
    filepath: bpy.props.StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_glob: bpy.props.StringProperty(default=IMAGE_GLOB, options={"HIDDEN"})

    def invoke(self, context, event):
        img = bpy.data.images.get(self.image_name)
        if img is not None and img.filepath:
            path = abspath(img.filepath)
            if os.sep == "/":
                path = path.replace("\\", "/")
            folder = _nearest_folder(path)
            if folder:
                self.filepath = os.path.join(folder, os.path.basename(path))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        proj = get_project(context)
        img = bpy.data.images.get(self.image_name)
        if img is None:
            self.report({"ERROR"}, f"Texture « {self.image_name} » absente du fichier.")
            return {"CANCELLED"}
        path = abspath(self.filepath)
        if not os.path.isfile(path):
            self.report({"ERROR"}, f"Fichier introuvable : {path}")
            return {"CANCELLED"}
        if not path.lower().endswith(IMAGE_EXTS):
            self.report({"ERROR"}, "Choisissez un fichier image (DDS, PNG, JPG, TGA, TIF…).")
            return {"CANCELLED"}
        img.filepath = path
        img.reload()
        update_missing(proj)
        readable = img.size[0] > 0 and img.size[1] > 0
        if not readable:
            self.report({"WARNING"}, f"{img.name} relié à {os.path.basename(path)}, mais Blender n'arrive pas à "
                                     f"lire ce fichier : il apparaîtra rose au rendu.")
        else:
            self.report({"INFO"}, f"{img.name} → {os.path.basename(path)} ({img.size[0]}×{img.size[1]}).")
        return {"FINISHED"}


class MIO_OT_preview_move(bpy.types.Operator):
    bl_idname = "mio_chain.preview_move"
    bl_label = "Déplacer la chaîne"
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
    bl_description = ("Ouvre la scène d'aperçu et regarde par la caméra choisie (ou par le gros plan, "
                      "s'il est activé)")

    def execute(self, context):
        proj = get_project(context)
        scene, cam = proj.preview_scene, proj.render_camera
        if scene is None or cam is None:
            self.report({"ERROR"}, "Chargez le display et choisissez une caméra.")
            return {"CANCELLED"}
        if context.window is None:
            self.report({"ERROR"}, "Aucune fenêtre Blender (mode sans interface).")
            return {"CANCELLED"}
        if proj.render_closeup:
            try:
                cam = closeup_camera(proj)
            except McsError as exc:
                self.report({"ERROR"}, str(exc))
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
    bl_description = ("Rend la scène d'aperçu avec la caméra du display (ou en gros plan sur la chaîne) et "
                      "enregistre l'image (Blender est occupé pendant le rendu)")

    mode: bpy.props.EnumProperty(items=[("CURRENT", "Réglage actuel", ""), ("QUICK", "Rapide", ""),
                                        ("FINAL", "Final", "")], default="CURRENT", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        proj = get_project(context)
        if self.mode != "CURRENT":
            proj.render_mode = self.mode
        try:
            out, enough = render(context, proj)
        except McsError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        stale = proj.preview_signature != preview_signature(proj)
        msg = f"Rendu enregistré : {out}"
        if stale:
            msg += " (aperçu périmé : actualisez la chaîne sur le display avant le rendu final)."
        if proj.render_note:
            msg += " " + proj.render_note
        self.report({"WARNING"} if stale or not enough else {"INFO"}, msg)
        return {"FINISHED"}


CLASSES = (MIO_OT_display_analyse, MIO_OT_display_load, MIO_OT_marker_set, MIO_OT_marker_save,
           MIO_OT_preview_refresh, MIO_OT_display_find_textures, MIO_OT_display_relink_texture, MIO_OT_preview_move, MIO_OT_view_camera, MIO_OT_back_to_project, MIO_OT_render)
