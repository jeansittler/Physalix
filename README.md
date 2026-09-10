# Physalix

Physalix est une application de bureau Windows destinée à l’exploitation,
l’analyse et la visualisation de données expérimentales en physique-chimie,
notamment dans l’enseignement secondaire. Le projet privilégie une interface
simple, des fichiers de travail échangeables et des calculs reproductibles.

La version actuelle est **Physalix 1.1.3**. Son code source est publié sous
licence **GNU GPL-3.0-only**. Les exécutables publiés actuellement ne sont pas
encore signés numériquement ; la signature numérique des futures versions est
en cours de préparation.

L’application contient six espaces : **Données / Tableur**,
**Graphique**, **Modélisation**, **Pointage vidéo**, **Calculs** et **Statistiques**. L’onglet Données / Tableur permet de saisir des mesures et des formules de cellules.
L’onglet Graphique affiche les mesures sous forme de nuage de points.
L’onglet Modélisation ajuste des fonctions aux mesures. Les tableaux peuvent être importés par copier-coller ou depuis un fichier CSV.

## Enregistrer et échanger un travail

- **Fichier → Enregistrer** (`Ctrl+S`) sauvegarde le travail dans un fichier **`.physalix`**.
  **Enregistrer sous…** permet d’en conserver une autre version. **Ouvrir un projet…**
  (`Ctrl+O`) restitue le tableur, les noms et unités, les formules et colonnes calculées,
  les graphiques, les séries, les modélisations et leurs résultats, les intervalles et
  les outils graphiques. Les calculs restent liés aux mesures et modifiables.
- La vidéo préparée, son étalonnage et ses points sont intégrés au projet : le fichier
  peut donc être volumineux, mais ne dépend pas du fichier vidéo d’origine.
  Les historiques Annuler/Rétablir ne sont pas conservés après réouverture.
- **Nouveau projet** (`Ctrl+N`), l’ouverture et la fermeture proposent d’enregistrer
  les modifications. Une écriture interrompue ne remplace pas le fichier précédent.
- **Importer un CSV…** (`Ctrl+I`) affiche un aperçu avec choix du séparateur
  (automatique, point-virgule, virgule ou tabulation) et des en-têtes. Les colonnes
  s’ajoutent au tableau existant ; un tableau initial vierge est réutilisé. Les noms
  en double sont suffixés. Les en-têtes `Temps [s]` restituent aussi les unités.
  Les cellules vides sont préservées ; les textes importés ne sont pas exécutés
  comme formules. UTF-8 et Windows-1252 sont acceptés.
- **Exporter le tableur en CSV…** (`Ctrl+E`) écrit les **valeurs calculées**, dans
  l’ordre visible des colonnes, avec noms et unités. Le fichier utilise UTF-8 avec
  signature, le point-virgule et la virgule décimale, pour Excel en français.
  Dans une autre configuration régionale, choisir ces paramètres à l’import dans Excel.
  Le CSV ne contient pas les graphiques ni les définitions des calculs : conserver
  aussi le projet `.physalix` pour reprendre le travail.

## Saisir des données

- La première ligne du tableau contient les noms des grandeurs : remplacez x et y
  par exemple par `Volume` et `pH`. Double-cliquez pour modifier une cellule,
  ou sélectionnez-la et commencez à taper.
- La deuxième ligne contient les **unités**, indépendamment des noms. Cliquez
  sur une cellule pour choisir une suggestion dans la liste ou taper librement
  une unité, y compris des symboles Unicode et des unités composées.
  Exemples : `mL`, `mol/L`, `m/s²`, `°C`, `Ω`, `kg·m²/s³`.
  Pour le pH, choisissez `Sans unité` ou laissez la cellule vide.
  **Entrée** valide et descend à la première mesure ; **Tab** passe à l’unité
  suivante ; **Échap** annule la modification.
  Les unités sont des indications : leur modification ne convertit pas les valeurs.
- Chaque ligne numérotée correspond à une mesure : les valeurs de volume et de pH
  sur la même ligne sont associées. Une cellule vide reste une valeur manquante.
- **Entrée** valide puis descend dans la même colonne ; **Tab** valide puis passe
  à la cellule suivante. **Échap** annule la modification en cours.
- Les nombres acceptent la virgule ou le point décimal et la notation scientifique
  (ex. `1,2e-3`). **Suppr** efface les cellules sélectionnées hors édition.
- **Ctrl+Z** ou **Annuler** restaure la dernière modification de cellules ;
  **Ctrl+Y** ou **Rétablir** la réapplique. Un effacement de sélection, un collage
  ou une recopie s'annule en une seule fois, avec les formules d'origine.
  L'historique conserve les 100 dernières actions. Les lignes ou colonnes vides
  ajoutées pour recevoir un collage restent disponibles après son annulation.
- Glissez l'en-tête d'une colonne pour la déplacer dans le tableau. Sa lettre
  (A, B, C…) reste attachée à la grandeur, avec ses formules, unités et liens vers
  les graphiques. Copier et coller suivent l'ordre visible des colonnes.
  Le déplacement peut également être annulé avec **Ctrl+Z**.
