# AstroDataReduc OHP

Pipeline de réduction d'images FITS (`.fit` et `.fits`) acquises à l'OHP.

## Utilisation

Lancer `astrodatareduc` puis choisir une opération :

- `m` : reconstruire le master bias et les masters flats ;
- `r` : réduire des images scientifiques ;
- `align` : aligner automatiquement chaque groupe homogène ;
- `stack` : empiler chaque groupe homogène ;
- `a` : inspecter les fichiers FITS.

Les groupes sont séparés par objet, filtre et temps de pose. Les filtres
photométriques ne doivent jamais être mélangés dans une même image empilée.

Les masters sont produits dans `data/photo/masters`. Les flats bruts peuvent
être placés directement dans `data/photo/flats` ou dans ses sous-dossiers ;
leur filtre est déterminé depuis le header OHP `FLTRNM`, et non depuis le nom
du dossier. Les fichiers suffixés `_norm` sont ignorés comme produits dérivés.
Si aucun flat ni aucune image ne contient de filtre, un master flat générique
est utilisé.

## Comparer les masters à ceux de Siril

Le module `compared_masters` apparie explicitement les masters `bias`, `dark`
et `flat` malgré leurs noms de fichiers différents. Il calcule les écarts
pixel par pixel (MAE, RMSE, biais, corrélation et ajustement linéaire), compare
les headers et écrit un rapport JSON, un résumé CSV ainsi qu'une figure PNG
pour chaque master :

```powershell
uv run python -m astrodatareduc_ohp_october_2026.compared_masters
```

Les chemins et le dossier de sortie peuvent être personnalisés avec
`--siril-dir`, `--mine-dir` et `--output-dir`. Les figures utilisent les
percentiles 1--99 pour l'affichage, tandis que les métriques sont calculées
sur les valeurs FITS, sans dépendre d'un étirement visuel.

Les masters de calibration utilisent exclusivement les noms `master_bias.fits`,
`master_dark.fits` et `master_flat_<filtre>.fits`. Les bias et dark Siril normalisés sont reconvertis dans l'échelle
ADU des images brutes, et le flat est renormalisé à une médiane de 1 avant la
réduction.

## Application Qt6

Une interface graphique est disponible avec :

```powershell
uv run astrodatareduc-gui
```

