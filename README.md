# Mio Chain Studio

Addon Blender pour préparer **vos propres pendentifs et chaînes FiveM** avec **Sollumz**, depuis un panneau simple en français : onglet **« Mio Chain »** de la barre latérale de la vue 3D (touche `N`).

| Élément | Version |
|---|---|
| Blender | **5.2** (vérifié avec 5.2.3 LTS) |
| Sollumz | **2.9.0** (dernière version publiée, vérifiée) avec sa dépendance `szio` |
| Addon | 0.2.0 |

## Installation

1. Installez et activez **Sollumz 2.9.0** et ses dépendances (préférences de Sollumz → *Install dependencies*).
2. Blender → **Édition → Préférences → Extensions** → menu **⌄** → **Installer depuis le disque…** → `dist/mio_chain_studio-0.2.0.zip`.
3. Extrayez **Teef.zip** en conservant son arborescence :
   ```
   Teef/
     mp_m_freemode_01.yft.xml
     teef_000_u.ydd.xml
     teef_000_u/teef_normal_001.dds
     teef_000_u/teef_spec_000.dds
   ```
4. Dans l'onglet **Mio Chain**, choisissez ce dossier **Teef** puis cliquez 🔍. Les quatre fichiers sont vérifiés et le chemin est mémorisé.

Les fichiers de Teef.zip (références GTA et textures) **ne sont pas publiés** dans ce dépôt : l'addon les lit depuis votre dossier local.

## Les huit étapes

Chaque section affiche un statut **À faire / À vérifier / Terminé**, recalculé à partir de l'état réel de la scène, ainsi que les problèmes détectés et leur correction. Les opérations qui modifient la scène peuvent être annulées (`Ctrl+Z`). Rien d'extérieur au projet n'est supprimé.

### 1 — Préparation des SVG
1. Importez votre SVG (**Fichier → Importer → SVG**) et sélectionnez les courbes.
2. Affectez les couches :
   - **Détecter les couches** utilise les hauteurs initiales si elles sont distinctes.
   - Si toutes les courbes sont à la même hauteur, l'addon ne devine rien : utilisez les boutons **1 / 2 / 3** ou le champ de chaque courbe. Plusieurs courbes peuvent partager une couche.
3. Cliquez **Préparer les SVG sélectionnés**. L'addon :
   - retire les matériaux noirs et leurs affectations, en gardant toute la géométrie (même les formes noires) et les autres matériaux ;
   - convertit les courbes en maillages et donne leur épaisseur aux couches : 0,05 m, 0,025 m et 0,015 m par défaut, modifiables ;
   - empile les couches le long de **+Z** (direction réglable), dos de la couche 2 contre l'avant de la couche 1, sans espace par défaut ;
   - mesure les épaisseurs réelles et le contact entre couches.

Les courbes d'origine sont conservées, masquées, comme source. Un nouveau clic repart d'elles : ni épaisseur cumulée, ni doublon.

### 2 — Chaîne et composants
- Choisissez un **.obj**, réglez l'échelle et les axes, puis **Importer ma chaîne**. Matériaux et UV importés sont conservés.
- Si l'import échoue, la chaîne précédente est gardée.
- **Sélection = chaîne / pendentif** désigne des objets déjà présents dans la scène.
- La liste distingue la chaîne et le pendentif. Retirer un élément de la liste ne le supprime pas de la scène.

### 3 — Matériaux Sollumz sur les faces sélectionnées
1. En **Edit Mode**, sélectionnez des faces.
2. Choisissez le type :
   - **Ped — sans glow** → `ped.sps` ;
   - **Ped Emissive — avec glow** → `ped_emissive.sps`.

   Ces noms techniques sont vérifiés dans Sollumz 2.9.0 et modifiables dans « Correspondance des choix ».
3. Choisissez le mode :
   - **Preset** : shader, textures et paramètres viennent du preset ;
   - **Personnalisé** : DiffuseSampler à votre choix. BumpSampler et SpecSampler sont par défaut `teef_normal_001.dds` et `teef_spec_000.dds`.
4. **Appliquer aux faces sélectionnées**. Le bouton :
   - crée ou réutilise le matériau ;
   - l'assigne à ces faces uniquement ;
   - active **Embedded** pour Bump et Spec, et met Bump en **Non-Color** ;
   - fait une **Cube Projection** sur ces faces seulement (réglages exposés).

   Embedded de la Diffuse reste réglable. Une image partagée avec un autre matériau n'est pas modifiée : l'addon en charge une copie.

### 4 — Value Parameters et presets
- Les paramètres du shader du matériau actif sont affichés et modifiables.
- Presets : **Enregistrer**, **Appliquer**, **Dupliquer**, **Supprimer**.
- Un preset enregistre le shader, les chemins de textures, Embedded, l'espace colorimétrique et les paramètres.
- Les presets sont stockés en JSON dans le dossier de configuration de Blender et restent disponibles après fermeture.
- Un preset dont une texture manque est marqué **incomplet** ; **Relocaliser** permet de choisir le nouveau fichier.

