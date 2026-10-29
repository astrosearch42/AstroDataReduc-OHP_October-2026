# Réduction photométrique

Pour chaque filtre, le master flat doit être construit à partir des flats
bruts après soustraction du master bias, masquage des pixels saturés et
normalisation individuelle à une médiane de 1. Le master flat final est
également renormalisé à 1.

Sans master dark disponible :

```text
image_reduite = (image_science - master_bias) / master_flat_normalisé
```

Avec un master dark déjà produit pour la même configuration et le même
temps de pose :

```text
image_reduite = (image_science - master_bias - master_dark) / master_flat_normalisé
```

Les images ne doivent être empilées qu'après regroupement par objet, filtre
et temps de pose. Les images saturées et les produits déjà réduits ne sont
pas des entrées valides pour la construction des masters.