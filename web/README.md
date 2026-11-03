# Mio Chain Photo

Un fichier HTML unique pour photographier vos chaînes GTA V / FiveM à partir des fichiers du jeu, sans Blender.

## Utilisation

1. Ouvrez `mio_chain_photo.html` dans Chrome, Edge ou Firefox (double-clic). Aucune installation.
2. Déposez vos chaînes (`.ydr` ou `.ydd`) **et** leurs textures (`.ytd`) dans la zone « Fichiers ». Les `.ytd` peuvent être ajoutés après coup : les textures sont reliées par leur nom.
3. Sous chaque chaîne, une pastille indique chaque texture du shader :
   - **✓** : texture trouvée (intégrée au modèle ou dans un `.ytd` chargé) ;
   - **✕** : texture introuvable. Ajoutez le `.ytd` qui la contient.
4. Réglez le rendu, choisissez la vue (Face, 3/4, Profil, Dessus, Dos), le format et la taille, puis **Prendre la photo**.
   - **Photographier toutes les chaînes** prend une photo de chaque chaîne, avec les mêmes réglages.
   - Le cadre affiché sur la scène correspond exactement à l'image exportée.
5. Les photos s'ajoutent à la **planche contact** : **Télécharger** pour une image, **Tout télécharger (.zip)** pour toutes.

Vos fichiers restent sur votre ordinateur : rien n'est envoyé. Le moteur 3D (three.js) est inclus dans le fichier, qui marche donc sans Internet (les polices de l'interface ont un remplacement).

## Rendu

Les réglages du matériau viennent du shader de la chaîne :

| Paramètre du shader | Utilisation |
|---|---|
| `DiffuseSampler` | couleur |
| `BumpSampler` + `bumpiness` | relief (normal map DirectX, lue telle quelle) |
| `SpecSampler` + `specularIntensityMult` | brillance |
| `specularFalloffMult` | rugosité : `(2 / (n + 2)) ^ 0,25` (1997 → 0,18, au lieu d'un miroir parfait) |
| `emissiveMultiplier` (`ped_emissive`) | glow, limité aux zones peintes dans le canal bleu de Color 1 |

- **Bijou** : métal et reflets de studio, pour des photos de présentation.
- **Jeu** : non métallique, plus proche du shader GTA.

Le rendu reste une approximation du moteur du jeu.

## Formats pris en charge

- Ressources **Legacy (gen8, RSC7)** : `.ydr` (version 165), `.ydd` (165), `.ytd` (13). C'est le format de FiveM.
- Les fichiers **Enhanced (gen9)** et les fichiers chiffrés (non extraits avec OpenIV ou CodeWalker) sont refusés, avec un message.
- Textures : DXT1, DXT3, DXT5, ATI1, ATI2 (normal maps à 2 canaux), A8R8G8B8, X8R8G8B8, A8B8G8R8, A1R5G5B5, L8, A8, et BC7 si la carte graphique le permet (cas général sur ordinateur).

## Vérifié

- **Lecteur** (`tests/test_lecteur.mjs`, 10/10) : sur les fichiers binaires de test de Sollumz 2.9.0, tous les sommets, indices, paramètres de shader et noms de textures sont identiques à leur version XML CodeWalker ; les pixels de texture sont identiques octet par octet au `.dds` de référence.
- **Décodage** : DXT1 (textures de Teef) et DXT5 identiques au décodage de Blender à 1/255 près.
- **Taille des pages mémoire** : la taille calculée correspond exactement aux données sur tous les fichiers de test, y compris ceux de 3 et 4 pages.
- **Page** (`tests/test_navigateur.cjs`, Chromium sans écran) : texture externe reliée au `.ytd`, texture intégrée, gen9 refusé, photos 2048 × 2048, ZIP valide, aucun débordement à 400 px de large, aucune erreur de console.
- **Orientation** : texture et vue « Face » identiques à l'import Sollumz dans Blender.
- **Relief** (`tests/test_relief.cjs`) : une normal map DirectX en dôme apparaît bombée et éclairée du bon côté.

## Pas encore vérifié

- De **vraies chaînes** : seuls les petits fichiers de test de Sollumz ont été lus. Une grande chaîne (nombreux sommets, plusieurs textures, autres formats de sommets) n'a pas été essayée.
- **`.ydd`** : lu avec la même structure que les `.ydr`, mais aucun `.ydd` binaire n'était disponible pour le tester.
- Textures **DXT3, ATI1, ATI2, BC7** et formats non compressés : décodeurs écrits, sans fichier réel pour les comparer.
- **Glow** : la règle « canal bleu de Color 1 » suit la peinture de Mio Chain Studio ; elle n'a pas été comparée au jeu.

## Reconstruire le fichier

```bash
cd web
npm install
npm run build
```

`npm test` relance la vérification du lecteur. Les fichiers de test viennent de Sollumz : indiquez leur dossier avec `SOLLUMZ_ASSETS=…/sollumz/tests/assets`.