### 5 — Color Attributes
- **Configurer les Color Attributes** crée ou remplit, en *Face Corner / Byte Color* :
  - **Color 1** : `#FF8000`, alpha 1 ;
  - **Color 2** : `#000000`, alpha 0.
- Ce sont les noms et l'ordre utilisés par Sollumz (Colour0 / Colour1).
- Les autres attributs sont conservés. Seul un attribut de mauvais domaine ou de mauvais type est remplacé.
- Le bouton demande confirmation avant d'effacer une peinture existante.

### 6 — Note pour le glow
En mode émissif, le panneau affiche le rappel de peinture (couleur principale `#FFBAFF`, secondaire noire, sélection des faces, `Ctrl + X`).
- **Raccourci vérifié** dans le keymap par défaut de Blender 5.2 : *Paint ▸ Set Vertex Colors* (`paint.vertex_color_set`).
- Un bouton active Color 1 et passe en Vertex Paint. **Rien n'est peint automatiquement**, et l'étape 5 n'est jamais relancée d'elle-même.

### 7 — Rigging sur SKEL_Spine3
**Rigger sur SKEL_Spine3** crée une **copie** (`MCS_Bijou_Final`) : vos sources restent modifiables. Le bouton :
- réunit uniquement les composants désignés en un seul Mesh Object ;
- conserve placement, matériaux, UV et Color Attributes ;
- assigne tous les sommets au groupe `SKEL_Spine3` avec un poids de 1, par l'API ;
- retire les autres groupes ;
- lie le mesh au squelette masculin fourni (modificateur Armature).

**Contrôler en Weight Paint** permet la vérification visuelle.

### 8 — Modèle d'export et remplacement du mesh
1. **Charger les références Teef** : Sollumz importe `teef_000_u.ydd.xml` avec `mp_m_freemode_01.yft.xml` comme squelette externe (mode « Saved »). On obtient `REF_teef_000_u` (armature, 128 os) > `REF_teef_012_u` > `SKEL_ROOT` (mesh).
2. **Préparer le modèle d'export** : copie de cette structure sous **vos** noms (fichier YDD et drawable, `teef_000_u` par défaut, pas `teef_012_u`).
3. **Remplacer le mesh de référence par mon bijou** :
   - le mesh de référence est repéré dans la **nouvelle hiérarchie** (ou choisi explicitement), jamais d'après son seul nom ;
   - le bijou prend sa place : même parent, type Sollumz, skinning et liaison au squelette, position monde inchangée ;
   - la structure est vérifiée **avant** de retirer le mesh de référence de la copie. Os et armature ne sont jamais touchés.
   - **LOD** : *High uniquement* (Medium et Low vides) ou *High copié en Medium et Low*. Cette seconde option est affichée comme **non optimisée**.
4. **Vérifier avant export**, puis **Exporter avec Sollumz**. Les fichiers produits sont relus :
   - drawable et nom de sortie ;
   - LOD exportés ;
   - 100 % des sommets sur l'os 38 (SKEL_Spine3) ;
   - squelette exclu ;
   - DDS Bump et Spec intégrés.

Un export Blender réussi **ne valide pas** le bijou dans FiveM : testez-le en jeu.

## Aperçu sur mon display
Section séparée :
- choix et chargement de votre `.blend`, dans une scène à part (éclairage, matériaux et caméras préservés) ;
- **repère réglable**, enregistrable pour les projets suivants ;
- copie indépendante du bijou, **actualisable** sans doublon ;
- **Voir par la caméra** et **Lancer le rendu** (aperçu rapide ou final).

Le display, ses lumières, ses caméras et les copies d'aperçu sont exclus de l'export.

## Code

```
mio_chain_studio/        Extension Blender (contenu du ZIP)
  svg.py                 Étape 1   components.py  Étape 2
  materials.py           Étapes 3-4  presets.py   Presets JSON
  colors.py              Étapes 5-6  rigging.py   Étape 7
  teef.py                Références Teef (vérification, import Sollumz)
  export.py              Étape 8   display.py     Aperçu
  sollumz_bridge.py      Accès à Sollumz installé (aucun export GTA séparé)
  status.py  ui.py  props.py  prefs.py  utils.py  dds.py
tests/run_tests.py       Tests de bout en bout dans Blender + Sollumz
tools/build_zip.py       ZIP via l'outil officiel de Blender
```

```bash
python tools/build_zip.py <bpy>/5.2/scripts/addons_core/bl_pkg/cli/blender_ext.py
```

```bash
python -I tests/run_tests.py -- /tmp/mcs_test /chemin/vers/Teef
```

Résultats, limites et tests restants : [docs/LIMITES_ET_TESTS.md](docs/LIMITES_ET_TESTS.md).

Licence : GPL-3.0-or-later.