- **Ctrl+C** copie les cellules sélectionnées ; **Ctrl+V** colle à partir du coin
  supérieur gauche de la sélection. Ces commandes sont aussi accessibles par clic droit.
  Les tableaux copiés depuis Excel ou LibreOffice (tabulations), ainsi que les données
  séparées par des points-virgules, sont acceptés. Les lignes et colonnes nécessaires
  sont ajoutées automatiquement ; les valeurs de la zone de destination sont remplacées.
  Pour coller seulement des mesures, sélectionnez une ligne numérotée. Pour inclure
  les noms et unités, commencez sur la ligne Grandeur avec ces deux lignes dans la copie.
  Une valeur qui n'est ni numérique ni une formule dans les mesures, ou une colonne calculée dans la zone
  de destination annule le collage entier avec un message explicatif.
- Le tableau propose vingt lignes de mesures et s’allonge lors de la saisie sur
  la dernière ligne. Le bouton **Ajouter une grandeur**, juste au-dessus du tableau,
  crée une colonne vide et permet de saisir immédiatement son nom, même si toutes
  les colonnes ont été supprimées. Cette commande est aussi accessible par clic droit
  dans le tableau ou sur ses en-têtes.
- Pour supprimer une colonne, faites un clic droit sur **Grandeur 1**, **Grandeur 2**…
  ou sur son nom, puis choisissez **Supprimer la grandeur…** et confirmez.
  La confirmation indique aussi les grandeurs calculées dépendantes qui seront supprimées.
  La suppression complète d'une grandeur reste une opération confirmée, hors de
  l'historique des cellules ; elle réinitialise cet historique.
- Pour incrémenter une colonne, saisissez par exemple `0` puis `1` dans deux
  cellules consécutives. Sélectionnez ces deux cellules à la souris, puis faites
  glisser le petit carré en bas à droite de la sélection vers le bas. Relâchez
  pour écrire `2`, `3`, `4`, etc. dans les cellules couvertes par le cadre.
  Ces cellules sont remplacées ; les autres colonnes restent intactes.
- Le pas est déduit des deux premières valeurs : `0` et `0,5` donnent `1`, `1,5`,
  etc. Une seule valeur sélectionnée est répétée. La poignée apparaît pour une
  sélection numérique continue dans une seule colonne, à pas constant.
  Maintenez la souris près du bord inférieur pour défiler et ajouter des lignes.
  **Échap** annule la recopie avant de relâcher la souris.

### Formules directement dans les cellules

- Saisissez `=A1*2` dans B1 : A1 désigne la **première mesure** de la colonne A,
  sans compter les lignes Grandeur et Unité. La cellule affiche le résultat ;
  la barre **fx** et l'édition de la cellule affichent la formule originale.
- Sélectionnez B1 et tirez sa poignée vers le bas : B2 reçoit `=A2*2`, B3 `=A3*2`…
  Les références `$A$1`, `$A1` et `A$1` fixent respectivement les deux coordonnées,
  la colonne ou la ligne. Copier puis coller à l'intérieur de Physalix adapte aussi
  les références ; une copie vers un autre logiciel fournit les valeurs affichées.
- Opérations : `+`, `-`, `*`, `/`, `^`. Fonctions : `RACINE` / `SQRT`, `ABS`,
  `SIN`, `COS`, `TAN`, `EXP`, `LN` (népérien), `LOG` / `LOG10` (base 10), `SOMME` / `SUM`,
  `MOYENNE` / `AVERAGE`, `MIN`, `MAX`. Constantes : `pi` et `e`.
  Exemples : `=RACINE(A1^2+B1^2)`, `=SOMME(A1:A5)`, `=MAX(A1;B1;0)`.
  Séparez les arguments par `;` ; la virgule reste utilisable comme décimale.
- Les résultats se recalculent quand les sources changent et sont utilisables
  dans les graphiques et les calculs. Une cellule vide référencée seule vaut zéro ;
  les cellules vides d'une plage sont ignorées par les fonctions d'agrégation.
- Une erreur apparaît dans la cellule (`#DIV/0!`, `#REF!`, `#CYCLE!`, `#ERREUR!`) ;
  survolez-la pour lire l'explication et modifiez la formule pour la corriger.
  Les références à une colonne supprimée deviennent `#REF!`.

## Statistiques d'une grandeur

- Dans **Statistiques**, choisissez une grandeur. Par défaut, toutes les lignes
  sont prises en compte. Décochez **Toutes les lignes** pour indiquer les numéros
  de début et de fin, bornes incluses, selon la numérotation des mesures du tableur.
- Vous pouvez aussi sélectionner une plage continue dans une seule colonne du
  tableur, puis cliquer sur **Utiliser la sélection du tableur** dans Statistiques.
- Indicateurs : effectif, moyenne, médiane, minimum, maximum, étendue, Q1, Q3,
  écart interquartile, variance et écart-type de la série (diviseur n), variance et
  écart-type corrigés (diviseur n − 1), incertitude-type A de la moyenne et somme.
  Les unités sont reprises de la grandeur ; les variances utilisent leur carré.
