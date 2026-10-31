# Réduction photométrique

Pour chaque filtre, le master flat doit être construit à partir des flats
bruts après soustraction du master bias, masquage des pixels saturés et
normalisation individuelle à une médiane de 1. Le master flat final est
également renormalisé à 1.

```text
image_reduite = (image_science - master_bias) / master_flat_normalisé
```

Le master dark est construit par médiane des darks bruts et conserve le
niveau de bias. Le choix de correction est explicite : le pipeline utilise
exactement le master sélectionné, et signale une erreur s'il est absent.

```text
image_reduite = (image_science - master_dark) / master_flat_normalisé
```

Le master dark doit correspondre à la même configuration et au même temps
de pose que les images scientifiques. Le bias et le dark ne sont jamais
soustraits simultanément.

Les images ne doivent être empilées qu'après regroupement par objet, filtre
et temps de pose. Les images saturées et les produits déjà réduits ne sont
pas des entrées valides pour la construction des masters.