# Dépendances, limites connues et état des tests

## Dépendances

| Dépendance | Version | Rôle | Obligatoire |
|---|---|---|---|
| Blender | 5.2 (testé 5.2.3 LTS) | Hôte ; le manifeste exige ≥ 5.2.0 | Oui |
| Sollumz | 2.9.0 (testé) | Matériaux GTA, dictionnaires de textures, export | Oui |
| szio | 1.3.0.dev9 (installé par Sollumz) | Moteur d'import/export de Sollumz | Oui |
| PyMateria | via Sollumz, Windows | Export binaire natif `.ydd` / `.ytd` | Non |
| texconv (DirectXTex) ou ImageMagick | — | Encodage DDS de l'atlas | Non |

Tout fonctionne en local, sans API payante ni accès réseau.

Une autre version de Sollumz est détectée et signalée. Les fonctions internes appelées sont listées dans `sollumz_bridge.py` :
- `create_shader` ;
- `post_create_shader_update_object` ;
- `get_uv_map_name` et `get_color_attr_name` ;
- l'opérateur `sollumz.export_assets` ;
- `scene.sz_txds`.

## Ce qui a été réellement testé dans Blender

Environnement : **module `bpy` 5.2.3 LTS (Linux, sans interface graphique)**, **Sollumz 2.9.0** et szio 1.3.0.dev9 réellement installés, ImageMagick 6.9.12.

Script : `tests/run_tests.py`, exécuté sur l'addon **installé depuis le ZIP** par `extensions.package_install_files`. Résultat : **129/129 vérifications réussies**.

Les chaînes, armatures et displays de ces tests sont **synthétiques**. Votre fichier `teef_000_u.ydd.xml` a été importé par Sollumz comme modèle de référence.

