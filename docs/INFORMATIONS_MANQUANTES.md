# Informations manquantes

## 1. Vidéo de référence (https://www.youtube.com/watch?v=sn-4b5vYNuo)

L'environnement de développement ne peut pas joindre youtube.com (domaine bloqué). Je n'ai eu accès ni à la description, ni aux chapitres réels, ni au commentaire épinglé, ni aux manipulations montrées.

**Aucun réglage du tutoriel n'a donc été repris.** Le parcours de l'addon s'appuie sur les titres de chapitres que vous avez fournis, et ses paramètres viennent de sources vérifiables : le code de Sollumz 2.9.0 et votre fichier de référence.

Pour aligner l'addon sur la vidéo, envoyez-moi (texte ou captures d'écran) :

| Chapitre | À préciser |
|---|---|
| 0:00 — outils et fichiers | Versions de Blender, Sollumz et CodeWalker utilisées ; fichiers de base (modèle du ped, squelette `.yft`, chaîne vanilla). |
| 1:41 — préparation du modèle | Échelle, axes, application des transformations, nettoyage, nommage des objets, nombre de LOD. |
| 3:25 — matériaux et textures | Shader exact choisi, paramètres modifiés, textures par entrée, format et taille des DDS, textures intégrées au YDD ou placées dans le YTD. |
| 6:25 — effets de shader | Shader utilisé pour l'effet, paramètres et valeurs (ex. `emissiveMultiplier`), couleurs de sommets peintes ou non. |
| 8:46 — rigging | Os utilisés, méthode de pondération (transfert, peinture, os unique), source des poids. |
| 9:40 — export | Options d'export de Sollumz (format, Gen8/Gen9, *Exclude Skeleton*, *Apply Parent Transforms*…), noms de fichiers. |
| 11:50 — CodeWalker | Manipulations exactes : import XML, création du YTD, ajout du DDS (le point du commentaire épinglé), vérifications. |
| Commentaire épinglé | Texte exact de la manipulation manquante. |

## 2. Fichiers à fournir

Poussez-les dans le dépôt `MiooDev/Mio-Chains-Studio`, par exemple dans un dossier `reference/`.

- **Le `.blend` de votre display** : pour inspecter ses axes, son échelle, ses origines, ses caméras et son éclairage, et préparer le repère par défaut.
- **Le modèle de référence avec son armature** : le squelette du ped (ex. `mp_m_freemode_01.yft` ou un `.blend` où Sollumz l'a importé). Indispensable pour tester les indices d'os et les poids réels.
- **Une ou deux chaînes `.obj`** : pour régler les axes et l'échelle d'import par défaut, et vérifier les UV pour l'atlas.

## 3. Ce que votre fichier `teef_000_u.ydd.xml` a permis d'établir

- Composant **teef**, maillage skinné (`HasSkin = 1`), squelette absent du fichier (`Joints` vide) : il vient du ped. D'où l'export avec *Exclude Skeleton*, option que Sollumz décrit comme « habituelle pour les composants de ped MP ».
- Le fichier s'appelle `teef_000_u` mais son drawable s'appelle **`teef_012_u`**. L'addon donne par défaut le même nom au fichier et au drawable. Dites-moi si l'écart était voulu.
- Shaders `ped_hair_cutout_alpha` (LOD haut) et `ped_default` (LOD moyen et bas).
- Textures :
  - `teef_diff_012_a_uni` dans le YTD externe ;
  - `teef_normal_001` et `teef_spec_000` intégrées au YDD, en DXT1.
- Couleurs de sommets constantes : Colour0 = 255 128 0 255, Colour1 = 0 0 0 0. Ce sont les valeurs par défaut de l'addon.
- 4 indices d'os par sommet. LOD haut : 100 % sur l'os d'indice 38 ; LOD moyen : mélange des os 36, 37, 38, 39, 68 et 97. Les noms de ces os ne sont connus qu'avec le squelette du ped.
- Unités en mètres, Z vers le haut, avant du torse vers **−Y**. D'où l'orientation par défaut du pendentif.
