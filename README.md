# Mio Chain Studio

Addon Blender pour préparer **vos propres pendentifs et chaînes FiveM** avec **Sollumz**, depuis un panneau simple en français : onglet **« Mio Chain »** de la barre latérale de la vue 3D (touche `N`).

| Élément | Version |
|---|---|
| Blender | **5.2** (vérifié avec 5.2.3 LTS) |
| Sollumz | **2.9.0** (dernière version publiée, vérifiée) avec sa dépendance `szio` |
| Addon | 0.3.2 |

## Installation

1. Installez et activez **Sollumz 2.9.0** et ses dépendances (préférences de Sollumz → *Install dependencies*).
2. Blender → **Édition → Préférences → Extensions** → menu **⌄** → **Installer depuis le disque…** → `dist/mio_chain_studio-0.3.2.zip`.
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
   - convertit les courbes en maillages et donne leur épaisseur aux couches : 0,02 m, 0,01 m et 0,005 m par défaut, modifiables ;
   - empile les couches le long de **+Z** (direction réglable), dos de la couche 2 contre l'avant de la couche 1, sans espace par défaut ;
   - mesure les épaisseurs réelles et le contact entre couches, puis contrôle les faces de dos et d'avant sur leur plan, la surface du dessin et l'orientation des faces.

Les faces de surface nulle, que Blender crée quand plusieurs points d'un tracé sont alignés, sont conservées et signalées. La préparation est « tout ou rien » : si une vérification échoue, rien n'est modifié.

Les courbes d'origine sont conservées, masquées, comme source. Un nouveau clic repart d'elles, ainsi que des autres courbes déjà préparées du projet pour garder un empilement cohérent : ni épaisseur cumulée, ni doublon.

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
   - fait une **Cube Projection** sur ces faces seulement (taille du cube 0,2 par défaut, réglages exposés).

   Embedded de la Diffuse reste réglable. Une image partagée avec un autre matériau n'est pas modifiée : l'addon en charge une copie.

### 4 — Value Parameters et presets
- Les paramètres du shader du matériau actif sont affichés et modifiables.
- **Valeurs de base** : en mode Personnalisé, chaque nouveau matériau reçoit
  umGlobalParams 0,0025 / 0,0025 / 7 / 7, envEffFatThickness 25 / 25, specularIntensityMult 1997,
  specularFalloffMult 1997, specularFresnel 0,45, bumpiness 1,3, emissiveMultiplier 1 (Ped Emissive seulement),
  detailSettings 0 / 0 / 24, StubbleControl 2 / 0,6. **Appliquer les Value Parameters de base** les remet sur le
  matériau actif. Un preset garde ses propres valeurs.
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
1. **Charger les références Teef** : Sollumz importe `teef_000_u.ydd.xml` avec `mp_m_freemode_01.yft.xml` comme squelette externe (mode « Saved »), directement dans la Scene Collection.
2. **Rigger sur SKEL_Spine3** crée le mesh **`mio_chain`**, une copie : vos sources restent modifiables. Le bouton :
   - réunit uniquement les composants désignés en un seul Mesh Object ;
   - conserve placement, matériaux, UV et Color Attributes ;
   - assigne tous les sommets au groupe `SKEL_Spine3` avec un poids de 1, par l'API, et retire les autres groupes ;
   - lie `mio_chain` à l'armature `teef_000_u` (modificateur Armature) ;
   - le met **à la place de `SKEL_ROOT`** sous `teef_012_u` : même parent, type Sollumz, skinning et LOD, position monde inchangée. La structure est vérifiée **avant** de retirer le mesh `SKEL_ROOT`. L'os `SKEL_ROOT` et l'armature ne sont jamais touchés.

Résultat, comme dans votre Outliner :

```
Scene Collection
└─ teef_000_u            (armature, données teef_000_u.skel, 128 os)
   └─ teef_012_u         (drawable)
      └─ mio_chain       (votre bijou)
```

Si `mio_chain` existe déjà quand vous chargez (ou rechargez) les références, il est placé automatiquement dans la nouvelle structure. **Contrôler en Weight Paint** permet la vérification visuelle.

### 8 — Structure d'export et export
- **Noms** : armature et fichier `teef_000_u`, drawable `teef_012_u` par défaut, modifiables. Les objets sont renommés à l'export si besoin.
- **LOD** : *High uniquement* (Medium et Low vides) ou *High copié en Medium et Low*, affichée comme **non optimisée**. Le réglage est réappliqué au placement et juste avant l'export.
- **Placer mio_chain dans la structure** refait le placement si besoin, par exemple après un rechargement. Si le mesh de référence porte un autre nom, choisissez-le dans « Mesh à remplacer ».
- **Vérifier avant export**, puis **Exporter avec Sollumz**. Les fichiers produits sont relus :
  - drawable et nom de sortie ;
  - LOD exportés ;
  - 100 % des sommets sur l'os 38 (SKEL_Spine3) ;
  - squelette exclu ;
  - DDS Bump et Spec intégrés.

Un export Blender réussi **ne valide pas** le bijou dans FiveM : testez-le en jeu.

## Aperçu sur mon display
Section séparée et facultative, en quatre gestes :
1. Choisissez votre `.blend` puis **Charger le display**. En un clic :
   - le display est ajouté dans une scène à part, avec son éclairage, ses matériaux, ses caméras et ses réglages de rendu ;
   - une **copie** du bijou y est posée sur un repère : la position mémorisée pour ce display, sinon un vide dont le nom contient « repère », « bijou », « collier »…, sinon le curseur 3D.
2. **Déplacer le bijou (G / R / S)** ouvre le display et sélectionne le repère qui porte le bijou. **Mémoriser cette position** la garde pour les prochains projets.
3. **Actualiser le bijou** après une modification, sans recharger le display ni créer de doublon.
4. **Voir par la caméra**, puis **Rendu rapide** ou **Rendu final**. **Revenir au projet** vous ramène à votre scène.

**Textures du display** : si une texture du display est introuvable (fichier déplacé, chemin relatif cassé), l'addon reprend la même texture déjà utilisée dans votre projet (même nom de fichier). S'il en reste, **Rechercher les textures manquantes…** vous laisse choisir votre dossier de textures ; Blender y cherche les fichiers par leur nom, sous-dossiers compris.

Caméra, résolution, dossier des rendus, mode de chargement et décalages sont dans le sous-panneau **Options**, fermé par défaut. Le display, ses lumières, ses caméras et les copies d'aperçu sont exclus de l'export.

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
