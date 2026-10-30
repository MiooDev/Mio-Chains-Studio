# Guide du parcours utilisateur

Ouvrez la vue 3D, appuyez sur `N`, onglet **Mio Chain**. Le premier panneau résume l'état de chaque section.

Chaque section affiche :
- un **statut** : « À faire », « À vérifier » ou « Terminé » ;
- une instruction courte ;
- les erreurs détectées et leur correction (→).

Les statuts sont **recalculés à partir de l'état réel** de la scène, jamais à partir d'un simple clic. Exemple : si vous modifiez le texte après avoir préparé l'atlas, l'atlas repasse en « périmé ».

Toutes les opérations qui modifient la scène peuvent être annulées avec `Ctrl+Z`. L'addon ne supprime que ce qu'il a lui-même créé : vos objets ajoutés à la main sont conservés.

---

## 1. Préparer le projet

1. Enregistrez votre fichier `.blend` : les textures (`//textures/`), rendus et exports sont rangés à côté de lui.
2. Cliquez **Initialiser le projet**. Cela crée les collections `MCS_Sources`, `MCS_Bijou` et `MCS_Export`, ainsi que les repères.
3. Réglez les **noms des fichiers**. Par défaut :

   | Élément | Nom |
   |---|---|
   | Drawable | `teef_000_u` |
   | Texture diffuse | `teef_diff_000_a_uni` |
   | YTD | `teef_diff_000_a_uni` |

   Ces motifs reprennent votre référence `teef_012_u` / `teef_diff_012_a_uni`. Un préfixe de fichier facultatif est disponible (ex. `mp_m_freemode_01_monpack^`).
4. Facultatif : choisissez le **modèle de référence**, par exemple votre chaîne vanilla importée avec Sollumz. Il sert à comparer la taille de la chaîne et à relever les couleurs de sommets.

Le bouton ⟳ relance la détection de Sollumz, de szio et des encodeurs DDS.

## 2. Créer et assembler le bijou

**Pendentif texte**
- Écrivez le texte (ex. `NO RULES`).
- Choisissez une police chargée, ou un fichier `.ttf` / `.otf`.
- Réglez la taille, l'espacement, l'épaisseur, le biseau et sa résolution, et la **finesse des courbes**.
- Facultatif : **plaque** (marge, épaisseur, coins arrondis) et **bélière** (position, rotation, rayon, épaisseur du fil).
- **Créer le pendentif** / **Mettre à jour le pendentif** : l'objet est mis à jour sur place, sans copie, et ses matériaux sont conservés. Si des poids avaient été générés, ils sont réappliqués avec la même méthode.
- Le nombre de triangles s'affiche pour chaque pièce. Le texte source reste modifiable (objet `MCS_Texte_Source`, caché).

**Chaîne et composants**
- Choisissez un fichier `.obj` et réglez les axes (avant / haut) et l'échelle de l'importateur Blender, puis **Importer la chaîne**. Un nouvel import remplace celui que l'addon avait fait auparavant.
- Si l'OBJ contient plusieurs objets, ils sont rangés sous un vide, sans être fusionnés (sauf si « Joindre » est coché).
- Pour une chaîne déjà présente dans la scène : sélectionnez-la, puis cliquez la **pipette** de la ligne « Chaîne ».
- Les pipettes permettent aussi de désigner séparément texte, plaque et bélière.
- Les dimensions de la chaîne s'affichent. Une échelle incohérente avec le modèle de référence est signalée.

**Assemblage**
- *Pendentif par rapport à la chaîne* : position, rotation et échelle du pivot du pendentif.
- **Accrocher au bas de la chaîne** : place la bélière au point le plus bas de la chaîne.
- *Bijou entier* : déplace l'ensemble sans changer la position relative des pièces.
- Le pivot est tourné de 90° sur X : le texte regarde vers −Y, comme l'avant du torse de votre référence. C'est réglable.

## 3. Matériaux et textures