| Domaine | Vérifié |
|---|---|
| Pendentif | Création ; mise à jour du texte (même objet, nouveau maillage) ; clics répétés sans doublon ni maillage orphelin ; objet ajouté à la main conservé ; plaque retirée puis rétablie ; police chargée depuis un fichier ; erreurs police manquante et texte vide ; matériaux et poids conservés après mise à jour |
| Chaîne | Import OBJ ; ré-import qui remplace sans doublon ; OBJ multi-objets (vide parent ou joints) ; chaîne existante choisie dans la scène (l'ancienne n'est pas supprimée) ; erreurs fichier absent et mauvais format ; avertissement d'échelle face à la référence ; accroche du pendentif ; déplacement de l'ensemble sans casser l'assemblage |
| Matériaux | Création de matériaux Sollumz `ped_default` ; clics répétés sans doublon ; association de textures ; image introuvable refusée ; préréglage enregistré puis réappliqué |
| Atlas / DDS / YTD | Atlas 512 px vérifié coin par coin ; UV d'origine intactes ; atlas périmé après changement du texte ; PNG renommé en `.dds` refusé ; conversion ImageMagick (DXT5, 512×512, 10 mips relus dans l'en-tête) ; YTD Sollumz contenant la texture |
| Effets | Couleurs 255 128 0 255 écrites et relues ; couleurs relues sur la référence teef ; émissif activé (`ped_emissive`, `emissiveMultiplier`, `UVMap 1`) puis désactivé |
| Rigging (armature de test) | Liaison ; transfert de poids ; pendentif rigide ; 4 influences max. ; groupe sans os détecté ; restauration exacte ; déformation visible ; pose restaurée exactement ; poids réappliqués après mise à jour du texte |
| Display | Fichier manquant ; analyse ; chargement en scène complète (caméra, réglages Cycles et résolution repris) ; mode collections ; ressource manquante signalée ; second chargement refusé ; repère depuis un objet, enregistré puis restauré au rechargement ; placement puis 3 actualisations sans doublon ; matériaux et géométrie d'aperçu indépendants ; assemblage conservé ; réglage de position ; « Épouser » limité à l'aperçu ; rendu rapide Cycles (fichier PNG) avec réglages restaurés ; rechargement sans scène en double |
| Export | Copie d'export (DWD armature → drawable → 4 modèles) ; sources intactes ; vérification sans erreur ; export CW XML Gen8 (YDD XML, YTD XML et DDS) ; contenu relu (drawable, texture, couleurs, aucun objet du display) ; export lancé depuis la scène d'aperçu ; écart de format signalé entre le XML de szio et le DDS ; statuts 7 et 8 ; checklist invalidée par un nouvel export |
| Fiabilité | Sauvegarde puis réouverture : toutes les références conservées, mise à jour sans doublon ; code de dessin de **tous les panneaux** exécuté (noms de propriétés et d'opérateurs validés), aussi après réouverture et sans Sollumz ; Sollumz désactivé : erreurs claires et opérations refusées ; objets extérieurs jamais supprimés |

## Vérifié seulement par lecture du code (non exécuté ici)

- **Interface graphique réelle** : rendu visuel des panneaux, sélecteurs de fichiers, confirmation « Recharger », recherche de préréglages et de shaders, « Voir par la caméra » dans une vraie vue 3D, rendu lancé depuis l'interface (Blender reste occupé pendant le rendu).
- **texconv** (Windows) : la commande suit la documentation de DirectXTex mais n'a pas été exécutée.
- **Export binaire natif** (PyMateria, Windows uniquement) et **Gen9**.
- Moteur **EEVEE** en mode « Aperçu rapide » (seul Cycles a été testé).

## Points restant à tester avec vos fichiers

1. **Votre display `.blend`** : axes, échelle, origines, choix du repère, éclairage et cadrage conservés.
2. **Le squelette réel du ped** (ex. `mp_m_freemode_01`) : indices d'os produits par Sollumz, transfert des poids depuis la chaîne vanilla importée **avec** son squelette, déformation.
3. **Vos chaînes `.obj`** : axes et échelle d'import (le test utilise les axes par défaut de Blender), UV dans [0, 1] pour l'atlas.
4. **CodeWalker** : import des XML, présence du DDS dans le YTD, format réel de la texture.
5. **FiveM** : rendu des matériaux, couleurs de sommets, émissif, déformation en jeu.

## Limites connues

- **Vidéo de référence inaccessible** (domaine bloqué dans l'environnement de développement). Aucun réglage du tutoriel n'a été repris : voir `INFORMATIONS_MANQUANTES.md`.
- **Atlas** : grille de tuiles égales (une par image diffuse distincte). Il exige des UV dans [0, 1] : les textures répétées demanderaient un pré-calcul (bake), non fourni.
- **DDS** : aucune conversion sans encodeur externe. BC7 n'est disponible qu'avec texconv.
- Le YTD XML écrit par Sollumz 2.9 / szio 1.3 annonce `D3DFMT_DXT1` et `MipLevels 0` par défaut, quel que soit le DDS. L'addon signale l'écart ; vérifiez le format réel dans CodeWalker.
- **Couleurs de sommets** : on reproduit les valeurs constantes de votre référence ; leur signification exacte par canal n'est pas documentée ici.
- **Émissif** : seul `ped_emissive.sps` expose `emissiveMultiplier` dans la famille ped de Sollumz 2.9.0. Le rôle exact de sa seconde map UV n'est pas documenté ici.
- **Rigging** :
  - le transfert de poids s'applique au maillage de base : les modificateurs génératifs de la chaîne (Array, Curve…) sont signalés et doivent être appliqués avant ;
  - les sauvegardes de poids sont stockées dans l'objet : pour un maillage très dense, le fichier `.blend` grossit.
- **Analyse des poids** : elle est relancée à la demande (bouton) et à l'export. Une retouche au pinceau qui ne change pas la géométrie n'invalide pas automatiquement le statut affiché.
- **LOD** : seul le LOD haut est exporté (vos références contiennent aussi des LOD moyen et bas).
- **Fichiers de stream FiveM** (`fxmanifest`, métadonnées de vêtements addon) : hors du périmètre de l'addon.
- **Hors V1** : placement automatique de diamants et génération de maillons.
