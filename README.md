# AstroDataReduc OHP

Pipeline de réduction d'images FITS (`.fit` et `.fits`) acquises à l'OHP.

## Réduction photométrique

Pour chaque filtre, le master flat doit être construit à partir des flats bruts après soustraction du master bias, masquage des pixels saturés et normalisation individuelle à une médiane de 1. Le master flat final est également renormalisé à 1.

```text
image_reduite = (image_science - master_bias) / master_flat_normalisé
```

Le master dark est construit par médiane des darks bruts et conserve le niveau de bias. Le choix de correction est explicite : le pipeline utilise exactement le master sélectionné, et signale une erreur s'il est absent.

```text
image_reduite = (image_science - master_dark) / master_flat_normalisé
```

Le master dark doit correspondre à la même configuration et au même temps de pose que les images scientifiques. Le bias et le dark ne sont jamais soustraits simultanément.

Les masters bias, dark et flat sont enregistrés en `float32` afin de conserver
les fractions produites par les combinaisons médianes et la normalisation des
flats. Les fichiers bruts conservent leur type d'origine.

Les images ne doivent être empilées qu'après regroupement par objet, filtre et temps de pose. Les images saturées et les produits déjà réduits ne sont pas des entrées valides pour la construction des masters.

Lors d'un alignement sans référence imposée, l'image ayant le plus petit FWHM
médian des sources stellaires détectées est choisie comme référence, car elle
est la plus nette. Une référence fournie explicitement reste prioritaire.

## Utilisation

Lancer `astrodatareduc` puis choisir une opération :

- `m` : reconstruire le master bias et les masters flats ;
- `r` : réduire des images scientifiques ;
- `align` : aligner automatiquement chaque groupe homogène ;
- `stack` : empiler chaque groupe homogène ;
- `a` : inspecter les fichiers FITS.

Les groupes sont séparés par objet, filtre et temps de pose. Les filtres photométriques ne doivent jamais être mélangés dans une même image empilée.

Les masters sont produits dans `data/photo/masters`. Les flats bruts peuvent être placés directement dans `data/photo/flats` ou dans ses sous-dossiers ; lors de la création des masters flats, la clé FITS contenant le filtre est demandée dans l'interface (avec `FILTER` par défaut) ou en ligne de commande. Elle n'est pas déduite du nom du dossier. Les fichiers suffixés `_norm` sont ignorés comme produits dérivés. Si aucun flat ni aucune image ne contient de filtre, un master flat générique est utilisé.
Lorsque plusieurs filtres sont présents, les flats sont regroupés par filtre et un master flat distinct est créé pour chaque filtre (`master_flat_R`, `master_flat_G`, etc.) ; ils ne sont jamais mélangés.

## Application Qt6

Lancer l'interface avec :

```powershell
uv run astrodatareduc-gui
```

Choisir un dossier parent contenant, selon les besoins :

- `lights` et `flats` ;
- `biases` ;
- `darks` (optionnel).

L'application crée automatiquement `masters`, `process` et, lors de
l'empilement, `recomb_colors`. Le dossier **Sortie finale** est
`recomb_colors` par défaut, mais peut être choisi avec le bouton « Choisir… ».
Les fichiers réduits et alignés vont dans `process`, tandis que les fichiers
empilés `stacked_*.fits` sont écrits dans le dossier final choisi. Ce choix
est conservé lorsque le dossier parent contenant les images d'entrée est
changé.
Trois modes d'alignement sont disponibles : automatique, basique et
« Superposé ». Ce dernier ne cherche aucune étoile et ne transforme pas les
images ; il ajoute seulement le suffixe `_aligned` pour permettre leur
empilement.
Pour les images à matrice de Bayer, le débayering est réalisé avant
l'alignement afin que l'interpolation d'astroalign ne mélange pas les pixels
R, G et B de la mosaïque. L'empilement produit alors directement un cube RGB.

L'onglet **Console** affiche l'avancement des opérations. L'onglet **Visionneuse FITS** ouvre les fichiers `.fit` et `.fits`, et affiche le dernier résultat produit.

L'onglet **Recombinaison RGB** permet de sélectionner un dossier contenant les
fichiers FITS empilés. La clé FITS contenant le filtre est configurable
(`FILTER` par défaut). Le bouton de détection affiche les fichiers associés à
chaque canal et la valeur lue dans leur header. Quatre modes sont disponibles :
`RGB` (R/G/B), `HOO` (Ha/OIII/OIII), `SHO` (SII/Ha/OIII) et
`RGB + HOO` (R+Ha/G+OIII/B+OIII) et `RGB + SHO`
(R+SII/G+Ha/B+OIII). Les filtres OHP
`R Cousin`, `V Cousin`, `B Cousin`, `Ha Baader`, `Halpha`,
`OIII Baader`, `SDSS g`, `SDSS r`, `SDSS i` et `SDSS z` sont reconnus.
Après la détection, le bouton « Aligner les images » aligne les
fichiers sur le canal rouge avec `astroalign` et conserve les résultats dans
`.recombination_aligned`. Le bouton « Recombiner les canaux » réutilise ensuite
ces fichiers alignés, puis le résultat est écrit sous
`rgb_recombined.fits`, `hoo_recombined.fits`, `sho_recombined.fits` ou
`rgb_hoo_recombined.fits` ou `rgb_sho_recombined.fits` sous forme de cube FITS
dans l'ordre `R/G/B`. L'alignement utilise directement `astroalign` sur les
images sélectionnées. Une erreur d'alignement est affichée dans la console et
bloque le traitement afin de ne pas produire une image mal superposée.
Si plusieurs fichiers correspondent à un même canal, une boîte de dialogue
affiche les différences de header et impose de sélectionner le fichier à
utiliser pour chaque canal ambigu avant le lancement du traitement. Fermer
cette boîte annule la détection. Modifier uniquement les coefficients
narrowband ne relance pas l'alignement : le fichier FITS est régénéré
automatiquement après une courte temporisation suivant le mouvement des
sliders, en réutilisant les images déjà alignées.

