# AstroDataReduc OHP

Pipeline de réduction d'images FITS (`.fit` et `.fits`) acquises à l'OHP.

## Utilisation

Lancer `astrodatareduc` puis choisir une opération :

- `m` : reconstruire le master bias et les masters flats ;
- `r` : réduire des images scientifiques ;
- `align` : aligner automatiquement chaque groupe homogène ;
- `stack` : empiler chaque groupe homogène ;
- `a` : inspecter les fichiers FITS.

Les groupes sont séparés par objet, filtre et temps de pose. Les filtres photométriques ne doivent jamais être mélangés dans une même image empilée.

Les masters sont produits dans `data/photo/masters`. Les flats bruts peuvent être placés directement dans `data/photo/flats` ou dans ses sous-dossiers ; leur filtre est déterminé depuis le header OHP `FLTRNM`, et non depuis le nom du dossier. Les fichiers suffixés `_norm` sont ignorés comme produits dérivés. Si aucun flat ni aucune image ne contient de filtre, un master flat générique est utilisé.

## Application Qt6

Lancer l'interface avec :

```powershell
uv run astrodatareduc-gui
```

Choisir un dossier parent contenant, selon les besoins :

- `lights` et `flats` ;
- `biases` ;
- `darks` (optionnel).

L'application crée automatiquement `masters` et `process`. Les fichiers réduits et alignés vont dans `process`, tandis que les fichiers empilés `stacked_*.fits` restent dans le dossier parent.

L'onglet **Console** affiche l'avancement des opérations. L'onglet **Visionneuse FITS** ouvre les fichiers `.fit` et `.fits`, et affiche le dernier résultat produit.

La visionneuse permet de choisir un étirement d'affichage. Elle détecte aussi les images Bayer contenant `BAYERPAT` : la débayerisation automatique ne modifie pas le fichier original. Le bouton dédié permet d'enregistrer une version débayerisée.

La réduction et l'alignement utilisent jusqu'à quatre workers CPU. Cette limite peut être modifiée avec `ASTRODATAREDUC_WORKERS`, par exemple :

```powershell
$env:ASTRODATAREDUC_WORKERS=2
```

L'empilement calcule une médiane pixel par pixel et renseigne `TOTEXP`. Le choix Bias/Dark est exclusif et le master sélectionné doit exister. Les masters conservent le `dtype` des fichiers sources.

Le bouton « Créer les masters » produit le master bias et les masters flats. Avec l'option Dark, il produit aussi `master_dark.fits`. Les bias sont requis pour créer les flats ; les darks doivent correspondre aux lights.

Le choix Bias/Dark est exclusif et le master choisi doit exister. Le bouton « Tout le processus » enchaîne la création des masters, la réduction, l'alignement et l'empilement.

<!--
## Limites scientifiques

La réduction peut utiliser un master dark, mais les données photo du dépôt ne contiennent pas nécessairement de série de darks. Les résultats de poses longues doivent donc être interprétés avec prudence tant qu'un master dark adapté au temps de pose et à la température n'est pas produit.

La photométrie quantitative nécessite en plus une calibration en magnitude, une correction de l'extinction atmosphérique et une estimation des incertitudes.
-->