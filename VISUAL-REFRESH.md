# Refonte visuelle de Physalix

## Organisation conservée

Physalix reste une application native **PySide6 / Qt Widgets**, avec **PyQtGraph**
pour les tracés, **SciPy** pour les ajustements et **PyAV** pour le décodage vidéo.
`MainWindow` conserve son `QTabWidget`, ses cinq classes d'écran, le modèle de
données partagé et les connexions de signaux existantes. Aucun framework,
moteur de calcul ou bibliothèque d'icônes supplémentaire n'est introduit.

Avant cette intervention, le style reposait sur Fusion, la palette système,
quelques couleurs locales de PyQtGraph et le HTML des rapports. Aucune collection
d'icônes ni feuille QSS globale n'était présente. Le message « Base de
développement » était une chaîne statique de la fenêtre principale, sans rôle
fonctionnel : il devient « Physalix — Prêt ».

## Thème et composants

- `physalix/ui/theme.py` : tokens du thème clair, palette Qt explicite, Segoe UI,
  QSS global, hiérarchie des boutons, champs, cases à cocher, tableaux, menus,
  barres de défilement et styles HTML des résultats.
- `physalix/ui/components.py` : rôles de présentation, marges de page, panneaux,
  aide dépliable, cartes adaptatives et conteneurs défilants pour petites fenêtres.
- `physalix/ui/icons.py` : cinq pictogrammes SVG simples rendus par Qt à plusieurs
  résolutions, avec variantes actives et désactivées.
- `physalix/ui/resources/*.svg` : cinq petits fichiers pour les chevrons et la
  coche. `Physalix.spec` les inclut dans l'exécutable distribué.

Les propriétés `role` distinguent `primary`, `danger`, `panel`, `sectionTitle`,
`caption`, `muted`, `brand` et `brandTitle`. Les boutons secondaires utilisent le
style standard commun. La palette Qt impose le thème clair même si Windows est
sombre. Aucun sélecteur de thème sombre ni nouvelle fenêtre de paramètres.

## Changements par écran

| Écran | Présentation |
| --- | --- |
| Données | Tableau blanc, traits fins, en-têtes teintés, lignes Grandeur/Unité distinguées, sélection claire et cadre de cellule bleus, lignes de 32 px, bouton Ajouter une grandeur, aide dépliable. |
| Graphique | Barre d'outils harmonisée, accès au menu existant par un bouton, réglages des séries dans des panneaux, tracé dominant sur fond blanc, grille allégée, bleu Physalix par défaut pour la première série, messages discrets. |
| Modélisation | Cartes Modèle et Intervalle et options, côte à côte ou empilées selon la largeur, bouton de calcul principal, rapport blanc et typographie harmonisée, aide détaillée conservée. |
| Pointage vidéo | Groupes Fichier, Étalonnage, Pointage et Lecture, état lisible, surface vidéo sombre préservée, loupe encadrée, slider bleu, contrôles accessibles par défilement si nécessaire. |
| Calculs | Deux cartes adaptatives pour la dérivée et la formule, clavier mathématique conservé, boutons de création principaux, explications secondaires, tableau récapitulatif harmonisé. |

La navigation supérieure conserve les cinq modules, avec une identité sobre,
des icônes vectorielles et un état actif bleu/blanc. Aux petites largeurs, les
flèches natives permettent de parcourir les onglets. Les outils des écrans
Graphique et Vidéo défilent sous leur taille confortable au lieu de se superposer.

## Fichiers modifiés

`physalix/app.py`, `physalix/ui/main_window.py`, `data_tab.py`, `graph_tab.py`,
`graph_series.py`, `graph_axis.py`, `graph_legend.py`, `modeling_tab.py`,
`fit_report.py`, `video_tab.py`, `calculations_tab.py`, `Physalix.spec`, `README.md`.
Les chemins abrégés des écrans sont tous dans `physalix/ui/`.

Fichiers créés : les trois modules de thème/composants/icônes, cinq SVG,
`tests/test_ui_theme.py`, ce document, et les scripts, journaux et captures dans
`artifacts/visual-review/`. Une copie des sources avant modification se trouve
dans `artifacts/visual-review/before/`, car ce dossier de travail n'est pas un
dépôt Git.

## Fonctions conservées et validation

Les fichiers des moteurs `calculations.py`, `fitting.py`, `video.py`, ainsi que
`ui/video_tracking.py`, `ui/units.py` et `ui/fill_table.py` sont **identiques octet
par octet** à la copie initiale. Les modifications des écrans portent sur leur
construction visuelle ; la présentation du rapport ne change aucun nombre ni
formule. Dans l'ajout/retrait des séries, seuls la palette initiale et le
dimensionnement du panneau changent. Les couleurs choisies par l'utilisateur,
le zoom, les intervalles, les calculs et le pointage restent gérés comme avant.

Les fonctions de sauvegarde/export fichier ne sont pas implémentées dans cette
version initiale : elles n'ont pas été ajoutées. L'import/export de tableau par
copier-coller reste inchangé, et les données restent en mémoire pendant la session.

- Avant modification : **53 tests réussis**.
- Après modification : **56 tests réussis**, comprenant les 53 tests existants
  et trois contrôles de navigation, de redimensionnement et d'accès à l'aide.
- Suite entièrement initialisée avec le thème : **56 tests réussis** en mode
  Qt offscreen, mode prévu par les tests existants.
- Revue des cinq écrans par captures Qt avec le moteur **Windows** : zones
  clientes 1366 × 700 et 1920 × 1000 (place laissée au cadre et à la barre des
  tâches), puis 900 × 620 et 640 × 420. Accès aux contrôles vérifié par défilement.
- Parcours Windows complémentaire : choix d'une unité par la souris, réticule,
  chargement vidéo, images précédente/suivante, étalon, origine, pointage,
  annulation, lecture et fermeture : **réussis**.
- `build-demo.ps1` : **réussi**, exécutable et ZIP produits. La fenêtre Qt nommée
  Physalix a été détectée après lancement de l'exécutable, puis fermée proprement.

Deux tests de souris échouent dans la suite native Windows brute, **également
sur les sources d'origine** : survol du réticule et sélection d'une unité dans
une liste. Le parcours complémentaire attend l'affichage du popup et envoie
explicitement un événement Qt de déplacement pour le réticule ; ces contrôles
passent. Les tests fonctionnels d'origine ne sont pas modifiés pour masquer ces
limitations de l'automatisation native.

PyInstaller signale l'absence de `OpenGL` pour le module optionnel
`pyqtgraph.opengl` et d'un import caché `scipy.special._cdflib`. La construction
aboutit ; ces avertissements restent consignés dans le journal du build.

Commandes de reproduction (depuis la racine du projet) :

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -q
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe artifacts/visual-review/verify.py
$env:QT_QPA_PLATFORM = 'windows'
.venv/Scripts/python.exe artifacts/visual-review/capture.py
.venv/Scripts/python.exe artifacts/visual-review/native_smoke.py
./build-demo.ps1
```
