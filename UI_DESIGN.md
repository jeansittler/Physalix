# Design system Physalix

Le thème clair est centralisé dans `physalix/ui/theme.py`. La structure `Theme`
contient la palette, les niveaux typographiques, les rayons, les dimensions de
contrôles et l’échelle d’espacement (4, 8, 12, 16 et 24 px). Le bleu du logo reste
la couleur primaire ; les couleurs d’état ne doivent pas remplacer un libellé ou
une autre indication visible.

Les règles Qt communes sont produites par `stylesheet()`. Elles couvrent les
boutons, champs, listes, cases à cocher, cartes, tableaux, menus, barres de
défilement et leurs états interactifs. Les composants de présentation réutilisables
se trouvent dans `physalix/ui/components.py`.

Pour ajouter un écran ou un composant :

1. utiliser les layouts Qt et les espacements de `LIGHT` plutôt que des valeurs
   locales ;
2. utiliser `panel()` pour une carte fonctionnelle ;
3. appliquer `role(widget, "primary")`, `"quiet"`, `"danger"`, `"muted"` ou
   `"caption"` pour exprimer la hiérarchie ;
4. ajouter un nouveau token dans `Theme` si une valeur doit être partagée, puis
   vérifier au minimum les états normal, hover, focus et disabled.
