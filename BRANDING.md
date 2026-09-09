# Identité visuelle Physalix

Les deux PNG originaux sont conservés dans `physalix/ui/resources/branding/` :
`logo_physalix.png` et `icon_physalix.png`. Aucune ressource n'est chargée depuis
le dossier Téléchargements. `icon_physalix.ico` contient les tailles 16, 24, 32,
48, 64, 128 et 256 pixels en RGBA, générées depuis le mini-logo avec un
redimensionnement Qt lissé, sans déformation, et encodées en PNG dans l'ICO.

Le logo complet occupe la zone de marque existante (180 × 60 unités Qt).
Le rendu conserve les proportions et la transparence et utilise le PNG
original avec le lissage de QPainter pour les écrans HiDPI. La devise
« Observer • Mesurer • Comprendre » reste en infobulle.

L'icône est définie sur QApplication et la fenêtre principale. Avant de créer
QApplication, Windows reçoit l'AppUserModelID `Physalix.Physalix`, utilisé pour
l'identité de la barre des tâches. Le titre reste Physalix lors de l'ouverture
et de l'enregistrement des projets. Le format courant est `.physalix` ;
les anciens projets restent lisibles et sont enregistrés au nouveau format.

`physalix/ui/resources.py` centralise les chemins à partir de `__file__`,
également positionné par PyInstaller dans le bundle. Le thème utilise ce même
résolveur. La configuration existante `Physalix.spec` embarque déjà tout le
dossier de ressources, y compris le nouveau sous-dossier de marque, et définit
maintenant l'ICO de l'exécutable.

Reconstruction : `./build-demo.ps1`. Résultat : `dist/Physalix/Physalix.exe`.
Distribuer le dossier `dist/Physalix` complet avec son sous-dossier `_internal`.
La reconstruction complète utilise uniquement `build/Physalix` et `dist/Physalix`.
Les exécutables précédemment distribués doivent être remplacés pour obtenir
la nouvelle identité. Aucun installateur n'est présent dans le dépôt ; l'ICO
est prêt pour un futur installateur et ses raccourcis.

Validation : `.venv/Scripts/python.exe -m unittest discover -s tests -v`.

## Vérifications du 9 septembre 2026 — normalisation du nom

- Suite standard : 124 tests réussis (119 existants et 5 tests de migration).
- Sources sous Windows : démarrage par le point d'entrée, nom d'application,
  AppUserModelID, logo et icônes validés ; enregistrement puis réouverture
  d'un projet au nouveau format et capture du rendu contrôlés.
- Les anciens projets sont lus sans changer leur signature sur disque.
  L'enregistrement propose une destination au nouveau format ; l'annulation
  conserve l'original et une destination existante reste protégée.
- Reconstruction complète avec `--clean` réussie. Le bundle contient le
  package `physalix` et les trois ressources de marque, identiques octet
  pour octet aux originaux. Les sept images de l'ICO sont présentes dans
  les ressources PE de l'exécutable.
- Métadonnées Windows : produit, description et nom interne `Physalix`,
  fichier original `Physalix.exe`. La version technique est `0.0.0.0`
  en attendant la définition d'une numérotation de publication.
- EXE lancé depuis un autre dossier : fenêtre `Physalix` détectée, réactive,
  icône native présente, sortie d'erreur vide.
- Le contrôle supplémentaire de toute la suite avec le moteur Qt Windows
  présente deux échecs d'interaction déjà reproduits sur le commit d'origine
  (survol du graphique et liste des unités). Le parcours Windows dédié,
  avec activation et délais de présentation, valide ces deux gestes ainsi
  que le chargement, la calibration, le pointage et la lecture vidéo.
- Limite : l'outil de bureau n'expose pas la fenêtre de l'EXE. Son apparence
  dans la barre des tâches et Alt+Tab, ainsi que le parcours manuel des
  dialogues dans l'EXE, restent à confirmer par l'utilisateur. Le rendu
  source et les ressources embarquées ont été vérifiés.

Les avertissements PyInstaller restent ceux déjà observés : `OpenGL`
concerne le module 3D facultatif de PyQtGraph ; `scipy.special._cdflib`
est un import caché absent de la version installée. Les tests 2D, de calcul
et de modélisation passent ; ces avertissements n'ont pas été masqués.

Les journaux, captures et l'inventaire détaillé sont dans `artifacts/physalix-*`
(ignorés par Git). Le script de build demande de fermer l'application avant
une reconstruction si l'exécutable est verrouillé, sans effacer le bundle.
Aucun commit ni push automatique n'a été effectué.