- Q1 et Q3 correspondent aux rangs ⌈n/4⌉ et ⌈3n/4⌉ de la série triée, sans
  interpolation. Pour un effectif pair, la médiane est la moyenne des deux valeurs centrales.
- L'incertitude-type A vaut s/√n, avec l'écart-type corrigé s. Elle s'applique à
  des mesures répétées indépendantes d'une même grandeur et ne couvre pas les
  autres sources d'incertitude. Les statistiques corrigées demandent au moins 2 valeurs.
- Les cellules vides, non numériques, non finies et les erreurs de formules sont
  exclues et comptées séparément. Les résultats de formules valides sont inclus.
  Les calculs se mettent à jour avec les données ; ils ne modifient pas le tableur.
- **Copier les résultats** copie un tableau avec la grandeur, l'intervalle, les
  valeurs, les unités et les définitions. Un tiret indique une statistique indisponible ;
  son explication est accessible au survol.

## Afficher un graphique

- **Nouveau graphique** crée un graphique indépendant à partir du même tableur.
  Chaque graphique conserve ses séries, couleurs, échelles, outils et modélisations.
  **Renommer** donne un nom au graphique actif.
- **Disposition** propose **Onglets** (onglets déplaçables), **Côte à côte**,
  **Superposés** et **Libre**. En mode Libre, déplacez les fenêtres par leur titre
  et redimensionnez-les par leurs bords. Les dispositions de comparaison affichent
  les courbes avec des contrôles réduits ; **Réglages de ce graphique** ouvre
  directement sa configuration en onglet. Repassez ensuite à la disposition souhaitée.
- L'onglet **Modélisation** cible le graphique actif et indique son nom.
  Fermer un graphique retire ses tracés, sans supprimer les données du tableur ;
  le dernier graphique reste disponible.

- La liste **Série à régler** donne accès aux réglages d'une série à la fois :
  grandeurs **X** et **Y**, couleur, liaison et visibilité. Toutes les séries
  cochées restent tracées ; changer de sélection conserve le zoom du graphique.
  Toutes les colonnes du tableau sont disponibles avec leur numéro, nom et unité.
- Ajouter des séries n'augmente pas la hauteur des réglages. **Masquer les réglages**
  libère encore de la place pour la courbe ; **Afficher les réglages** les rétablit.
- Cliquez sur **Ajouter une série** pour superposer d’autres grandeurs. La nouvelle
  série reprend l’abscisse précédente et propose une ordonnée encore inutilisée
  lorsqu’il en existe une. Vous pouvez choisir une abscisse différente pour chaque série.
- Chaque série possède sa couleur, son option **Relier**, une case pour la masquer
  et un bouton **Retirer**. Retirer une série ne supprime aucune donnée du tableau.
  Une légende identifie les séries avec leurs grandeurs et unités.
- Dans les réglages d'une série, choisissez **Y gauche** (par défaut) ou **Y droite**.
  L'axe droit apparaît dès qu'une série visible l'utilise ; son titre et son unité
  correspondent aux grandeurs choisies. Les deux échelles verticales s'ajustent
  indépendamment, tandis que l'axe X reste commun. Les séries utilisant un même
  côté partagent son échelle. Le retour à **Y gauche** retire l'axe droit s'il n'est
  plus utilisé. Les modélisations et constructions suivent l'axe de leur série.
- Chaque couple numérique d’une même ligne devient une croix **+**.
  Les lignes incomplètes sont ignorées ; le détail par série est accessible en
  survolant le nombre de séries visibles, sous le graphique.
- Cochez **Relier** sur la série voulue pour joindre ses points valides par des segments,
  dans l’ordre des lignes du tableau, sans tri ni modélisation.
  Les lignes ignorées ne produisent pas de point : les points valides restants
  sont reliés les uns aux autres.
- **Couleur…** ouvre une palette pour les croix et leurs segments. La couleur et
  l’option de liaison sont indépendantes pour chaque série et conservées pour ses
  couples d’axes pendant la session.
- Les axes sont gradués, avec une grille, les noms des grandeurs et leurs unités.
  Le cadrage s’ajuste automatiquement à l’ensemble des séries visibles lors du
  choix des axes et des changements de données. Les séries partagent l’échelle X
  et l’échelle Y de leur côté, sans conversion d’unité. L’axe droit s’active
  explicitement avec le choix **Y droite**.
- Utilisez la molette pour zoomer et faites glisser pour déplacer la vue.
  **Ajuster la vue** permet de retrouver l’ensemble des points.
- Un **clic droit** ouvre les commandes **Zoom avant**, **Zoom arrière**,
  **Ajuster la vue**, **Zoom par rectangle** et **Déplacer la vue**.
  En mode rectangle, tracez une zone avec le bouton gauche pour l’agrandir.
- Activez **Réticule** dans ce menu : deux lignes suivent la souris dans le
  graphique et les coordonnées X et Y, avec les grandeurs et unités, apparaissent
  sous le tracé sans cliquer. La lecture est libre, sans aimantation aux mesures.
  Les lignes disparaissent lorsque la souris sort du graphique. Décochez
  **Réticule** pour désactiver l’outil.
