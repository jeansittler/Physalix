# Préparer et publier une version de Physalix

## Base conservée

Audit avant modification : branche `feature/auto-update`, origin
`https://github.com/jeansittler/Physalix.git`, tag `v1.0.0` existant.
Entrée : `main.py` → `physalix.app.main` → `MainWindow`, interface PySide6.
PyInstaller utilise `Physalix.spec` en **onedir**, sans UPX, avec les ressources
Qt, les bibliothèques scientifiques et la correction ICU existantes.

La source de vérité reste **`physalix/_version.py`**. Elle alimente Qt, À propos,
le protocole de mise à jour, les métadonnées PE et, via le build, Inno Setup.
La version du format des projets est indépendante et reste inchangée.

`packaging/installer/Physalix.iss` est conservé intégralement depuis `v1.0.0` :

- AppId : `{807A4F23-674E-4CD3-9B57-D66B7B819B72}` ; ne jamais le remplacer.
- `DefaultDirName={autopf}\Physalix`, `PrivilegesRequired=admin`.
- `ArchitecturesAllowed=x64compatible` et `ArchitecturesInstallIn64BitMode=x64compatible`.
- `UsePreviousAppDir=yes` et `UsePreviousTasks=yes`.
- `AppVersion`, `AppVerName`, `VersionInfoVersion` et le nom du fichier dépendent
  du paramètre `AppVersion` transmis par le build.
- Aucune suppression globale des fichiers. Une seule installation machine et
  son entrée de désinstallation sont réutilisées, y compris sur un autre disque.

Les projets/CSV restent aux emplacements choisis, les écritures projet sont
atomiques et les caches vidéo sont temporaires. Aucune préférence persistante
existante à migrer. Conserver les travaux dans Documents, hors Program Files.
Les fichiers de l'updater sont dans `%LOCALAPPDATA%\Physalix\updates` :
`state.json` (dernière tentative en secondes UTC), `check.lock`, et `updater.log`
(256 Kio, deux archives). Ils ne sont pas installés ou effacés par Inno Setup.

## Fonctionnement

La fenêtre s'ouvre avant le démarrage d'un timer de 2,5 secondes. Ensuite un
thread Python effectue le réseau et les écritures locales ; seuls les signaux Qt
mettent à jour l'interface. Les fenêtres de préparation d'un projet et les tests
ne démarrent pas la recherche automatique.

URL de production, centralisée dans `physalix/updates.py` :

`https://github.com/jeansittler/Physalix/releases/latest/download/update.json`

Aucun appel à l'API REST GitHub, aucun token. HTTPS est requis, y compris sur
les redirections. Les redirections GitHub vers son stockage d'assets sont permises.
La comparaison utilise trois entiers, jamais l'ordre alphabétique.

Une tentative automatique au maximum toutes les 24 heures par profil Windows,
même après échec. Un verrou de fichier Windows protège les lancements simultanés.
Si l'état ne peut pas être écrit, la recherche automatique est omise ; la recherche
manuelle reste possible. Une horloge revenue en arrière ou un état corrompu sont
récupérés. Le bouton manuel contourne toujours le délai ; il est désactivé pendant
une opération déjà en cours.

Timeout réseau de 10 secondes par opération bloquante, avec une limite de durée
contrôlée entre les blocs de 30 secondes pour le manifeste et 30 minutes pour
l'installateur. Limites de taille : manifeste 1 Mio, notes 20 000 caractères,
installateur 2 Gio. Les erreurs automatiques restent silencieuses. Les erreurs
manuelles utilisent un message simple. Les journaux indiquent les versions,
étapes et types d'erreur, sans URL signée, notes, chemins de projets ou secrets.

Les notes sont du texte brut. `mandatory` est validé et stocké mais n'impose
aucune installation. « Plus tard » ferme simplement la proposition.

Le téléchargement annulable va dans un dossier aléatoire
`%TEMP%\Physalix-update-<version>-…\Physalix-Setup-<version>.exe`.
L'empreinte SHA-256 est calculée par blocs après le téléchargement et comparée avant
tout lancement. Un fichier incomplet, annulé ou de mauvaise empreinte est supprimé.
Après une fermeture forcée du processus, un reliquat temporaire peut subsister ;
il n'est jamais repris ou exécuté automatiquement.

Après validation, Physalix demande de sauvegarder les modifications éventuelles.
Annuler cette sauvegarde annule aussi l'installation. Le chargeur Inno est lancé
avec `subprocess.Popen`, sans shell, avec `/SP- /NORESTART`. Aucun `/DIR`, `/SILENT`
ou `/VERYSILENT` : le chemin précédent et l'assistant existant restent utilisés.
La recherche des DLL PyInstaller est réinitialisée pour ce processus externe.
Physalix ferme ensuite sa fenêtre et ses traitements vidéo proprement.

