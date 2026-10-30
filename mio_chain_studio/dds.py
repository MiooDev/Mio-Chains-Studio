"""Conversion DDS par un encodeur externe réel (texconv ou ImageMagick) et vérification de l'en-tête.

Blender ne sait pas écrire de DDS et Sollumz 2.9 n'en encode pas : sans encodeur, l'atlas reste en PNG
et l'étape restante est indiquée. Renommer un .png en .dds n'est jamais une conversion.
"""

import math
import os
import shutil
import struct
import subprocess
import sys

import bpy

from .prefs import addon_prefs
from .utils import McsError, abspath

DXGI_NAMES = {71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 77: "BC3_UNORM", 78: "BC3_UNORM_SRGB",
              98: "BC7_UNORM", 99: "BC7_UNORM_SRGB", 28: "R8G8B8A8_UNORM", 87: "B8G8R8A8_UNORM"}
EXPECTED = {"DXT1": {"DXT1", "BC1_UNORM", "BC1_UNORM_SRGB"},
            "DXT5": {"DXT5", "BC3_UNORM", "BC3_UNORM_SRGB"},
            "BC7": {"BC7_UNORM", "BC7_UNORM_SRGB"}}
TEXCONV_FORMATS = {"DXT1": "BC1_UNORM", "DXT5": "BC3_UNORM", "BC7": "BC7_UNORM"}


def read_header(path):
    """Lit l'en-tête DDS. Retourne {width, height, mips, format}. Lève McsError si invalide."""
    try:
        with open(path, "rb") as f:
            head = f.read(148)
    except OSError as exc:
        raise McsError(f"DDS illisible : {exc}") from exc
    if len(head) < 128 or head[:4] != b"DDS ":
        raise McsError(f"{os.path.basename(path)} n'est pas un fichier DDS (signature absente).")
    size, flags, height, width, pitch, depth, mips = struct.unpack_from("<7I", head, 4)
    if size != 124:
        raise McsError(f"{os.path.basename(path)} : en-tête DDS invalide.")
    pf_flags = struct.unpack_from("<I", head, 80)[0]
    fourcc = head[84:88].decode("ascii", "replace")
    if pf_flags & 0x4:
        fmt = fourcc
        if fourcc == "DX10" and len(head) >= 132:
            dxgi = struct.unpack_from("<I", head, 128)[0]
            fmt = DXGI_NAMES.get(dxgi, f"DXGI_{dxgi}")
    else:
        fmt = "non compressé"
    return {"width": width, "height": height, "mips": max(1, mips), "format": fmt}


def verify(path, expected_size=None, expected_format=None):
    """Vérifie un DDS ; retourne (info, liste de problèmes)."""
    issues = []
    if not path or not os.path.isfile(path):
        return None, [("ERROR", f"Fichier DDS introuvable : {path}", "")]
    try:
        info = read_header(path)
    except McsError as exc:
        return None, [("ERROR", str(exc), "Convertissez l'image avec un vrai encodeur DDS.")]
    if expected_size and (info["width"], info["height"]) != tuple(expected_size):
        issues.append(("ERROR", f"DDS {info['width']}×{info['height']} au lieu de "
                                f"{expected_size[0]}×{expected_size[1]}.", "Reconvertissez l'atlas actuel."))
    if expected_format and info["format"] not in EXPECTED.get(expected_format, {expected_format}):
        issues.append(("WARNING", f"Format DDS {info['format']} au lieu de {expected_format}.", ""))
    if info["width"] % 4 or info["height"] % 4:
        issues.append(("WARNING", "Dimensions non multiples de 4 : compression par blocs incorrecte.", ""))
    return info, issues


def _is_imagemagick(exe):
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return "ImageMagick" in (out.stdout + out.stderr)


_encoders_cache = {"value": None}


def find_encoders(refresh=False):
    """[(nom, chemin)] des encodeurs DDS réellement utilisables (résultat mis en cache)."""
    if _encoders_cache["value"] is not None and not refresh:
        return _encoders_cache["value"]
    prefs = addon_prefs()
    found = []
    tex = abspath(prefs.texconv_path) if prefs and prefs.texconv_path else None
    tex = tex if tex and os.path.isfile(tex) else (shutil.which("texconv") or shutil.which("texconv.exe"))
    if tex:
        found.append(("texconv", tex))
    mag = abspath(prefs.magick_path) if prefs and prefs.magick_path else None
    candidates = [mag] if mag and os.path.isfile(mag) else [shutil.which("magick")]
    if sys.platform != "win32":  # « convert » sous Windows est un outil système sans rapport
        candidates.append(shutil.which("convert"))
    for exe in candidates:
        if exe and _is_imagemagick(exe):
            found.append(("ImageMagick", exe))
            break
    _encoders_cache["value"] = found
    return found


def convert(src_png, fmt="DXT5", mipmaps=True):
    """Convertit `src_png` en DDS à côté de lui ; retourne (chemin, info, encodeur)."""
    if not os.path.isfile(src_png):
        raise McsError(f"Image source introuvable : {src_png}")
    encoders = find_encoders(refresh=True)
    if not encoders:
        raise McsError("Aucun encodeur DDS trouvé (texconv ou ImageMagick). L'atlas PNG est prêt : "
                       "convertissez-le avec l'outil de votre choix, puis indiquez le fichier .dds.")
    out_dir = os.path.dirname(src_png)
    out = os.path.splitext(src_png)[0] + ".dds"
    errors = []
    for name, exe in encoders:
        if fmt == "BC7" and name != "texconv":
            errors.append("BC7 n'est disponible qu'avec texconv.")
            continue
        if name == "texconv":
            cmd = [exe, "-nologo", "-y", "-f", TEXCONV_FORMATS[fmt], "-m", "0" if mipmaps else "1", "-o", out_dir, src_png]
        else:
            w = h = 0
            try:
                w, h = bpy.data.images.load(src_png, check_existing=True).size
            except RuntimeError:
                pass
            levels = int(math.log2(max(1, min(w, h)))) if mipmaps and w and h else 0
            cmd = [exe, src_png, "-define", f"dds:compression={fmt.lower()}",
                   "-define", f"dds:mipmaps={levels}", out]
        if os.path.exists(out):
            os.remove(out)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{name} : {exc}")
            continue
        if res.returncode != 0 or not os.path.isfile(out):
            errors.append(f"{name} a échoué : {(res.stderr or res.stdout).strip()[:300]}")
            continue
        info = read_header(out)
        return out, info, name
    raise McsError("Conversion DDS impossible. " + " ".join(errors))