Chaque recombinaison est également copiée dans un sous-dossier
`recomb_colors` créé automatiquement dans le dossier sélectionné.

Le mode `RGB+Ha` ajoute uniquement Ha au canal rouge :
`R'=(1-aR)R+aR Ha`, tandis que les canaux vert et bleu restent RGB. Le
coefficient Ha est réglable avec le slider rouge et utilise les mêmes
préréglages 30 %, 50 % et 70 %.

Pour `RGB+HOO` et `RGB+SHO`, la contribution narrowband est pondérée par
canal avec trois sliders. Les préréglages proposés sont 30 %, 50 % et 70 %,
mais chaque canal peut ensuite être réglé indépendamment. Les coefficients
sont appliqués après normalisation des images :

```text
RGB+HOO : R'=(1-aR)R+aR Ha, G'=(1-aG)G+aG OIII, B'=(1-aB)B+aB OIII
RGB+SHO : R'=(1-aR)R+aR SII, G'=(1-aG)G+aG Ha, B'=(1-aB)B+aB OIII
```

Le mode **Personnalisé** permet de choisir zéro, un ou plusieurs fichiers pour
chacun des canaux `R`, `G`, `B`, `Ha`, `OIII` et `IR pass`. Les fichiers
supplémentaires sont mélangés avec les canaux RGB à l'aide des sliders :
`Ha` contribue au rouge, `OIII` au vert et `IR pass` au bleu. Un canal RGB
sans fichier est remplacé par un plan noir.

La visionneuse permet de choisir un étirement d'affichage. Elle détecte aussi les images Bayer contenant `BAYERPAT` : la débayerisation automatique ne modifie pas le fichier original. Le bouton dédié permet d'enregistrer une version débayerisée.

La réduction et l'alignement utilisent jusqu'à quatre workers CPU. Cette limite peut être modifiée avec `ASTRODATAREDUC_WORKERS`, par exemple :

```powershell
$env:ASTRODATAREDUC_WORKERS=2
```

L'empilement calcule une médiane pixel par pixel et renseigne `TOTEXP`. Le
choix Bias/Dark est exclusif et peut être désactivé avec « Aucune correction ».
Le flat peut également être activé ou désactivé séparément. Les masters
correspondant aux corrections sélectionnées doivent exister ; une réduction
sans aucun DOF est donc autorisée.

Le bouton « Créer les masters » ne demande que les dossiers nécessaires aux
corrections choisies. Un flat peut être construit sans master bias. Avec
l'option Dark, il produit aussi `master_dark.fits`. Les darks doivent
correspondre aux lights.

Le choix Bias/Dark est exclusif et le master choisi doit exister lorsqu'une
correction est activée. Le bouton « Tout le processus » enchaîne la création
des masters, la réduction, l'alignement et l'empilement.
Lorsque « Aucune correction » et le flat sont désactivés, les lights sont
tout de même réduites puis peuvent être alignées et empilées sans master DOF.
Dans ce cas, les boutons de traitement restent disponibles : la réduction,
l'alignement et l'empilement s'effectuent sans master de calibration.
L'interface accepte également un dossier sélectionné contenant directement
les lights, avec `masters` et `process` à côté, sans sous-dossier `lights`.

<!--
## Limites scientifiques

La réduction peut utiliser un master dark, mais les données photo du dépôt ne contiennent pas nécessairement de série de darks. Les résultats de poses longues doivent donc être interprétés avec prudence tant qu'un master dark adapté au temps de pose et à la température n'est pas produit.

La photométrie quantitative nécessite en plus une calibration en magnitude, une correction de l'extinction atmosphérique et une estimation des incertitudes.
-->

## Installation avec PyInstaller

Pour créer un executable de l'application Qt6 il faut utiliser PyInstaller. Tout d'abord il faut initialiser PyInstaller déjà présent dans les packages `uv` :

```bash
uv sync
```

Pour ensuite compiler l'executable : 

```bash
uv run pyinstaller `
  --name AstroDataReduc `
  --onefile `
  --windowed `
  --clean `
  --paths src `
  --collect-all PySide6 `
  run_gui.py
```

L'executable se trouvera dans le dossier `\dist\AstroDataReduc\`.
Les données FITS ne sont pas intégrées dans l'exécutable. Pour utiliser les
chemins par défaut du mode non graphique, placez le dossier `data` à côté de
`AstroDataReduc.exe`; dans l'interface graphique, un autre dossier peut être
sélectionné directement.

## Stockage des fichiers FITS

Les fichiers `.fit` et `.fits` sont gérés avec **Git LFS** afin de ne pas
stocker directement les grandes données binaires dans Git. Le fichier
`.gitattributes` configure automatiquement cette règle.

Git LFS doit être installé et initialisé sur la machine :

```powershell
git lfs install
```

Sans Git LFS, les fichiers FITS récupérés depuis le dépôt peuvent apparaître
comme de simples pointeurs au lieu de leurs données réelles.