Le chargeur Inno demande lui-même l'UAC : cela permet à la case « Lancer Physalix »
de l'écran final de relancer l'application avec l'utilisateur d'origine. En cas
de refus UAC ou d'annulation ultérieure de l'assistant, Physalix peut déjà être
fermé : le relancer normalement ; le projet a été sauvegardé ou son abandon
explicitement confirmé. Le fichier temporaire lancé est laissé à Windows, pour
ne pas le supprimer pendant que l'installateur l'utilise. Aucun helper ajouté.

Références : [chargeur et UAC Inno](https://jrsoftware.org/is6help/topic_securitymeasures.htm),
[paramètres Inno](https://jrsoftware.org/ishelp/topic_setupcmdline.htm),
[relance avec l'utilisateur d'origine](https://jrsoftware.org/ishelp/topic_runsection.htm),
[processus externes PyInstaller](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).

## Commandes de release

Prérequis et environnement verrouillé : [BUILD_WINDOWS.md](BUILD_WINDOWS.md).
Depuis la racine, modifier uniquement la version dans `physalix/_version.py`
et mettre à jour les notes courtes dans `packaging/update-notes.txt`.
Exemple pour la prochaine version :

```powershell
Set-Location C:\Physalix
Set-Content -LiteralPath physalix\_version.py -Value '__version__ = "1.1.1"' -Encoding ascii
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

Le build exécute à nouveau les tests, construit l'EXE, valide le bundle et son
lancement réel, compile Inno Setup, signe si les paramètres existants sont fournis,
calcule le SHA-256 et génère **automatiquement** `artifacts/update.json`.
La génération vérifie aussi la version PE de l'installateur pour refuser un ancien
EXE simplement renommé. Elle utilise `pefile`, déjà dans l'environnement de build.
Aucune nouvelle dépendance d'application ou de build.

Résultat pour la version de l'exemple :

- `artifacts/Physalix-Setup-1.1.1.exe` ;
- `artifacts/Physalix-Setup-1.1.1.exe.sha256` ;
- `artifacts/update.json` avec l'URL exacte
  `https://github.com/jeansittler/Physalix/releases/download/v1.1.1/Physalix-Setup-1.1.1.exe`.

Pour régénérer uniquement le manifeste après modification des notes ou signature
externe **définitive** de l'installateur :

```powershell
.\.venv\Scripts\python.exe .\scripts\prepare_release.py
# Autres notes UTF-8 ou dossier d'artefacts, si nécessaire :
.\.venv\Scripts\python.exe .\scripts\prepare_release.py --notes-file .\packaging\update-notes.txt --artifacts .\artifacts
```

Ne jamais modifier/signer l'EXE après ce calcul sans régénérer son manifeste.
Ne publier que les artefacts d'un build entièrement réussi. `artifacts` est ignoré
par Git : les fichiers de distribution sont des pièces jointes de la Release.

Après revue des changements et validation sur un autre PC :

```powershell
git diff --check
git diff
git status --short
# Sélectionner explicitement les fichiers modifiés du logiciel et de ses tests :
git add physalix scripts tests packaging README.md BUILD_WINDOWS.md RELEASE.md
git commit -m "Prepare Physalix 1.1.1"
git tag -a v1.1.1 -m "Physalix 1.1.1"
# Seulement lorsque vous décidez de publier :
git push origin HEAD
git push origin v1.1.1
```

Dans GitHub → Releases → Draft a new release : sélectionner `v1.1.1`, ajouter
les notes, joindre **l'installateur et `update.json`** (ainsi que `.sha256` si souhaité),
puis publier comme version stable/latest, sans cocher pre-release. L'URL `latest`
doit alors servir ce manifeste. Aucun script ne committe, ne tague ou ne publie.
Ne jamais déplacer `v1.0.0` ni remplacer les assets de sa Release finalisée.
Pour la préparation actuelle, employer le numéro présent dans `_version.py` dans
le message de commit, le tag et la Release plutôt que celui de cet exemple futur.

**Les installations 1.0.0 n'ont pas d'updater** : leur première migration vers
la version actuelle nécessite le téléchargement et le lancement manuels de
l'installateur. L'updater pourra ensuite prendre en charge les versions suivantes.

## Essai local sans Release publique

Les tests automatisés utilisent des réponses simulées et n'exigent pas Internet :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_update*.py" -v
```

Pour parcourir réellement la proposition, le téléchargement et l'installation,
après un build réussi, préparer un dossier local contenant les vrais artefacts :

```powershell
New-Item -ItemType Directory -Force .\artifacts\update-test | Out-Null
$testVersion = (& .\.venv\Scripts\python.exe -c 'from physalix import __version__; print(__version__)').Trim()
Copy-Item -LiteralPath ".\artifacts\Physalix-Setup-$testVersion.exe" -Destination .\artifacts\update-test
$testManifest = Get-Content .\artifacts\update.json -Raw | ConvertFrom-Json
$testManifest.installer_url = "http://127.0.0.1:8765/Physalix-Setup-$testVersion.exe"
$testJson = $testManifest | ConvertTo-Json
[IO.File]::WriteAllText('C:\Physalix\artifacts\update-test\update.json', $testJson, [Text.UTF8Encoding]::new($false))
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory .\artifacts\update-test
```

Dans un second terminal, simuler une ancienne version **en mémoire uniquement** :

```powershell
Set-Location C:\Physalix
$env:PHYSALIX_UPDATE_MANIFEST_URL = 'http://127.0.0.1:8765/update.json'
.\.venv\Scripts\python.exe -c 'import physalix; physalix.__version__ = "1.0.0"; from physalix.app import main; raise SystemExit(main())'
Remove-Item Env:PHYSALIX_UPDATE_MANIFEST_URL
```

Le fichier version du projet et les tags ne changent pas. Le vrai installateur
actuel sera lancé si vous cliquez « Mettre à jour » et acceptez la sauvegarde.
Faire cet essai de préférence sur une machine de test. Fermer le serveur par Ctrl+C.
La substitution d'URL est ignorée par les EXE empaquetés, même si la variable
d'environnement existe ; HTTP n'est permis qu'en développement explicite et sur
loopback. Les vérifications de développement utilisent un état séparé dans
`updates/development`. Aucun réglage n'est exposé aux élèves.

Pour tester le rejet de fichier, modifier un caractère de `sha256` dans ce manifeste
local, puis utiliser le bouton manuel. Pour le réseau indisponible, arrêter le
serveur. Les timeouts et les JSON incomplets sont également couverts par les tests.

## Validation sur un deuxième PC

Sur Windows x64 sans Python, conserver l'installation 1.0.0 avec son chemin choisi,
un projet enregistré et un fichier témoin personnel. Installer la version actuelle
par-dessus : vérifier même dossier, une seule entrée Windows, raccourcis fonctionnels,
projet et fichier témoin conservés. Tester également un compte standard avec saisie
d'un autre compte administrateur à l'UAC et un chemin d'installation personnalisé.

Vérifier la case de relance, l'absence d'élévation du Physalix relancé, le refus UAC,
l'annulation de l'assistant, la sauvegarde/annulation d'un projet modifié et un fichier
vidéo ouvert. Pour l'updater empaqueté, le test réel de version supérieure se fera
avec la prochaine Release stable officielle. Tester aussi hors ligne et derrière
le proxy de l'établissement. Vérifier les téléchargements interrompus et SmartScreen.
La compilation et les mocks ne remplacent pas ces essais d'installation.

## Validation de la préparation actuelle — 10 septembre 2026

- **151 tests réussis**, dont 27 nouveaux tests updater/release/Qt ; réponses
  réseau simulées, versions, JSON, champs, délais, empreintes, annulation,
  réactivité, sauvegarde et lancement simulé. Log : `artifacts/release-tests.log`.
- Build complet réussi : PyInstaller, contrôle de 683 fichiers (environ 295,2 Mio),
  imports updater/SSL présents, diagnostics scientifiques/Qt et lancement normal
  de l'EXE avec PATH limité à Windows, fermeture propre.
- Inno Setup 6.7.3 compilé : `Physalix-Setup-1.1.0.exe`, **84 100 365 octets**,
  métadonnées PE 1.1.0.0. `update.json` généré et empreinte revérifiée :
  `f8e361e34cce1cdf75f488c80d4af62dac4c6d4ad61bfebc7d7a818d049d36e9`.
- Test complémentaire sur un vrai serveur HTTP loopback : redirection, manifeste,
  téléchargement de 900 000 octets, bon hash accepté et mauvais hash rejeté.
  Aucun installateur exécuté lors de cet essai. Rapport : `artifacts/local-update-check.json`.
- Rendu des dialogues vérifié avec le plugin Qt Windows : `artifacts/about-dialog.png`
  et `artifacts/update-dialog.png`. Le mode hors écran seul ne rendait pas les polices
  Windows correctement, d'où cette vérification sur le vrai plugin.
- Le script Inno est identique à celui de `v1.0.0` (AppId, mode administrateur/x64,
  conservation du chemin). Ancien tag inchangé :
  `ed28c8994bf7ea99645b3496f2b72a7b35072ddc`. L'installateur 1.0.0 a conservé son hash
  `f1ed18fb0bc42bdbdeda6a25612364c783c84d39c84eb7f39f03fa134af12d6d`.
- `git diff` et `git status` revus, `git diff --check` sans erreur ; aucun secret
  détecté dans les ajouts. Les avertissements Git concernent la normalisation
  LF/CRLF existante. Aucun commit, tag, push ou publication effectué.
- Installateur **non signé** (aucun certificat fourni). Avertissement Inno
  préexistant sur `{userdocs}` en mode administrateur : il concerne ici les dossiers
  de travail des raccourcis/relance, pas une copie de données utilisateur ; tester
  avec un compte standard et d'autres identifiants UAC avant diffusion.
- L'installation réelle par-dessus 1.0.0 et l'UAC n'ont pas été exécutés dans cette
  préparation. Leur validation sur un autre PC reste à faire selon la liste ci-dessus.
