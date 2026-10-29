# AstroDataReduc OHP

Pipeline de réduction d'images FITS acquises à l'OHP.

## Utilisation

Lancer `astrodatareduc` puis choisir une opération :

- `m` : reconstruire le master bias et les masters flats ;
- `r` : réduire des images scientifiques ;
- `align` : aligner automatiquement chaque groupe homogène ;
- `stack` : empiler chaque groupe homogène ;
- `a` : inspecter les fichiers FITS.

Les groupes sont séparés par objet, filtre et temps de pose. Les filtres
photométriques ne doivent jamais être mélangés dans une même image empilée.

Les masters sont produits dans `data/photo/masters`. Les flats bruts sont
lus depuis `data/photo/flats/<filtre>` ; les fichiers suffixés `_norm` sont
ignorés comme produits dérivés.

## Application Qt6

Une interface graphique est disponible avec :

```powershell
uv run astrodatareduc-gui
```

Elle permet de sélectionner séparément les dossiers des lights, bias,
darks (optionnels), flats, masters et la destination des stacks. Les
opérations longues s'exécutent dans un thread séparé ; les messages du
pipeline sont affichés dans le journal de la fenêtre. Les images réduites
et alignées restent dans le dossier des lights, tandis que les fichiers
`stacked_*.fits` sont écrits uniquement dans le dossier de sortie choisi.

Le bouton « Créer les masters » produit le master bias, les masters flats
et, si un dossier de darks est fourni, un `master_dark.fits` construit par
médiane après soustraction du bias. Les darks doivent être acquis avec un
temps de pose et une température compatibles avec les lights.

## Limites scientifiques

La réduction accepte un master dark optionnel via l'API Python, mais les
données photo du dépôt ne contiennent pas de série de darks. Les résultats
de poses longues doivent donc être interprétés avec prudence tant qu'un
master dark adapté au temps de pose et à la température n'est pas produit.

La photométrie quantitative nécessite en plus une calibration en magnitude,
une correction de l'extinction atmosphérique et une estimation des
incertitudes.