1. Choisissez un shader par composant (par défaut `ped_default.sps`, famille « ped »), puis cliquez **Créer / configurer les matériaux**. Les matériaux sont créés par Sollumz lui-même.
2. Pour chaque entrée du shader (DiffuseSampler, BumpSampler, SpecSampler) : 📁 choisit l'image, ✕ la retire.
   - L'addon affiche le **nom de texture** que Sollumz exportera (le nom du fichier) et les dimensions.
   - Il signale les fichiers manquants, les tailles non puissance de deux et les tailles au-dessus de votre seuil.
3. **Préréglages** : 💾 enregistre shader, paramètres et chemins de textures (JSON réutilisable) ; 📋 en applique un.

**Atlas, DDS et YTD**
- L'atlas regroupe les **images** dans une seule texture. Les **matériaux et shaders restent distincts** : à l'export, ils pointent tous vers l'atlas avec des UV recalculées.
- Vos UV d'origine ne sont jamais modifiées : les UV d'atlas sont stockées à part.
- **Préparer l'atlas** : grille automatique, marge en pixels anti-débordement, puis vérification de chaque coin de face.
  - L'atlas exige des UV dans [0, 1] : les textures répétées sont refusées avec un message.
  - Les atlas de normales et de spéculaire utilisent la même disposition. Chaque tuile doit alors avoir sa texture : l'addon n'invente aucune valeur neutre.
- **Convertir en DDS** : utilise texconv ou ImageMagick, puis relit l'en-tête du fichier produit (signature, taille, format, mipmaps).
  - Sans encodeur, l'atlas reste en PNG : convertissez-le avec l'outil de votre choix, puis indiquez le `.dds` et cliquez 🔍.
  - Renommer un `.png` en `.dds` est détecté et refusé.
- **Préparer le YTD (Sollumz)** : place le DDS vérifié dans un dictionnaire de textures Sollumz nommé comme votre YTD.

## 4. Effets

- **Émissif** : seuls les shaders ped dont la définition Sollumz contient `emissiveMultiplier` sont proposés (dans Sollumz 2.9.0 : `ped_emissive.sps`).
  - « Activer » change le shader en conservant les textures ; ✕ revient au shader précédent.
  - Ce shader utilise aussi une seconde map UV (`UVMap 1`), ajoutée par Sollumz.
  - L'aspect dans Blender n'est qu'indicatif : vérifiez l'intensité dans FiveM.
- **Couleurs de sommets** : les shaders ped lisent `Color 1` et `Color 2`.
  - Valeurs par défaut lues dans votre référence `teef_012_u` : Color 1 = 255 128 0 255, Color 2 = 0 0 0 0. Sans cette étape, Sollumz créerait des attributs blancs (255 255 255 255).
  - « Lire depuis la référence » relève la valeur la plus fréquente du modèle de référence. « Appliquer » écrit les valeurs puis les relit pour vérification.

## 5. Préparer le rigging

1. Choisissez l'**armature de référence** : le squelette du ped importé avec Sollumz, par exemple `mp_m_freemode_01`.
2. Choisissez éventuellement un **maillage source des poids** : un maillage déjà pondéré, avec des groupes nommés comme les os (chaîne vanilla, corps du ped).
3. **Lier à l'armature** : ajoute le modificateur Armature, sans reparenter les objets.
4. Choisissez une méthode explicite pour la chaîne et pour le pendentif :

   | Méthode | Effet |
   |---|---|
   | Transfert depuis la référence | Data Transfer, surface la plus proche, puis 4 influences max. normalisées |
   | Rigide, poids du point d'attache | Le pendentif reprend les poids de la chaîne à l'endroit de la bélière |
   | Un os choisi | Tout l'objet suit un os **que vous choisissez** |
   | Conserver l'existant | Aucune modification |

