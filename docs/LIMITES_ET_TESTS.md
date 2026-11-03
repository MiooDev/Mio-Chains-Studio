# Vérifications, limites connues et tests restants (version 0.3.6)

## Environnement des tests réellement exécutés

- **Blender** : module `bpy` 5.2.3 LTS, sous Linux, sans interface graphique.
- **Sollumz** : 2.9.0 (dernière version publiée) et szio 1.3.0.dev9, réellement installés.
- **Références** : les **vrais fichiers de Teef.zip**.
- **Données synthétiques** : le SVG, la chaîne `.obj`, les textures diffuses et le display, générés par les tests.
- **Copie testée** : l'addon **installé depuis le ZIP** (`extensions.package_install_files`).
- **Script** : `tests/run_tests.py`.

**Résultat : 177/177 vérifications réussies.**

| Point demandé | Vérification exécutée |
|---|---|
| Formes SVG conservées après retrait des noirs | Faces de dos et trou de la lettre noire conservés ; forme entièrement noire gardée sans matériau ; matériaux non noirs identiques ; dessin XY inchangé |
| Épaisseurs réelles et contact | Mesuré : 0,02 / 0,01 / 0,005 m (valeurs par défaut) ; dos de la couche 2 = avant de la couche 1 ; idem pour la couche 3 ; direction −Z |
| SVG réaliste (corrigé en 0.2.1) | Tracés avec points alignés (faces de surface nulle), trous et courbes de Bézier : solides fermés et bien orientés, volume = surface × épaisseur, faces nulles signalées |
| Préparation « tout ou rien » | Courbe non plane : refus avant toute création ; échec simulé après construction : nouveaux maillages retirés, anciens gardés, sources non masquées |
| Pas d'accumulation | Deux clics de plus : épaisseurs identiques, 4 maillages ; une épaisseur modifiée recalcule l'empilement |
| Ordre des couches | Même hauteur : rien n'est deviné et la préparation est refusée ; hauteurs distinctes : ordre détecté |
| Chaîne OBJ | Matériau et UV conservés ; ré-import sans doublon ; chaîne gardée si le fichier est absent ou sans maillage ; chaîne de la scène ajoutée et retirée sans suppression |
| Matériaux et UV sur les seules faces choisies | Indices de matériau des autres faces inchangés ; UV des autres coins inchangées ; UV des faces choisies recalculées (Cube Projection) ; matériau réutilisé ; `ped.sps` et `ped_emissive.sps` (avec `UVMap 1`) |
| Embedded et Non-Color | Bump et Spec Embedded, Diffuse non ; Bump en Non-Color ; une image partagée par un autre matériau reste en sRGB |
| Presets | Enregistrement (shader, textures, Embedded, espaces, paramètres), duplication, suppression ; preset incomplet signalé et refusé ; relocalisation ; mode Preset appliqué aux faces |
| Color Attributes | Color 1 = 255 128 0 255 et Color 2 = 0 0 0 0 relus partout, en Face Corner / Byte Color ; valeur linéaire 0,2158 pour 0x80 ; seul l'attribut de mauvais type est remplacé ; autres attributs conservés ; pas de doublon ; refus sans confirmation si une peinture existe |
| Glow | Color 1 actif et mode Vertex Paint ; la peinture `#FFBAFF` est conservée jusqu'à l'export |
| Poids 1 sur SKEL_Spine3 | Tous les sommets du mesh final : un seul groupe `SKEL_Spine3` à 1,0 ; groupe résiduel retiré de la copie (pas de la source) |
| Un seul mesh final et sa liaison | Un seul objet après deux clics ; modificateur Armature vers le squelette chargé (128 os, SKEL_Spine3 index 38, tag 24818) |
| Structure de votre Outliner (0.3.0) | `teef_000_u` (128 os, données `teef_000_u.skel`) > `teef_012_u` > `mio_chain` dans la Scene Collection ; le mesh `SKEL_ROOT` est retiré, l'os `SKEL_ROOT` et l'armature restent intacts ; rechargement : `mio_chain` replacé dans la nouvelle structure, sans doublon |
| Placement du bijou | Position monde identique avant et après le changement de parent |
| Aucune ancienne géométrie dans les LOD | High = bijou, Medium et Low vides ; mode copie : High recopié en Medium et Low ; fichier exporté : `DrawableModelsHigh` seul (ou High, Medium, Low), aucune trace de `teef_diff_012_a_uni` |
| Export relu | `teef_000_u.ydd.xml` : drawable `teef_000_u` ; 100 % des sommets à `0 0 255 0` / `0 0 38 0` comme la référence vanilla ; squelette exclu ; DDS Bump et Spec intégrés ; Colour0 255 128 0 255 et zones 255 186 255 255 |
| Sauvegarde et réouverture | Structure Teef, mio_chain, composants, réglages et presets conservés ; statut 8 conservé ; actualisation sans doublon |
| Aperçu simplifié (0.3.1) | Chargement en un clic avec bijou posé automatiquement sur le vide du display ; « Déplacer le bijou » sélectionne le repère dans le display ; position mémorisée ; retour au projet ; rendu rapide |
| Textures du display (0.3.2) | Chemin relatif au display retrouvé ; texture introuvable reprise du projet (même fichier) ; seule la texture vraiment absente est signalée, puis retrouvée par « Rechercher les textures manquantes » dans un sous-dossier |
| Mettre la chaîne sur le display (0.3.5) | Sans bijou désigné : la chaîne sélectionnée dans le projet est posée dans la scène du display, qui s'affiche ; rien de sélectionné : refus clair ; actualisation sans sélection : la chaîne mémorisée reste posée ; bijou de l'étape 2 désigné : il redevient la source |
| Textures du display (0.3.5) | Sélecteurs : dossiers et images affichés (filtre images + `*.dds`, DDS reconnu par Blender) ; « Choisir… » relie une texture à un fichier d'un autre nom et refuse un fichier non image ; un vrai DDS de Teef est relié et lu ; texture présente seulement intégrée (packed) au projet : réutilisée |
| Textures au rendu (0.3.6) | Copie de la chaîne : UV, images et nœuds UV Map identiques à la source ; damier rendu sur la copie (matériau d'OBJ et `ped.sps`) ; graphe Sollumz `ped` / `ped_emissive` sans couleur de sommet. Texture « paillettes » : invisible à 6 px/cm (caméra du display), visible en gros plan à 64 px/cm |
| Gros plan et détails (0.3.6) | Rendu rapide à la résolution complète ; taille de la chaîne sur l'image estimée (px, px/cm) ; gros plan : une seule caméra dans la scène d'aperçu, même angle que celle du display, chaîne à ~75 % du cadre, caméra du display intacte ; limite de textures Simplify signalée ; deux rendus de suite sans écrasement |
| Exclusion du display | Display chargé dans une scène séparée ; aucune erreur d'exclusion ; aucun objet du display dans le YDD |
| Dépendances | Dossier Teef incomplet ou absent refusé ; Sollumz désactivé : export refusé et panneaux sans erreur |
| Statut en erreur (0.3.3) | Si le calcul d'un statut échoue, tous les panneaux restent dessinés et l'erreur s'affiche dans le panneau concerné |
| Cohabitation avec d'autres addons (0.3.4) | Panneaux renommés `MCS_PT_…` : un autre addon qui utilise `MIO_PT_main`, `MIO_PT_step1…6` ou `MIO_PG_step` ne les remplace plus ; un vrai conflit d'identifiant est détecté et affiché dans le panneau principal |
| Interface | Le code de dessin de tous les panneaux a été exécuté (noms de propriétés et d'opérateurs validés), y compris sans Sollumz |

## Non testé (vérification du code seulement)

- **Annuler (`Ctrl+Z`)** : les opérateurs déclarent l'option UNDO, mais la pile d'annulation de Blender est désactivée en mode sans interface (`ed.undo` refuse le contexte). À tester dans Blender.
- **Interface graphique réelle sous Windows** :
  - rendu visuel des panneaux, sélecteurs de fichiers (l'affichage réel des `.dds` dans le sélecteur n'est vérifié que par ses réglages) ;
  - confirmations (remplacement de preset, peinture existante, suppression) et recherches (presets, shaders) ;
  - « Voir par la caméra » dans une vraie vue 3D ;
  - `Ctrl + X` en Vertex Paint avec votre propre keymap.
- **Export binaire natif** (PyMateria, Windows) et **Gen9**.
- **CodeWalker et FiveM** : aucun accès dans cet environnement. Le bijou n'est **pas** validé en jeu.

## Limites connues

- **mio_chain** : il est construit à partir des composants. S'ils changent, l'étape 7 repasse en « périmé » ; relancez-la : le nouveau mio_chain reprend sa place sous teef_012_u.
- **DiffuseSampler non intégré** : la texture doit être fournie dans un YTD. L'addon le signale mais ne crée pas ce YTD.
- **LOD Medium et Low** : aucune simplification automatique. Le mode « copie » recopie le High tel quel (non optimisé).
- **Seconde map UV de `ped_emissive.sps`** : `UVMap 1` est créée par Sollumz avec ses valeurs par défaut ; son rôle exact dans le shader n'est pas documenté ici.
- **SVG** : chaque courbe doit être plane, perpendiculaire à la direction d'empilement, et remplie (*Fill Mode*). Les maillages produits gardent leurs coordonnées monde (origine à l'origine du monde).
- **Tracés SVG qui se chevauchent ou se croisent** : le remplissage de Blender y est déjà ambigu. L'addon l'épaissit fidèlement, mais le solide obtenu se recoupe lui-même. Préférez des tracés simples, unis à l'avance dans votre logiciel de dessin.
- **Reconstruction groupée** : préparer une sélection reconstruit aussi les autres courbes déjà préparées du projet, pour garder l'empilement cohérent. Préparez un pendentif à la fois.
- **Noms en double** : Blender ajoute `.001` quand un nom est déjà pris (par exemple drawable et fichier nommés pareil). Sollumz retire ce suffixe à l'export ; le panneau affiche le nom réellement exporté.
- **Fichiers de stream FiveM** (manifest, métadonnées de vêtements) : hors du périmètre de l'addon.
- **Gros plan** : la caméra est placée devant la chaîne, sous l'angle de la caméra du display. Un objet du display placé entre les deux (main, cheveux…) peut la cacher ; dans ce cas, réglez l'angle de la caméra du display.