Elle permet de sélectionner un seul dossier parent. L'application y détecte
automatiquement les sous-dossiers `Lights`, `Biases`, `Darks` (optionnel) et
`Flats`, sans tenir compte de la casse. Elle crée `Masters` pour les masters
et `Process` pour les fichiers réduits et alignés intermédiaires ; les stacks
finaux sont écrits directement dans le dossier parent. Les
opérations longues s'exécutent dans un thread séparé ; les messages du
pipeline et les calculs effectués sont affichés en temps réel dans l'onglet
Console. Les options et boutons sont regroupés dans le volet gauche. Un onglet
Visionneuse FITS permet d'ouvrir des fichiers `.fit` ou `.fits` et affiche
automatiquement le dernier fichier produit par une opération, notamment le
stack final. Les images réduites et alignées sont écrites dans `Process`,
tandis que les fichiers `stacked_*.fits` sont écrits dans le dossier parent.
La visionneuse propose un volet déroulant pour choisir l'étirement
d'affichage : linéaire, logarithmique, puissance, racine carrée, carré,
`asinh`, `sinh` ou égalisation d'histogramme. Ces transformations concernent
uniquement l'aperçu et ne modifient jamais les données FITS. Pour une image
Bayer 2D contenant `BAYERPAT`, le bouton « Débayeriser l'image » crée un
nouveau fichier suffixé `_debayered` et l'ouvre immédiatement dans la
visionneuse. Lorsqu'une image 2D contient le mot-clé `BAYERPAT`, la
visionneuse la débayerise automatiquement pour l'aperçu en respectant le
motif de la caméra. Une image mono sans ce mot-clé reste affichée en niveaux
de gris. Cette débayerisation automatique ne modifie pas le fichier FITS ;
un message le précise et le bouton dédié permet d'enregistrer une version
débayerisée en couleur.
La fenêtre possède une taille minimale pour conserver une interface lisible ;
le volet gauche n'affiche qu'un défilement vertical si son contenu dépasse la
hauteur disponible.
Les fichiers d'entrée peuvent utiliser l'extension `.fit` ou `.fits`.
La réduction et l'alignement utilisent plusieurs workers CPU pour traiter les
images indépendantes en parallèle, avec un maximum prudent de quatre workers
par défaut afin de préserver la mémoire. Cette limite peut être ajustée avec
la variable d'environnement `ASTRODATAREDUC_WORKERS` (par exemple
`$env:ASTRODATAREDUC_WORKERS=2` sous PowerShell) ; une valeur trop élevée peut
ralentir le traitement ou saturer la RAM avec de grandes images.
L'empilement calcule la médiane simple pixel par pixel et écrit le temps de
pose total (`TOTEXP`). Une case permet de débayeriser les images Bayer après
l'empilement ; les canaux RGB sont alors équilibrés par leur médiane robuste.
Sans cette case, la sortie reste une matrice Bayer 2D.
Le stacking utilise une combinaison médiane simple, sans rejet statistique
supplémentaire ni mode rapide.
Lors d'une réduction, le choix Bias ou Dark est exclusif : le master
sélectionné doit exister, puis le master flat du filtre est divisé. Le header
`CALIBRAT` du fichier produit indique la correction utilisée. Les masters
sont calculés en précision étendue puis écrits en `float32`, comme le format
de travail recommandé par Siril. Le passage de `float64` à `float32` à
l'écriture ne suffit pas à expliquer une différence visuelle : les écarts
importants viennent surtout de la soustraction de la correction, de la
normalisation multiplicative des flats et de l'étirement utilisé pour
afficher les images. Le master dark conserve le niveau de bias et doit
correspondre au temps de pose et à la température des lights.

Références Siril :
[calibration](https://siril.readthedocs.io/en/latest/preprocessing/calibration.html),
[registration](https://siril.readthedocs.io/en/latest/preprocessing/registration.html)
et [stacking](https://siril.readthedocs.io/en/stable/preprocessing/stacking.html).

La création des masters utilise désormais des tableaux `float32` pendant les
empilements, ce qui réduit environ de moitié la mémoire temporaire par rapport
à `float64`, sans changer le calcul médian. Le stacking réutilise ses buffers
de calcul au lieu de créer une seconde copie complète des images.

Le bouton « Créer les masters » exige toujours des fichiers bias, car ils
sont nécessaires pour corriger les flats. Il produit le master bias et les
masters flats. Si Dark est sélectionné, il exige également des fichiers dark
et produit un `master_dark.fits` construit par médiane en conservant l'offset
du capteur, comme attendu pour une calibration Siril. Les darks doivent être acquis avec un
temps de pose et une température compatibles avec les lights.
Le choix Bias/Dark est explicite et le master sélectionné doit exister ;
sinon la réduction affiche une erreur. Le bouton « Tout le processus »
enchaîne automatiquement la création des
masters, la réduction, l'alignement et le stacking, en respectant le choix
Bias/Dark et l'option de débayerisation. Chaque étape attend la fin de la
précédente ; les masters existants font l'objet des mêmes demandes de
recréation que dans l'action séparée.

## Limites scientifiques

La réduction peut utiliser un master dark, mais les données photo du dépôt
ne contiennent pas nécessairement de série de darks. Les résultats de poses
longues doivent donc être interprétés avec prudence tant qu'un master dark
adapté au temps de pose et à la température n'est pas produit.

La photométrie quantitative nécessite en plus une calibration en magnitude,
une correction de l'extinction atmosphérique et une estimation des
incertitudes.