- Les choix sont conservés lors d’un renommage ou de l’ajout d’une colonne.

Le composant graphique utilise [PyQtGraph](https://pyqtgraph.readthedocs.io/).
Sur une installation existante, mettez à jour les dépendances avant de relancer :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Modéliser les mesures

Depuis le graphique, cliquez sur **Modéliser…** (également dans le menu du clic
droit), puis choisissez la série visible à ajuster. Ses axes déterminent les couples
utilisés, sans conversion d’unité. Les lignes incomplètes ou non finies sont ignorées.

- Modèles disponibles : constante `c`, linéaire `a*x`, affine `a*x+b`, carrée
  `a*x²`, second degré `a*x²+b*x+c`, exponentielle, charge et décharge de
  condensateur, sinusoïde et formule utilisateur.
- Pour les exponentielles et les sinusoïdes, `x0` est la première abscisse de
  l’intervalle ajusté, fixée et affichée. Les modèles de condensateur ajustent
  l’amplitude `A`, la constante de temps positive `tau` et le décalage `c`.
  La sinusoïde ajuste `A`, `omega`, `phi` et `c` (angles en radians).
- Cochez **Limiter la modélisation à un intervalle d’abscisses** pour saisir les bornes ou cliquez sur
  **Sélectionner sur le graphique**, puis déplacez les limites de la bande.
  Cliquez sur **Valider l’intervalle et calculer** directement sur le graphique,
  ou revenez dans Modélisation pour lancer le calcul. Les bornes sont incluses.
  Après le calcul, la bande de sélection disparaît et les bornes sont conservées.
  **Sélectionner sur le graphique** permet de la retrouver pour modifier l’intervalle.
  **Masquer la sélection** la cache sans lancer de calcul.
- Le **Modèle utilisateur** accepte le membre droit d’une expression, par exemple
  `a*Temps^2+b*Temps+c`, et les paramètres `a=1 ; b=0 ; c=0`.
  `x` désigne toujours l’abscisse choisie ; son nom est aussi utilisable s’il
  constitue un identifiant valide. Pour les noms contenant des espaces ou des
  symboles, utilisez `x`. Fonctions : `sin`, `cos`, `tan`, `exp`, `log`, `log10`,
  `sqrt`, `abs` ; constantes : `pi`, `e`. Déclarez 1 à 8 paramètres.
- **Calculer la modélisation** affiche les coefficients, R², la RMSE et l’écart
  type résiduel. **Voir le graphique** montre la courbe en pointillés dans la couleur
  de sa série, limitée au domaine des mesures sélectionnées.
- R² vaut `1 − somme(résidus²)/somme((y−moyenne)²)` ; il peut être négatif et
  est indéfini pour une ordonnée constante. La RMSE vaut `√(somme(résidus²)/n)`.
  L’écart type résiduel vaut `√(somme(résidus²)/(n−p))` et nécessite plus de
  points que de paramètres. Ces deux écarts sont dans l’unité de l’ordonnée.
  Les mesures ont toutes le même poids. Un bon R² ne valide pas à lui seul le
  modèle physique ; les ajustements non linéaires peuvent atteindre un minimum local.
- Plusieurs modélisations peuvent être conservées sur une même série, avec le même
  modèle ou des modèles différents, sur toutes les mesures ou des intervalles choisis.
  Cliquez sur **Ajouter une modélisation**, choisissez les réglages puis calculez.
  La liste **Modélisation** permet de consulter les résultats, de retrouver les
  réglages et de recalculer uniquement la modélisation sélectionnée.
- Pour un dosage conductimétrique, choisissez le modèle **Affine** sur la partie
  décroissante puis sur la partie croissante. **Prolonger la droite sur le domaine
  des mesures** affiche les prolongements en pointillés fins, sans modifier le
  calcul. Les deux droites ont des couleurs distinctes ; activez le **Réticule**
  par clic droit dans le graphique pour lire l’abscisse de leur intersection.
- Masquer une série masque toutes ses modélisations ; **Retirer cette modélisation**
  supprime uniquement celle sélectionnée. Modifier les données, les unités ou les
  axes de la série retire toutes ses modélisations périmées et nécessite de les recalculer.

Les modélisations sont enregistrées avec le projet.

## Pointage vidéo : ouverture et lecture

- Dans **Pointage vidéo**, cliquez sur **Ouvrir une vidéo…**. Le filtre
  **Tous les fichiers** permet de sélectionner une extension non listée.
- Le décodage utilise PyAV et les bibliothèques FFmpeg fournies avec sa roue Python.
  La compatibilité dépend des décodeurs inclus ; tous les encodages ne sont pas garantis.
  Les tests utilisent des fichiers AVI/MPEG-4, MP4/MPEG-4, MKV/FFV1 et MPEG/MPEG-2.
- Une préparation en arrière-plan décode les images dans un cache PNG sans perte.
  Le nombre d’images préparées est affiché ; **Annuler la préparation** interrompt
  le chargement. Les longues vidéos peuvent demander du temps et beaucoup de disque.
  Le cache est limité à 4 Go par vidéo ; au-delà, utilisez un extrait plus court.
- **Lire / Pause** ou **Espace** contrôle la lecture, sans son dans cette version.
  **Retour au début** remet la vidéo à la première image et en pause, en quittant
  le pointage ou la correction en cours. L'étalon, l'origine, le sens des axes et
  tous les points déjà acquis sont conservés.
  **Image précédente / Image suivante**, ou les flèches **gauche / droite**,
  déplacent d’une image exacte et mettent en pause. Le curseur permet un accès direct.
- Le numéro d’image commence à 1 et le temps à zéro pour la première image.
  Les horodatages de présentation sont conservés, y compris à cadence variable.
  Lorsque des horodatages manquent, les temps sont estimés avec la cadence déclarée
  et un avertissement apparaît. Si ni les temps ni la cadence ne sont disponibles,
  l’import est refusé. Le temps affiché est celui du fichier, pas nécessairement
  celui de la prise de vue réelle (par exemple pour un ralenti).
- Les images sont affichées dans leurs proportions décodées. La lecture affiche
  chaque image ; elle peut ralentir si le disque ou l’affichage ne suit pas.
- Un échec ou une annulation conserve la vidéo précédente. Le cache temporaire est
  supprimé au remplacement réussi et à la fermeture normale de l’application.

### Étalonnage et pointage

1. Sélectionnez une image où une longueur connue est visible. Cliquez sur
   **Définir l'étalon**, puis sur ses deux extrémités : une flèche suit la souris
   entre les clics en restant **horizontale par défaut**. Le choix **Direction de
   l'étalon** permet aussi de choisir **Vertical** ou **Libre (diagonale)**, y compris
   après le premier clic. La loupe suit l'extrémité de la flèche.
   Saisissez la longueur réelle et son unité (**m** par défaut, **mm** ou **cm**).
   La longueur doit couvrir au moins un pixel dans la direction choisie.
2. Cliquez sur **Définir l'origine**, puis sur le zéro du repère. Par défaut, **x** augmente
   vers la droite, **y** vers le haut. Le choix **Sens des axes** propose droite/haut,
   droite/bas, gauche/haut et gauche/bas. Les flèches suivent l'orientation choisie
   et les coordonnées des points déjà acquis sont recalculées ; les positions
   sur l'image et les temps sont conservés. Chaque nouvelle vidéo repart sur droite/haut.
   L'origine et l'étalon s'appliquent à toute
   la vidéo. Ils peuvent être définis sur des images différentes.
3. Choisissez la première image à mesurer puis **Commencer le pointage**.
   Une cible et une **loupe ×6** permettent de viser l'objet. Chaque clic crée
   une mesure et avance d'une image. Le pointage s'arrête après la dernière image.
   **Échap** ou **Arrêter le pointage** termine le mode ; la lecture normale
   l'arrête également. Les boutons de navigation restent utilisables pendant le pointage.
4. Les colonnes **x**, **y** et **t** sont créées à la définition de l'origine,
   puis remplies au fur et à mesure, dans l'ordre des images pointées. x et y
   utilisent l'unité de l'étalon, t est en secondes, avec zéro à la première image
   de la vidéo (même si le pointage commence plus tard). Dans **Graphique**, choisissez
   ces colonnes pour tracer y en fonction de x, x en fonction de t ou y en fonction de t.

- Tous les points restent visibles sous forme de petites marques discrètes.
  Le point de l'image affichée, ou le dernier point posé après l'avance automatique,
  est plus marqué.
- **Corriger un point** suspend le pointage. Cliquez sur une ancienne marque ou
  choisissez son numéro d'image dans la liste (utile si des points se superposent).
  L'image correspondante s'affiche : cliquez à la bonne position pour remplacer
  uniquement ce point, sans changer son temps ni les autres points.
  **Échap** annule la sélection avant modification. **Revenir au pointage** retrouve
  l'image et le mode précédents. Un seul point est conservé par image.
- **Annuler la dernière action** annule aussi une correction et revient à l'image
  concernée.
- Redéfinir l'étalon ou l'origine recalcule tous les points de la vidéo courante.
  Les positions sont conservées dans les coordonnées de l'image originale,
  indépendamment de la taille de la fenêtre. Les bandes noires ne sont pas pointables.
- Les colonnes du pointage sont actualisées automatiquement : les modifications
  manuelles dans ces colonnes peuvent être remplacées au prochain pointage ou recalcul.
  Les autres colonnes sont conservées. Le tableau initial x/y est réutilisé seulement
  s'il est entièrement vierge ; sinon des colonnes sont ajoutées, avec des noms distincts.
- Ouvrir une nouvelle vidéo conserve les mesures précédentes dans le tableau et
  commence un nouvel étalonnage et un nouveau pointage. Comme les autres données,
  ces mesures peuvent ensuite être enregistrées avec le projet.

## Dérivées et formules

L'onglet **Calculs** ajoute des colonnes liées aux mesures, disponibles immédiatement
dans **Données** et **Graphique**. Les calculs se mettent à jour après une correction,
un nouveau pointage ou un changement d'étalon. Le nom et l'unité restent modifiables
dans les en-têtes du tableau ; les valeurs calculées sont protégées contre la saisie.
Les références suivent les colonnes même après leur renommage.

### Calculer une vitesse ou une accélération

Dans **Dérivée centrée**, choisissez **x** comme grandeur et **t** comme abscisse,
nommez le résultat **Vx**, puis cliquez sur **Créer la dérivée**. Recommencez avec
**y** pour **Vy**, ou avec **Vx** par rapport à **t** pour **ax**.

La méthode utilisée est `D[i] = (f[i+1] - f[i-1]) / (u[i+1] - u[i-1])`.
À pas constant, le dénominateur vaut `2 × pas`. Aucune extrapolation n'est faite :
les extrémités restent vides. Une seconde dérivation laisse donc deux points vides
à chaque extrémité. Les lignes ne sont jamais décalées ni compactées ; un voisinage
incomplet n'est pas utilisé. Les abscisses des trois points doivent être strictement
monotones : les temps répétés ou les inversions locales ne produisent pas de dérivée.
En présence d'un pas variable, le bilan le signale : le résultat est la pente entre
les deux voisins, et n'est pas une interpolation pondérée au point central.

Une unité est proposée : `cm/s` pour une position en cm et un temps en s, puis
`cm/s²` pour sa dérivée temporelle. Si cette suggestion est conservée, l'unité suit
celle des sources. Une unité personnalisée reste telle que saisie, sans conversion
des valeurs. Les dérivées numériques peuvent amplifier le bruit des mesures ;
aucun lissage n'est appliqué.

### Calculer une grandeur par formule

Saisissez **v** comme nom, une unité cohérente avec Vx et Vy, puis la formule
`SQRT(Vx^2 + Vy^2)` et cliquez sur **Créer la grandeur**. `sqrt(Vx² + Vy²)`
fonctionne également. Les boutons permettent d'insérer la racine, le carré et les
opérateurs à la position du curseur.

- Opérateurs : `+`, `-`, `*`, `/`, `^`, `**`, `²`, `³` et parenthèses.
- Fonctions à un argument : `SQRT`, `ABS`, `SIN`, `COS`, `TAN`, `EXP`, `LN`
  (logarithme népérien), `LOG` et `LOG10` (base 10). Leur casse est indifférente ; les angles sont
  en radians. Constantes : `pi` et `e`.
- Les noms de grandeurs sont sensibles à la casse. Pour un nom contenant des
  espaces, un nom ambigu ou un symbole particulier, **Insérer la grandeur** fournit
  sa référence stable `C1`, `C2`, etc. Ces références désignent les numéros de colonnes.
- Les décimales acceptent virgule ou point. Les puissances sont limitées à des
  exposants de −100 à 100 et les expressions à 2 000 caractères.
- Une donnée absente, une division par zéro ou une racine négative laisse la cellule
  vide ; le bilan distingue les lignes incomplètes des erreurs de calcul.
  Une formule constante ne remplit que les lignes déjà occupées par des données saisies.
- Les unités des formules sont à renseigner ; aucune analyse dimensionnelle ni
  conversion automatique n'est effectuée. Utilisez par exemple deux composantes
  toutes deux en cm/s pour obtenir une norme en cm/s.
- Les définitions sont ajoutées dans l'ordre et ne peuvent utiliser que des colonnes
  existantes. Le récapitulatif montre les calculs et leur bilan. Les définitions et
  les données peuvent ensuite être enregistrées avec le projet.

## Installation et lancement

### Installer la version Windows

Les installateurs publics existants sont disponibles dans
[Physalix-releases](https://github.com/jeansittler/Physalix-releases/releases).
Ce dépôt de distribution historique reste utilisé par la version 1.1.3 pour les
mises à jour. Les téléchargements ne sont pas encore signés numériquement.

### Lancer depuis les sources

Prérequis : Python 3.10 ou supérieur avec le lanceur Windows `py` et pip.
Depuis PowerShell, dans le dossier du projet :

```powershell
# Ouvrir PowerShell dans le dossier du projet.
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

L’environnement virtuel isole les dépendances du projet. Son activation n’est pas
nécessaire avec ces commandes. Pour les lancements suivants, seule la dernière
commande est nécessaire. Fermer la fenêtre arrête l’application.

## Structure

```text
Physalix/
├── main.py                   # Point d’entrée à exécuter
├── physalix/
│   ├── __init__.py           # Paquet de l’application
│   ├── app.py               # QApplication et boucle d’événements
│   └── ui/
│       ├── __init__.py       # Paquet de l’interface
│       ├── main_window.py   # Fenêtre principale et navigation
│       ├── data_tab.py      # Tableau de mesures et saisie au clavier
│       ├── graph_tab.py     # Choix des axes et nuage de points
│       ├── graph_series.py  # Réglages et éléments graphiques de chaque série
│       ├── fill_table.py    # Poignée de recopie et progression numérique
│       ├── units.py         # Suggestions d’unités (saisie libre autorisée)
│       └── modeling_tab.py  # Modèles, sélection et résultats d’ajustement
├── tests/
│   ├── test_fill_table.py   # Séries numériques et gestes de recopie Qt
│   ├── test_graph.py        # Couples de mesures, choix des axes et cadrage
│   └── test_units.py        # Choix et saisie des unités, navigation
├── requirements.txt         # Dépendances PySide6 et PyQtGraph
├── .gitignore               # Fichiers locaux et générés à ignorer
└── README.md                # Présentation et commandes de développement
```

## Faire évoluer le projet

Les tests s’exécutent sans ouvrir de fenêtre :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Le démarrage, la fenêtre et les onglets sont séparés pour faciliter les évolutions.
Le tableau de données possède son propre module, avec un modèle Qt séparé de la
vue et de l’éditeur des cellules. Les calculs et traitements sont placés autant que
possible hors de l’interface afin de pouvoir être testés indépendamment de Qt.

Les signalements de bugs et propositions peuvent être ouverts dans les
[issues GitHub](https://github.com/jeansittler/Physalix/issues). Consultez
[CONTRIBUTING.md](CONTRIBUTING.md) avant une pull request et [SECURITY.md](SECURITY.md)
pour signaler une vulnérabilité sans publier de détails sensibles.

## Distribution Windows

**Aide → À propos de Physalix** affiche la version et propose **Rechercher les
mises à jour**. Une vérification automatique discrète peut proposer une version
plus récente ; téléchargement et installation restent à votre choix.
Voir [RELEASE.md](RELEASE.md) pour le fonctionnement, les essais locaux et les
commandes de préparation/publication des prochaines versions.

La chaîne produit un dossier autonome PyInstaller puis un installateur Inno Setup.
Python est nécessaire uniquement sur le PC développeur. Voir
[BUILD_WINDOWS.md](BUILD_WINDOWS.md) pour la préparation et la validation.

```powershell
.\scripts\build_release.ps1
```

Résultat attendu : `artifacts/Physalix-Setup-<version>.exe`.
Le dossier autonome reste dans `dist/Physalix`, avec son sous-dossier `_internal`.
`build-demo.ps1` construit uniquement ce dossier. `NOTICE-DEMO.txt` est une archive
historique exclue de la distribution actuelle.

Le package Python principal est `physalix`. Les nouveaux projets utilisent
l'extension `.physalix` et la signature interne `Physalix` (version 1).
Les anciens projets `.physalyx` restent lisibles. Leur enregistrement propose
un nouveau fichier `.physalix` et conserve le fichier original.

## Confidentialité et licence

Physalix n’intègre pas de télémétrie. Il contacte GitHub pour vérifier les mises à
jour ; les détails sont décrits dans [PRIVACY.md](PRIVACY.md).

Le code de Physalix est distribué sous **GNU GPL version 3 uniquement**
(`GPL-3.0-only`). Voir [LICENSE](LICENSE). Les composants tiers conservent leurs
propres licences ; voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Code signing policy

La [politique de signature du code](SIGNING_POLICY.md) décrit la préparation de
la signature numérique des futures versions. La [politique de confidentialité](PRIVACY.md)
précise le traitement des données et les connexions réseau de l’application.

Free code signing provided by SignPath.io, certificate by SignPath Foundation

## Modifier une formule existante

Dans **Calculs → Grandeurs calculées**, double-cliquez sur la ligne d’une
grandeur définie par une formule. Vous pouvez aussi utiliser le clic droit
**Modifier la formule…**, ou sélectionner la ligne puis cliquer sur le bouton
du même nom.

Modifiez l’expression puis cliquez sur **Enregistrer**. La même colonne conserve
son nom et son unité ; ses résultats et les calculs qui en dépendent sont
recalculés. **Annuler** conserve l’ancienne formule. Une expression invalide ou
une dépendance circulaire est refusée sans remplacer le calcul précédent.
Les références C1, C2… proposées par l’éditeur correspondent aux colonnes
actuelles, même après un renommage. Cette commande concerne les formules ;
les dérivées conservent leur fonctionnement actuel.
## Tangente simple et asymptote horizontale

Dans **Graphique → Outils du graphique**, choisissez **Tangente en un point…**
ou **Asymptote horizontale…**. Ces commandes sont aussi accessibles par clic droit.
Les deux constructions peuvent rester affichées ensemble. Le panneau propose
les mesures et les modélisations des séries visibles ; les réglages de série
se replient pour laisser de la place au graphique.

- **Tangente** : elle est initialement placée au premier point de la courbe.
  Cliquez sur **Choisir un point**, puis près de la courbe, ou saisissez son
  abscisse **x₀**. **Échap** annule le choix à la souris. Le point, la droite orange,
  les coordonnées et la pente sont affichés. Le domaine de la courbe est respecté.
- Pour un nuage de mesures, une interpolation PCHIP (tracé gris discret) permet
  d'estimer la tangente. Cette estimation est sensible au bruit ; une modélisation
  adaptée peut donner un résultat plus régulier. Sur une modélisation, la pente
  est estimée à partir de l'interpolation de son tracé numérique. Les abscisses
  doivent être distinctes, sans doublon.
- **Asymptote horizontale** : déplacez la droite violette ou saisissez **y∞**.
  Sa position initiale reprend la dernière ordonnée de la courbe, comme point de
  départ à ajuster ; cette valeur n'est pas automatiquement un palier asymptotique.
- **Palier du modèle** reprend une limite en +∞ lorsque la forme du modèle la
  garantit : c + A pour une charge avec τ > 0, c pour une décharge avec τ > 0,
  c pour une exponentielle décroissante, ou la valeur d'un modèle constant.
  Le palier suit ensuite les modifications du modèle. Un déplacement manuel
  de la droite ou une saisie de y∞ reprend le réglage manuel.
- Les deux cases permettent de montrer ou masquer chaque construction séparément.
  **Masquer** retire les deux guides ; le zoom et les mesures ne sont pas modifiés.
  L'ouverture d'un outil de titrage masque ces guides pour éviter les superpositions.

## Dosage conductimétrique : intersection de deux droites

Dans **Graphique → Outils du graphique → Titrage conductimétrique…** (également
par clic droit), choisissez la série avec le volume en X et la conductivité en Y.
Les réglages de série se replient pour conserver de la place au graphique.

- Deux zones initiales sont proposées aux extrémités des données. Déplacez les
  zones ou leurs bornes pour isoler les portions rectilignes **avant l'équivalence
  (orange)** et **après l'équivalence (violet)**. Les points proches du changement
  de pente peuvent être laissés entre les zones, hors des ajustements.
- **Intervalles…** permet de saisir les bornes numériques dans l'unité de X.
  Les bornes sont incluses ; les deux zones doivent être distinctes, ordonnées,
  et contenir chacune au moins deux points de volumes distincts.
- Les deux ajustements affines par moindres carrés sont tracés en traits pleins.
  Leurs prolongements en pointillés rejoignent l'intersection. Un point vert et
  une projection verticale repèrent **Véq**, également affiché dans le panneau
  avec l'unité du volume. Les équations utilisent les unités des axes.
- Les équations, les effectifs et les R² se mettent à jour pendant le réglage.
  Avec deux points seulement, la qualité d'un ajustement ne peut pas être évaluée
  par son R² ; il est préférable d'utiliser davantage de mesures par zone.
- **Cadrer le résultat** inclut les mesures et l'intersection dans la vue. Déplacer
  une borne conserve le zoom ; **Réinitialiser les zones** rétablit les zones initiales.
- Une intersection extérieure à l'espace entre les deux zones est signalée :
  vérifiez la sélection des portions rectilignes. Des droites parallèles ou presque
  parallèles ne donnent pas de volume équivalent exploitable et le résultat est masqué.
- Les données du tableur ne sont pas modifiées. Les changements de données
  recalculent le résultat en conservant les intervalles de la série sélectionnée.
  **Masquer** retire cette construction ; l'outil des tangentes pH-métriques et
  cet outil s'utilisent séparément pour éviter de superposer les constructions.

# Dosage pH-métrique : méthode des tangentes

Dans **Graphique → Outils du graphique → Méthode des tangentes…**, choisissez
la série avec le volume en X et le pH en Y. Une construction est proposée
automatiquement. Déplacez les deux bornes pour isoler le saut à étudier et
ajustez le curseur **Inclinaison** : les deux tangentes orange restent parallèles.
La parallèle médiane verte coupe la courbe au volume équivalent, affiché avec
l’unité de la colonne X et projeté sur l’axe des volumes. Le segment gris montre
la perpendiculaire et son milieu. **Masquer** retire la construction.

Le calcul utilise une interpolation PCHIP des mesures, sans extrapolation,
et recherche deux contacts de même pente autour de la pente maximale de la zone.
Le curseur exprime cette pente commune en pourcentage de la pente maximale.
Il faut au moins sept couples valides et des volumes distincts dans la zone.
Les courbes croissantes et décroissantes sont acceptées. Une modification des
mesures recalcule la construction ; un résultat devenu impossible est effacé.
La valeur est une estimation graphique, sensible au choix des tangentes,
à l’échantillonnage et à l’asymétrie du saut. Vérifiez les contacts sur les mesures.
Principe pédagogique : [Éduscol, ressources mathématiques–physique-chimie, p. 8](https://cache.media.eduscol.education.fr/file/Mathematiques/85/9/Ressources_Premiere_STL_Maths-PC_222859.pdf).

## Fonctions usuelles et notation scientifique

Dans **Calculs** et à côté de la barre de formule de **Données / Tableur**,
le bouton **Fonctions usuelles…** ouvre une aide avec exemples.
Écrivez `8E5` pour 8 × 10⁵, `2,5E-3` pour 0,0025, `ln(x)` pour le logarithme
népérien, `log(x)` pour le logarithme en base 10 et `exp(x)` pour eˣ.
Dans une cellule, une formule commence par `=` : `=8E5*A1` ou `=ln(A1)`.
Dans Calculs : `8E5*C1` ou `ln(C1)`. Les fonctions acceptent aussi les majuscules.
La convention de `LOG` a changé : pour un logarithme népérien, utilisez désormais `LN`.
