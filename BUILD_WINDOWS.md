# Construire Physalix sous Windows

Pour les versions avec mise à jour intégrée, suivre **[RELEASE.md](RELEASE.md)** :
le build existant génère désormais aussi `artifacts/update.json`, après la signature
éventuelle de l'installateur. Les comptes rendus 1.0.0 ci-dessous restent historiques.
La version de l'application, du bundle et de l'installateur vient de `_version.py`.

## Première préparation

PC développeur : Windows x64, CPython **3.12 x64**, PowerShell et
[Inno Setup 6](https://jrsoftware.org/isdl.php) (6.7.3 conseillé).
Sur ce poste, Python 3.12.14 et les dépendances verrouillées sont utilisés.
L'utilisateur final n'a besoin ni de Python, ni de pip, ni de Codex.

Depuis la racine du dépôt, pour un nouvel environnement uniquement :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r packaging\requirements-build.txt
```

Ne recréez pas l'environnement existant s'il fonctionne. Le build vérifie les
versions exactes et `pip check` ; il n'installe rien implicitement. Pour mettre à
jour les bibliothèques, modifier le verrou puis revalider les tests et le bundle.
`requirements.txt` exprime les contraintes de développement ;
`packaging/requirements-build.txt` fixe les versions de distribution.
Conserver les roues et l'installateur Python avec les archives internes d'une
release pour une reconstruction à long terme. La procédure reproductible ne
garantit pas l'identité binaire (horodatages, outils Windows et signature).

## Générer une version

Fermer Physalix, puis depuis `C:\Physalix` :

```powershell
.\scripts\build_release.ps1
```

Si Windows PowerShell refuse les scripts sur ce poste, lancer uniquement ce script
local avec une autorisation limitée au processus, sans modifier la politique permanente :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

Si Windows PowerShell refuse les scripts sur ce poste, lancer uniquement ce script
local avec une autorisation limitée au processus, sans modifier la politique permanente :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

Le script nettoie seulement `build/Physalix` et `dist/Physalix`, vérifie Python et
les dépendances, exécute les tests, construit sans UPX, contrôle métadonnées,
ressources et runtimes, puis lance le véritable EXE avec un PATH limité à Windows
depuis un dossier temporaire externe. Il compile ensuite l'installateur et calcule
son SHA-256. Toute étape critique arrête le build. Les archives et données sous
`artifacts` sont conservées.

Sans Inno Setup, le bundle est testé puis le script s'arrête avec une erreur
explicite. Installer **Inno Setup 6** depuis le lien ci-dessus, puis relancer la
même commande. Pour un emplacement personnalisé :

```powershell
.\scripts\build_release.ps1 -Iscc 'D:\Outils\Inno Setup 6\ISCC.exe'
```

`-PackageOnly` produit et teste seulement le dossier autonome.
`-Python 'chemin\python.exe'` sélectionne un autre environnement.

## Résultat

- À distribuer : `artifacts/Physalix-Setup-1.0.0.exe` et son `.sha256` facultatif.
- Application autonome : `dist/Physalix/Physalix.exe` avec **tout** `dist/Physalix`.
- Preuves : `artifacts/release-tests.log`, `release-build.log`, `release-installer.log`,
  `distribution-check.json`, `normal-launch-check.json`, `bundle-manifest.json` (tailles et empreintes).

L'installateur 1.0.0 a été produit avec Inno Setup 6.7.3 et testé localement.
Ne pas distribuer un ancien installateur après un build en erreur : vérifier
la version, la date et la réussite finale de la commande.

## Installation et données

Installation pour tous les utilisateurs dans `{autopf}\Physalix`, soit
`C:\Program Files\Physalix` sur Windows x64, avec élévation administrateur.
La page de choix du dossier est affichée, avec le bouton Parcourir permettant
de choisir un autre disque ou dossier. Menu Démarrer commun automatique et Bureau
commun optionnel (`autoprograms`/`autodesktop`). L'identifiant Inno est fixe :
**ne jamais changer AppId**. Le répertoire précédent est réutilisé et Windows
conserve une entrée de désinstallation. `UsePreviousAppDir=yes` conserve le chemin
choisi lors des réinstallations de cette installation machine. Une ancienne
installation par utilisateur doit être désinstallée séparément avant de passer
à cette installation machine pour éviter deux entrées (les projets restent conservés).
Les fichiers applicatifs sont remplacés
même si leur version de DLL diminue. Aucune suppression globale du répertoire
n'est utilisée : les fichiers personnels restent conservés. Des fichiers devenus
obsolètes peuvent rester jusqu'à la désinstallation ; toute future migration
devra cibler seulement les anciens fichiers connus.

Projets et CSV vont aux emplacements choisis, avec écriture atomique. Les caches
vidéo utilisent les dossiers temporaires Windows. Pas de préférences persistantes
à déplacer. Conserver les projets dans Documents, hors installation.
Les politiques de l'établissement peuvent imposer une intervention informatique.

Cible : Windows 10 1809+ / Windows 11 x64, validation sur ce poste seulement.
PyInstaller embarque Python, Qt et ses plugins, NumPy/SciPy et leurs DLL,
PyAV/FFmpeg et les runtimes Visual C++. Aucun téléchargement Python au lancement.
Le correctif ICU existant est conservé : la DLL Windows remplace l'ICU incompatible
du Python développeur. Aucun besoin séparé de redistribuable Visual C++ n'a été
établi ; le test sur PC propre reste nécessaire.

## Tester avant diffusion

Le contrôle automatique teste NumPy/LAPACK, les ajustements SciPy linéaire et
non linéaire, le graphe, sauvegarde/relecture, encodage/décodage vidéo et la
fenêtre Qt avec le plugin Windows. Diagnostic explicite :

```powershell
$p = Start-Process -FilePath 'C:\Physalix\dist\Physalix\Physalix.exe' -ArgumentList '--distribution-check', 'C:\Physalix\artifacts\manual-check.json' -WorkingDirectory $env:TEMP -WindowStyle Hidden -PassThru -Wait
$p.ExitCode
Get-Content C:\Physalix\artifacts\manual-check.json
```

Sur une VM ou un autre PC sans outils développeur : installer avec un compte
standard, lancer depuis les deux raccourcis, saisir des données, tracer/ajuster,
ouvrir une vidéo, enregistrer/réouvrir un projet dans Documents. Réinstaller
par-dessus la même version puis une version suivante : vérifier une seule entrée
Windows et les projets conservés. Désinstaller : raccourcis et application doivent
disparaître, projets conservés. Ce test ne peut pas être remplacé par PyInstaller
ou un PATH nettoyé sur le poste développeur.

## Version suivante et publication

Source unique : `physalix/_version.py`. Elle alimente Qt, les métadonnées PE et
l'installateur. La constante VERSION du format projet est indépendante.

Pour produire 1.0.1 après modification du logiciel :

```powershell
Set-Location C:\Physalix
Set-Content -LiteralPath physalix\_version.py -Value '__version__ = "1.0.1"' -Encoding ascii
.\scripts\build_release.ps1
```

Après validation, pour enregistrer la première distribution :

```powershell
git diff --check
git status --short
git add .gitignore requirements.txt Physalix.spec main.py physalix/__init__.py physalix/_version.py physalix/app.py physalix/_distribution_check.py scripts packaging build-demo.ps1 README.md BRANDING.md BUILD_WINDOWS.md
git commit -m "Prepare Physalix Windows distribution"
git tag -a v1.0.0 -m "Physalix 1.0.0"
```

Pour 1.0.1, ajouter aussi les fichiers applicatifs modifiés, committer puis créer
`v1.0.1`. Ne jamais déplacer un tag publié. Reconstruire depuis le commit tagué,
refaire la validation, puis lorsque la publication est souhaitée pousser la branche
et le tag vers `jeansittler/Physalix`. Dans GitHub → Releases → Draft a new release,
sélectionner le tag, ajouter les notes, l'installateur et son SHA-256, puis publier.
Le build ne réalise aucun commit, tag, push ou publication.
GitHub Actions n'est pas ajouté pour cette première chaîne locale.

## Signature numérique

Sans signature et réputation suffisante, SmartScreen peut afficher une alerte.
La signature ne garantit pas non plus l'absence de faux positifs. Le build utilise
onedir sans UPX, des versions explicites et la compression standard Inno.
Aucun éditeur légal fourni : aucun nom de société n'est inventé.

Installer le Windows SDK pour `signtool.exe` et disposer d'un certificat de
signature de code dans le magasin personnel Windows, clé privée protégée.
Ne jamais versionner de secret ni de certificat PFX/P12.

```powershell
.\scripts\build_release.ps1 -CertificateThumbprint 'EMPREINTE_DU_CERTIFICAT' -TimestampUrl 'URL_HORODATAGE_DU_FOURNISSEUR' -SignTool 'CHEMIN\signtool.exe'
```

Le script signe **Physalix.exe avant Inno**, puis l'installateur et vérifie chaque
signature (`/pa`), avec SHA-256 et horodatage RFC 3161. Le désinstalleur interne
n'est pas signé dans cette première intégration ; `SignTool`/`SignedUninstaller`
d'Inno permettront de l'ajouter ultérieurement.

Références : [PyInstaller](https://pyinstaller.org/en/stable/usage.html),
[installation sans élévation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[identifiant de mise à jour](https://jrsoftware.org/ishelp/topic_setup_appid.htm).

Signature : [SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)
et [réputation SmartScreen](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

## Audit initial du 9 septembre 2026, avant installation d'Inno Setup

- Dépôt Git initial propre ; origin utilise exactement `jeansittler/Physalix`.
  Entrée réelle : `main.py` → `physalix.app.main` → `MainWindow`.
- Base existante conservée : PyInstaller onedir/PySide6, ressources relatives à
  `__file__`, icône officielle à sept résolutions et correction ICU Windows.
  Les hooks PyInstaller gèrent NumPy/SciPy/Qt ; les extensions PyAV sont collectées
  explicitement. Les imports optionnels OpenGL/Matplotlib/h5py/numba signalés ne
  sont pas nécessaires aux fonctions présentes. Aucun nouvel import caché NumPy
  ajouté arbitrairement : les calculs réels dans le bundle passent.
- Anciens noms conservés uniquement pour la lecture des anciens projets, sans
  renommer de package actif. La version du format projet reste indépendante.
- Sources inchangées fonctionnellement : ajout de la version Qt et d'un diagnostic
  explicitement demandé par argument de lancement. Aucune interface métier modifiée.
- 124 tests existants réussis, puis build réussi sous Windows PowerShell 5.1.
  Les diagnostics gelés passent dans `dist` et dans une copie déplacée sous
  `artifacts/Physalix-1.0.0`. Lancement normal : fenêtre Physalix réactive et fermeture
  propre, Python chargé depuis le bundle, aucune DLL du venv ou du runtime Codex.
- 684 fichiers, **309 495 068 octets (295,16 Mio)**. Ressources vérifiées octet par
  octet ; PE x64 graphique version 1.0.0 ; plugins Qt et runtimes présents ;
  aucun dossier source, tests, environnement virtuel ou cache Python distribué.
- Les métadonnées et licences tierces sont conservées, les caches et scripts
  auxiliaires de génération des notices sont exclus. L'ancienne notice de démo,
  qui annonçait à tort l'absence de sauvegarde, n'est plus distribuée.
- **Inno Setup absent** du PATH, des emplacements habituels et des entrées de
  désinstallation inspectées : le `.iss` est préparé mais non compilé. Aucun
  installateur produit ; installation, mise à jour et désinstallation non testées.
- Pas de PC propre/VM disponible dans cette session, pas de certificat fourni,
  pas de signature ni de garantie antivirus. Aucune publication Git effectuée.

## Validation initiale après installation d'Inno Setup 6 (ancien mode utilisateur)

La commande complète `scripts/build_release.ps1` a réussi sous Windows PowerShell
5.1, sans modification fonctionnelle. Inno Setup **6.7.3** a compilé avec succès :

`C:\Physalix\artifacts\Physalix-Setup-1.0.0.exe`

- Installateur : **84 028 280 octets** (84,0 Mo / 80,1 Mio).
- Application reconstruite : **309 489 328 octets**, 683 fichiers. Le script
  auxiliaire de génération de notices présent dans le premier bundle est exclu.
- SHA-256 vérifié contre le fichier `.exe.sha256` :
  `21bbc9019c0ae3d38a9b84018b6b2a814545423cbfc069b75188cc4252e5cde7`.
- 124 tests automatiques réussis ; diagnostics scientifiques et Qt du bundle
  réussis ; lancement normal et fermeture propres.
- Métadonnées de l'installateur : Physalix, version 1.0.0.0, icône présente,
  exécutable graphique, manifeste `asInvoker`. Signature : **NotSigned**.
- Installation silencieuse locale dans un dossier de test dédié : réussite,
  683 fichiers comparés aux empreintes du bundle, entrée Windows 1.0.0 unique,
  raccourcis Bureau/menu Démarrer présents avec la bonne cible, lancement réussi.
- Réinstallation de 1.0.0 : réussite, aucune entrée Windows supplémentaire,
  fichier personnel de test conservé.
- Désinstallation : réussite, application/runtime/raccourcis/entrée Windows
  supprimés ; fichier personnel de test conservé. L'installation de test a été
  retirée du poste. Rapports dans `artifacts/installer-check.json`,
  `installer-install.log`, `installer-reinstall.log`, `installer-uninstall.log`
  et `installed-launch-check.json`.

Restent à tester sur un autre PC Windows sans Python : assistant interactif et
installation au chemin par défaut avec un compte standard, lancement depuis les
deux raccourcis, fonctions sur de vrais projets/CSV/vidéos, réinstallation et
désinstallation avec projets conservés. Le passage vers une future version
1.0.1 reste à valider lorsque cette version existe. Les politiques de sécurité et
SmartScreen du PC cible ne sont pas simulés ; aucun certificat n'a été fourni.

## Installateur final 1.0.0 : Program Files

Configuration actuelle : `DefaultDirName={autopf}\Physalix`, `DisableDirPage=no`,
`PrivilegesRequired=admin`. Sur Windows x64, le dossier proposé est
`C:\Program Files\Physalix`. L'utilisateur peut modifier ce chemin, notamment via
Parcourir. Les raccourcis utilisent `autoprograms` et `autodesktop` pour une
installation machine. `AppId`, `UsePreviousAppDir=yes`, icône et version 1.0.0 sont
conservés. PyInstaller et les fonctionnalités n'ont pas été modifiés.

L'ancien script utilisait LocalAppData, pas `C:\Physalix`. Ce dernier est le dossier
du dépôt ; les anciens tests imposaient explicitement un sous-dossier via `/DIR`.
Aucune installation directement à la racine `C:\Physalix` n'a été retrouvée.

Reconstruction Inno Setup 6.7.3 effectuée le 10 septembre 2026 :
`C:\Physalix\artifacts\Physalix-Setup-1.0.0.exe`, **84 028 263 octets**.
La somme SHA-256 est disponible dans le fichier `.exe.sha256` adjacent.
La page de destination et le bouton Parcourir ont été vérifiés visuellement.
Le test précédent dans Program Files a validé les 683 fichiers installés,
le lancement, les cibles des raccourcis communs, la réinstallation sans doublon
et la désinstallation avec conservation du fichier témoin personnel.
Les journaux correspondants portent le préfixe `programfiles-` dans `artifacts`.

Le fichier reconstruit est identique à celui du test Program Files précédent :
SHA-256 `f1ed18fb0bc42bdbdeda6a25612364c783c84d39c84eb7f39f03fa134af12d6d`.
Lors de la reprise, un nouveau lancement interactif a bien déclenché l'UAC
(processus Windows `consent` observé). Ce lancement s'est terminé sans ouvrir
l'assistant ; la cause de fermeture du dialogue sécurisé n'est pas observable.
Le bouton Parcourir est visible sur la capture précédente ; l'ouverture effective
de sa boîte de sélection n'a pas été confirmée par l'automatisation.
La version 1.0.0 a ensuite été déclarée validée par son auteur pour publication.
