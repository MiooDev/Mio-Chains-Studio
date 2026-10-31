"""Lecture et vérification de l'en-tête des fichiers DDS (aucune conversion : renommer n'est pas convertir)."""

import os
import struct

from .utils import McsError, abspath

DXGI_NAMES = {71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 77: "BC3_UNORM", 78: "BC3_UNORM_SRGB",
              98: "BC7_UNORM", 99: "BC7_UNORM_SRGB", 28: "R8G8B8A8_UNORM", 87: "B8G8R8A8_UNORM"}
EXPECTED = {"DXT1": {"DXT1", "BC1_UNORM", "BC1_UNORM_SRGB"},
            "DXT5": {"DXT5", "BC3_UNORM", "BC3_UNORM_SRGB"},
            "BC7": {"BC7_UNORM", "BC7_UNORM_SRGB"}}


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
