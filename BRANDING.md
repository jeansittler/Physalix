# Identité visuelle Physalix

Les deux PNG originaux sont conservés dans `physlab/ui/resources/branding/` :
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
et de l'enregistrement des projets ; le format `.physalyx` reste compatible.

`physlab/ui/resources.py` centralise les chemins à partir de `__file__`,
également positionné par PyInstaller dans le bundle. Le thème utilise ce même
résolveur. La configuration existante `Physalyx.spec` embarque déjà tout le
dossier de ressources, y compris le nouveau sous-dossier de marque, et définit
maintenant l'ICO de l'exécutable.

Reconstruction : `./build-demo.ps1`. Résultat : `dist/Physalix/Physalix.exe`.
Distribuer le dossier `dist/Physalix` complet avec son sous-dossier `_internal`.
L'ancien dossier `dist/Physalyx`, s'il existe, n'est pas mis à jour.
Les exécutables précédemment distribués doivent être remplacés pour obtenir
la nouvelle identité. Aucun installateur n'est présent dans le dépôt ; l'ICO
est prêt pour un futur installateur et ses raccourcis.

Validation : `.venv/Scripts/python.exe -m unittest discover -s tests -v`.

## Vérifications du 9 septembre 2026

- Les 117 tests existants et les deux tests de branding passent.
- Lancement depuis les sources sur la plateforme Qt Windows : réussi.
  Captures examinées à 100 % et 200 % : logo transparent, proportions
  conservées, navigation intacte. Icônes Qt non vides ; AppUserModelID relu
  via l'API Windows et confirmé à `Physalix.Physalix`.
- Build existant réussi, sans reconstruction supplémentaire : les trois
  ressources embarquées sont identiques aux fichiers du projet. Les sept
  images de l'icône ont aussi été extraites des ressources PE de l'EXE et
  validées (dimensions et transparence).
- EXE lancé depuis `artifacts`, indépendamment du dossier courant : fenêtre
  « Physalix » détectée et réactive, journal d'erreurs vide.
- Limite du contrôle visuel : l'outil de bureau ne rend pas les fenêtres de
  test accessibles. Le rendu du logo dans l'EXE, l'icône native de la barre de
  titre, celle de la barre des tâches et Alt+Tab restent à confirmer
  visuellement par l'utilisateur. Les ressources et la configuration
  correspondantes sont vérifiées ; leur apparence dans le shell ne l'est pas.

Les avertissements PyInstaller étaient déjà consignés dans `VISUAL-REFRESH.md` :
`OpenGL` concerne `pyqtgraph.opengl`, non utilisé par les graphiques 2D du
logiciel ; `scipy.special._cdflib` provient d'un import caché du hook
PyInstaller, alors que cette extension séparée est absente de SciPy 1.18.1
installé. L'import de SciPy et les tests de modélisation passent. Ces warnings
sont considérés sans conséquence observée pour les fonctions actuelles de
Physalix et n'ont pas été masqués ni corrigés dans cette tâche.

Les journaux et captures sont dans `artifacts/branding-*` (ignorés par Git).
Aucun commit automatique n'a été effectué.