5. Chaque génération **sauvegarde les poids précédents** : « Restaurer » y revient exactement.
6. **Vérifier le rigging** contrôle :
   - l'armature et les liaisons ;
   - les groupes sans os correspondant (Sollumz les rattacherait à l'os racine) ;
   - les sommets sans poids, les influences en trop et les sommes différentes de 1 ;
   - les transformations.
7. **Tester la déformation** tourne un os. « Remettre la pose » restaure exactement la pose d'origine. Confirmez ensuite le contrôle visuel : cette confirmation est invalidée si la géométrie ou les poids changent.

## Aperçu sur mon display

1. Choisissez le `.blend` du display, puis 🔍 pour lister ses scènes, collections et mondes (rien n'est chargé à ce stade).
2. Mode **Scène complète** (recommandé) : conserve rendu, monde, lumières, caméras et cadrage. Mode **Collections choisies** : seulement les collections cochées.
3. **Charger le display** : il est ajouté dans une **scène séparée** (`MCS_Apercu_…`). Les ressources externes manquantes sont signalées. Un second clic est refusé ; « Recharger » recrée tout, après confirmation.
4. **Repère** : sélectionnez dans la scène d'aperçu un objet du display (ex. un vide au niveau du cou) puis « Objet actif », ou utilisez le curseur 3D. **Enregistrer le repère** le mémorise pour ce fichier display : il sera restauré automatiquement aux chargements suivants.
5. **Placer le bijou sur le display** / **Actualiser l'aperçu** : une **copie indépendante** (maillages et matériaux propres) est placée sur le repère, sans doublon et sans recharger le display.
   - Les pièces gardent leur assemblage. Réglages possibles : position, rotation, échelle, et point du bijou ancré sur le repère.
   - L'écart d'unité entre les deux scènes est compensé.
6. **Épouser la forme** est une opération distincte (Shrinkwrap). Elle ne concerne que la chaîne de l'aperçu : le placement seul ne déforme rien.
7. **Rendu** : choisissez caméra, résolution, dossier et mode.
   - « Aperçu rapide » : 50 % de la résolution et échantillons réduits, puis réglages restaurés.
   - « Rendu final » : réglages du display tels quels.
   - « Voir par la caméra » ouvre la scène d'aperçu ; « Revenir au projet » vous ramène à la scène du projet.

Rien de la scène d'aperçu n'entre dans l'export.

## 6. Vérifier avant export

1. **Créer / actualiser la copie d'export** : construit une copie dédiée (armature → drawable → modèles) au format attendu par Sollumz. Vos sources restent modifiables et intactes.
2. **Lancer la vérification**. Le rapport sépare les **erreurs bloquantes** et les **avertissements**, avec un bouton pour sélectionner l'objet concerné. Il couvre :
   - les objets inclus et leur organisation ;
   - les matériaux et les références de textures ;
   - les UV et les couleurs ;
   - l'armature et les poids ;
   - les noms ;
   - l'exclusion du display ;
   - le DDS et le YTD ;
   - le nombre de triangles (votre seuil, pas une limite officielle).

## 7. Exporter

- Choisissez le dossier, puis les formats proposés par votre Sollumz :
  - **CodeWalker XML** : toujours disponible ;
  - **Binaire natif** : nécessite PyMateria (Windows) ;
  - versions **Gen8 (Legacy)** et/ou Gen9.
- **Exporter avec Sollumz** refuse s'il reste une erreur bloquante. Il appelle ensuite l'export de Sollumz et **relit les fichiers produits** : drawable présent, modèles skinnés, squelette exclu, nom de texture, DDS à côté du YTD XML.
- Les formats produits et les opérations restantes s'affichent.
- Un export réussi ne valide pas le bijou dans FiveM.

## 8. Vérifier dans CodeWalker

Cochez chaque point après l'avoir vérifié vous-même. Un nouvel export invalide la checklist.
- Conversion des XML en `.ydd` / `.ytd`.
- **Présence effective du DDS dans le YTD** : étape absente de la vidéo, signalée par son auteur dans le commentaire épinglé.
- Noms identiques entre le YDD et le YTD.
- Taille, format et mipmaps de la texture. Le XML de Sollumz 2.9 peut annoncer DXT1 / 0 mip par défaut, même si le DDS est en DXT5 avec mipmaps : l'addon le signale après l'export.
- Aperçu du composant, déformation en jeu, émissif de jour et de nuit, fichiers de stream (hors périmètre de l'addon).
