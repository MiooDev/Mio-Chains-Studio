# Mio Chain Studio

Addon Blender pour créer et préparer des chaînes personnalisées FiveM :
texte → pendentif 3D → chaîne importée → préparation FiveM → aperçu sur votre display → vérification et export avec **Sollumz**.

Interface entièrement en français, onglet **« Mio Chain »** de la barre latérale de la vue 3D (touche `N`).

| | |
|---|---|
| Blender | **5.2** (testé avec 5.2.3 LTS) |
| Sollumz | **2.9.0** (testé), avec sa dépendance `szio` installée |
| Chaînes importées | `.obj` |
| Encodeur DDS (facultatif) | `texconv` (DirectXTex) ou ImageMagick |

## Installation

1. Installez et activez **Sollumz 2.9.0**, puis ses dépendances (Préférences de Sollumz → *Install dependencies*).
2. Dans Blender : **Édition → Préférences → Extensions**, menu **⌄** en haut à droite → **Installer depuis le disque…**,
   puis choisissez `dist/mio_chain_studio-0.1.0.zip`. Vous pouvez aussi glisser-déposer le ZIP dans Blender.
3. Vérifiez que **Mio Chain Studio** est coché.
4. Facultatif, pour convertir l'atlas en DDS : téléchargez `texconv.exe` (projet Microsoft DirectXTex, gratuit),
   puis indiquez son chemin dans les préférences de l'addon. Sans encodeur, l'atlas reste en PNG et l'étape restante est indiquée.
5. Ouvrez la vue 3D, appuyez sur `N` et choisissez l'onglet **Mio Chain**.

## Documentation

- [Guide du parcours utilisateur](docs/GUIDE_UTILISATEUR.md)
- [Dépendances, limites connues, ce qui a été testé](docs/LIMITES_ET_TESTS.md)
- [Informations manquantes à fournir](docs/INFORMATIONS_MANQUANTES.md)

## Organisation du code

```
mio_chain_studio/          Extension Blender (contenu du ZIP)
  blender_manifest.toml    Manifeste de l'extension (Blender ≥ 5.2)
  __init__.py              Enregistrement
  props.py                 Propriétés du projet (enregistrées dans le .blend)
  prefs.py                 Préférences : seuils, encodeurs DDS, repères de display
  utils.py                 Étiquettes de projet, suppression sûre, signatures, triangles
  sollumz_bridge.py        Accès à Sollumz installé (shaders, YTD, export) — aucun export GTA séparé
  pendant.py               Texte → texte 3D, plaque, bélière
  assembly.py              Structure, import OBJ, rôles, assemblage
  materials.py             Matériaux Sollumz, textures, préréglages JSON
  atlas.py                 Atlas d'images, UV d'atlas, DDS, YTD
  dds.py                   Encodeur externe + lecture/vérification d'en-tête DDS
  effects.py               Émissif (paramètre vérifié), couleurs de sommets
  rigging.py               Armature, poids réversibles, vérifications, test de déformation
  display.py               Aperçu sur le display (scène séparée), repère, rendu
  export.py                Copie d'export, rapport, export Sollumz, checklist CodeWalker
  status.py                Statuts « À faire / À vérifier / Terminé » calculés sur l'état réel
  ui.py                    Panneaux
tests/run_tests.py         Tests de bout en bout dans Blender + Sollumz (données synthétiques)
tests/make_display.py      Génère un display synthétique pour les tests
tools/build_zip.py         Construit le ZIP avec l'outil officiel de Blender
dist/                      ZIP installable
```

## Construire et tester

```bash
python tools/build_zip.py <bpy>/5.2/scripts/addons_core/bl_pkg/cli/blender_ext.py
```

```bash
python -I tests/run_tests.py -- /tmp/mcs_test [chemin/vers/teef_000_u.ydd.xml]
```

Les tests nécessitent le module `bpy` 5.2 (ou Blender en ligne de commande), avec Sollumz 2.9.0 et l'addon installés dans le dépôt
d'extensions `user_default`. Dernier résultat : **129/129 vérifications réussies** (détail dans `docs/LIMITES_ET_TESTS.md`).

Licence : GPL-3.0-or-later (obligatoire pour un addon Blender).
