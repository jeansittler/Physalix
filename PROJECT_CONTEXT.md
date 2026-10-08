# PHYSALIX — CONTEXTE DE TRAVAIL

> **Source de référence du projet**
>
> Ce fichier sert de contexte initial pour tout nouveau chat ChatGPT/Codex consacré à Physalix.
> Avant de proposer une modification, un prompt Codex, une refonte UI, une release ou un test, respecter les conventions, décisions d’architecture et méthodes de travail décrites ici.
>
> Ne pas demander à l’utilisateur de répéter une information déjà présente dans ce fichier.
>
> Ce fichier doit rester **compact, actuel et maintenable** : remplacer les informations devenues obsolètes au lieu d’empiler un historique exhaustif.

---

## 1. Projet

**Nom :** Physalix
**Type :** logiciel pédagogique de physique / traitement et acquisition de données
**Dépôt :** `C:\Physalix`
**Dépôt GitHub :** `jeansittler/Physalix`
**Licence :** GPL-3.0

Physalix est une application desktop Python/PySide6 destinée notamment à l’enseignement de la physique.

Fonctionnalités principales existantes :
- Données / tableaux de mesures ;
- Graphique ;
- Modélisation ;
- Pointage vidéo ;
- Calculs ;
- Statistiques ;
- Numérisation de graphiques ;
- Acquisition Arduino.

---

## 2. État actuel

### Version publique

**Physalix 1.5.0**

Commit de release :

`25d63ff85f7a8307c71c3d171c40c1e2b1ee0cb3`

Tag :

`v1.5.0`

Branche stable :

`main`

État attendu :

`main == origin/main == 25d63ff85f7a8307c71c3d171c40c1e2b1ee0cb3`

Working tree attendu : propre.

### Release 1.5.0

Physalix 1.5.0 a été publiée sur GitHub comme release stable et Latest.

Assets publiés :
- `Physalix-Setup-1.5.0.exe`
- `Physalix-Setup-1.5.0.exe.sha256`
- `update.json`

SHA-256 de l’installateur 1.5.0 :

`5eb1a9e8b92567ddef72914ba2532e68355d5b05567757fe38f38e05ce62e5c6`

`update.json` public :
- version `1.5.0`
- `mandatory = false`
- URL de l’installateur cohérente avec la release GitHub
- SHA identique à celui de l’installateur
- changelog cumulatif

Les ressources publiques ont été vérifiées en HTTP 200 et l’installateur public a été retéléchargé puis re-hashé avec succès.

### Validation restante

La validation réelle du parcours :

`1.4.1 → détection 1.5.0 → téléchargement → SHA → installation → redémarrage → test Arduino`

reste à effectuer manuellement si elle n’a pas encore été confirmée dans le chat courant.

---

## 3. Méthode ChatGPT / Codex

### Toujours préciser le modèle Codex conseillé

Pour toute tâche Codex, ChatGPT doit indiquer explicitement le niveau recommandé :

**GPT-5.6 Sol — minimal**
- changement local et mécanique ;
- petite correction ;
- test ciblé ;
- commit / push ;
- ajustement de texte ou configuration ;
- checkpoint Git.

**GPT-5.6 Sol — moyen**
- compréhension de plusieurs fichiers ;
- évolution fonctionnelle raisonnable ;
- refonte UI localisée ;
- modification nécessitant de suivre quelques interactions entre composants.

**GPT-5.6 Sol — élevé**
- intégration complexe ;
- architecture importante ;
- release ;
- fusion de branches ;
- bug multi-couches ;
- modification firmware/PC nécessitant une compréhension globale.

**GPT-5.6 Sol — très élevé**
- exceptionnel ;
- problème particulièrement difficile, ambigu ou transversal ;
- seulement si « élevé » n’est raisonnablement pas suffisant.

### Préserver les crédits Codex

Principe permanent :
- prompts précis, courts et complets ;
- éviter les audits généraux redondants ;
- limiter l’exploration aux fichiers nécessaires ;
- éviter les micro-phases inutiles ;
- tests ciblés pendant le développement ;
- une seule suite complète aux checkpoints importants ;
- ne pas relancer une suite complète qui vient de passer sans raison ;
- ne pas utiliser un niveau de modèle plus élevé que nécessaire.

### Validation avant Git

Par défaut :
- ne pas commit/push avant validation technique et, si pertinent, validation visuelle manuelle ;
- lorsque le changement est validé, faire ensuite un checkpoint Git propre ;
- ne jamais publier une release avant validation explicite des tests/builds nécessaires.

---

## 4. Commandes et tests manuels

Quand un test manuel est demandé, toujours donner **directement la commande PowerShell prête à copier**.

Commande habituelle de lancement en développement :

```powershell
cd C:\Physalix
.\.venv\Scripts\python.exe .\main.py
```

Si une branche particulière est requise, inclure aussi explicitement :

```powershell
git switch <branche>
```

Ne pas utiliser :

```text
python -m physalix
```

car le projet ne repose pas sur un `__main__.py` pour le lancement habituel.

Minimiser les étapes de test : ne demander que les contrôles réellement utiles.

---

## 5. Conventions UI Physalix

### Principe général

L’interface doit rester :
- sobre ;
- desktop ;
- scientifique ;
- compacte mais lisible ;
- cohérente d’un onglet à l’autre ;
- adaptée aux écrans portables ;
- sans aspect « dashboard web » ;
- sans apparence « générée par IA ».

Ne pas gagner de place en réduisant abusivement les polices.

Le gain d’espace doit venir de :
- meilleurs layouts ;
- regroupements logiques ;
- marges maîtrisées ;
- suppression des hauteurs inutiles ;
- panneaux scrollables localement si nécessaire.

### Onglets de référence visuelle

Lors d’une nouvelle refonte, prendre en priorité comme références internes :
- Graphique ;
- Modélisation ;
- Pointage ;
- Numérisation ;
- Acquisition.

Réutiliser les mêmes composants, marges, rôles et conventions existants plutôt que créer une nouvelle identité.

### Menus déroulants — règle importante

**Ne pas créer un `QComboBox` Qt brut si le composant harmonisé Physalix est applicable.**

Utiliser le composant partagé :

`PopupComboBox`

avec les helpers existants :

- `configure_popup()`
- `update_popup_height()`

Ce comportement a déjà été harmonisé entre plusieurs écrans.

Règle visuelle :
- popup propre ;
- hauteur adaptée au contenu ;
- environ 8 éléments visibles maximum ;
- scroll au-delà ;
- cohérence avec les menus de Graphique / Calculs / Modélisation.

Lorsqu’un nouvel écran ou un nouveau sélecteur est ajouté, vérifier explicitement qu’il suit cette convention.

### Responsive

Pour les écrans complexes, penser notamment à :
- `1366×768`
- `1600×900`
- `1920×1080` en fenêtre non maximisée

Éviter un scroll vertical global si un layout principal avec panneaux locaux peut faire mieux.

---

## 6. Architecture et intégrations importantes

### Modèle de données

Physalix utilise un modèle de mesures partagé.

Ne pas créer inutilement un second système de données parallèle.

L’Acquisition transfère ses résultats vers les mécanismes existants de Données et Graphique.

APIs importantes utilisées par Acquisition :
- `DataTab.append_measurements(...)`
- `GraphWorkspace.add_data_graph(...)`
- `GraphWorkspace.add_data_graph_series(...)`

Préserver la compatibilité de ces APIs sauf refonte explicitement décidée.

### Onglets

L’onglet Acquisition a été ajouté en dernier afin de préserver les indices historiques des onglets existants.

Ne pas réordonner les onglets sans raison forte, car des préférences/états sauvegardés peuvent dépendre de leur ordre.

### Chargement de projet

Les changements impliquant un remplacement de projet doivent tenir compte des nettoyages/callbacks de l’Acquisition.

Ne pas introduire de callback ou état matériel persistant après un `replace_project()`.

---

## 7. Acquisition Arduino — état fonctionnel

### Matériel cible

Carte de référence :
- Arduino Uno R3 ou compatible ;
- ATmega328P ;
- logique 5 V.

Carte physique déjà utilisée :
- Funduino compatible Uno R3.

### Montage RC de référence

Montage de test :

`D8 → R → nœud`

Le nœud est relié :
- à `A0`
- au condensateur

Condensateur :
- borne positive côté nœud / A0 ;
- borne négative vers `GND`.

Montage de validation historique :
- `R = 1 kΩ`
- `C = 1000 µF`
- `τ = 1 s`

Montage pédagogique prévu pour le TP :
- `R = 1 kΩ`
- `C = 100 µF`
- `τ = 0,10 s`

### Fonctionnalités Acquisition 1.5.0

Le module gère :
- détection du port série ;
- connexion / déconnexion ;
- détection de version firmware ;
- installation/mise à jour firmware depuis Physalix ;
- acquisition analogique A0 ;
- affichage temporaire en temps réel ;
- résultats partiels ;
- transfert vers Données / Graphique ;
- Échelon ;
- Carré — N périodes ;
- GBF carré continu ;
- synchronisation sur front montant ;
- affichage de `uC(t)` et de `E(t)` ;
- indicateur d’échantillonnage en mode GBF.

### Interface Acquisition

Architecture UI validée :
- bandeau Connexion compact en haut ;
- grande courbe à gauche ;
- panneau de réglages à droite ;
- scroll uniquement local aux réglages ;
- Actions fixes dans le panneau droit ;
- pas de scroll global ;
- graphique majoritaire ;
- adapté à un portable.

Les boutons GBF « Démarrer le générateur » et « Arrêter le générateur » sont sur deux lignes pleine largeur pour préserver la lisibilité.

### Indicateur d’échantillonnage GBF

Calcul :

`Fe acquisition / fréquence GBF réellement appliquée`

La fréquence GBF doit provenir de la valeur réellement appliquée après ACK, pas de la consigne demandée.

Seuils :
- `>= 100 pts/période` : excellent
- `>= 50` : très bon
- `>= 20` : correct
- `>= 10` : limité
- `< 10` : faible

Cet indicateur est pédagogique uniquement :
- il ne bloque jamais l’acquisition ;
- aucun warning bloquant ;
- aucune confirmation supplémentaire.

---

## 8. Contrôleur Acquisition / protocole

### Transport

`QSerialPort` est utilisé.

Principe :
- communication événementielle ;
- pas de boucle bloquante GUI ;
- `readyRead` ;
- buffer borné ;
- mise à jour UI par lots.

### Framing

Format historique du protocole :

`A5 5A | version:u8 | type:u8 | length:u16 LE | payload | CRC16:u16 LE`

CRC :
- CRC-16/CCITT-FALSE
- calculé sur version/type/length/payload

Payload maximum :
- 512 octets

Protocol version :
- `1`

### États / messages importants

Le protocole comprend notamment :
- HELLO
- HELLO_ACK
- CONFIG
- CONFIG_ACK
- START
- STOP
- DATA
- END
- ERROR

Extensions GBF :
- GEN_CONFIG
- GEN_CONFIG_ACK
- GEN_START
- GEN_START_ACK
- GEN_STOP
- GEN_STOP_ACK
- GEN_STATUS
- GEN_STATUS_ACK
- GEN_KEEPALIVE
- ACQ_STARTED
- DATA_GBF

Ne pas changer le protocole sans raison forte et plan de compatibilité explicite.

---

## 9. Firmware Arduino

### Version actuelle

Firmware Physalix :

`1.2.0`

Protocol :

`1`

Capabilities :

`0x0000001F` / `31`

### Artefacts de référence

HEX SHA-256 :

`2c2ac15843fdaaae6bc63a9ece84bc5a61740f25ad2c3d81bf9b07010901f30f`

Manifest SHA-256 :

`98e8de11f415991d296afcd9895ac498676fcd8b5461cb899bfe2d01fa55919a`

AVRDUDE 8.1 — exe SHA-256 :

`b08186071b0877ceed6ec3e86dd42ee6d2b7556859659b34d4e326069cafbf45`

AVRDUDE 8.1 — conf SHA-256 :

`690c40a8163ae845bf2b6d4635e8a3534ea75c263d8e7e59d693b182c738cf41`

Ne pas reconstruire le firmware « pour être sûr » lors d’une release applicative si aucun changement firmware n’a eu lieu.

### Toolchain firmware

- Arduino CLI 1.5.1
- core `arduino:avr@1.8.8`
- FQBN `arduino:avr:uno`

Le build doit utiliser l’application `.ino.hex`, jamais `.with_bootloader.hex`.

---

## 10. GBF continu

### Architecture

GBF indépendant de l’acquisition.

- Timer2 : génération GBF
- Timer1 : acquisition ADC
- sortie : D8
- signal carré 0–5 V
- duty-cycle 50 %

Plage :
- environ `0,1 Hz` à `1000 Hz`

Fréquence d’acquisition maximale utile actuelle :
- environ `4 kHz`

Conséquence pédagogique :
- 10 Hz → ~400 points/période
- 50 Hz → ~80
- 100 Hz → ~40
- 200 Hz → ~20
- 500 Hz → ~8
- 1 kHz → ~4

À haute fréquence, ne pas prétendre que la courbe est finement résolue : l’indicateur d’échantillonnage existe précisément pour l’expliciter.

### Synchronisation

Si le GBF est déjà RUNNING :
- START acquisition → état ARMED ;
- attente du prochain front montant ;
- ce front définit `t = 0` ;
- `ACQ_STARTED` déclenche le passage en acquisition réelle.

Les données `DATA_GBF` incluent :
- ADC ;
- bitmap de l’état physique E ;
- indices/session/sequence.

`E_k` correspond à l’état physique de D8 capturé juste avant l’ADC de l’échantillon k.

---

## 11. Flash firmware depuis Physalix

Module dédié :

`physalix/firmware_flash.py`

Le flash :
- est explicite ;
- n’est jamais automatique ;
- utilise un `QProcess` asynchrone ;
- ne doit pas bloquer l’UI.

Commande AVRDUDE de référence :

```text
avrdude.exe -C <conf> -p atmega328p -c arduino -P COMx -b 115200 -D -U flash:w:<hex>:i
```

Ne pas ajouter `-V`.

Ne pas toucher :
- fuses ;
- EEPROM ;
- bootloader.

Le succès n’est validé qu’après :
- code retour flash correct ;
- reconnexion ;
- handshake firmware compatible.

---

## 12. Tests de référence

### Acquisition

Checkpoint complet historique avant finalisation UI/GBF :
- `391 tests` — OK

Suite complète de release 1.5.0 :
- `399 tests`
- `405,141 s`
- OK

Dernière validation ciblée UI Acquisition/Firmware UI avant intégration :
- `56 tests`
- OK

Ne pas utiliser ces nombres comme exigence absolue après de futurs ajouts : le nombre de tests augmentera.

### Méthode

Pendant le développement :
- tests ciblés.

Avant une release importante :
- une suite complète.

Après correction d’un échec :
- tests ciblés ;
- puis une nouvelle suite complète uniquement quand la correction est prête.

Ne jamais désactiver ou supprimer un test pour faire passer une release.

---

## 13. Packaging et updater

### Release Windows

Physalix est distribué avec un installateur Windows.

Workflow actuel :
- build/bundle ;
- smoke test ;
- installateur ;
- SHA-256 ;
- `update.json` ;
- release GitHub.

Les ressources Acquisition nécessaires au runtime doivent être incluses :
- firmware ;
- manifeste firmware ;
- AVRDUDE ;
- configuration AVRDUDE.

### Updater

Le système de mise à jour utilise `update.json`.

Une release doit vérifier :
- version correcte ;
- URL correcte ;
- SHA exact ;
- changelog UTF-8 ;
- compatibilité de l’updater existant.

Ne pas modifier la logique de fallback cumulatif sans nécessité.

---

## 14. Workflow de release

Pour une version publique :

1. vérifier branche / working tree / origin ;
2. intégrer les branches de développement proprement ;
3. résoudre les conflits en conservant les deux intentions, jamais `ours/theirs` aveuglément ;
4. mettre à jour version et release notes ;
5. exécuter tests ciblés nécessaires ;
6. exécuter une seule suite complète ;
7. `git diff --check` ;
8. build / bundle / smoke test ;
9. produire installateur ;
10. calculer SHA-256 ;
11. produire/vérifier `update.json` ;
12. commit `release: prepare Physalix X.Y.Z` ;
13. push `main` ;
14. tag annoté `vX.Y.Z` pointant exactement sur le commit de release ;
15. push tag ;
16. publier release GitHub stable/Latest ;
17. vérifier publiquement les assets et `update.json` ;
18. tester ensuite la vraie mise à jour depuis la version précédente.

Ne jamais prétendre qu’une validation réelle de mise à jour a été faite si l’utilisateur ne l’a pas effectivement réalisée.

---

## 15. Git / branches

### Stable

`main` = branche publique stable.

Ne pas développer directement une grosse fonctionnalité sur `main`.

### Acquisition

La branche historique :

`feature/acquisition`

est conservée.

Dernier commit avant intégration dans main :

`f0e43dc7796d39bd8a1244e3350d3aa7dca8e63a`

Message :

`feat: add GBF sampling quality indicator`

Commit de merge dans main :

`9b9c3785874d4f096b1d0ba95f91fb8dcd90669f`

Message :

`feat: integrate Arduino acquisition`

Après stabilisation définitive, la branche pourra éventuellement être supprimée, mais uniquement sur décision explicite.

---

## 16. Versioning

Version applicative actuelle :

`1.5.0`

Firmware Arduino :

`1.2.0`

Les deux versions sont indépendantes.

Ne pas incrémenter le firmware lorsqu’une release applicative ne modifie pas le firmware.

### Convention de versions

- patch `1.5.1` : corrections / petites améliorations compatibles ;
- minor `1.6.0` : nouvelle fonctionnalité significative compatible ;
- major `2.0.0` : vraie rupture importante, incompatibilité ou transformation majeure.

Ne pas passer à `2.0.0` simplement parce qu’une fonctionnalité est importante.

---

## 17. Décisions pédagogiques Acquisition

Pour l’étude RC, le critère pédagogique utile est le rapport entre :
- demi-période `T/2`
- constante de temps `τ = RC`

Une charge/décharge quasi complète est obtenue approximativement lorsque :

`T/2 >= 5τ`

Avec `R = 1 kΩ` et `C = 100 µF` :

`τ = 0,10 s`

Exemples :
- 0,1 Hz → `T/2 = 5 s = 50τ`
- 0,5 Hz → `10τ`
- 1 Hz → `5τ`
- 5 Hz → `1τ`
- 10 Hz → `0,5τ`
- 50 Hz → `0,1τ`
- 100 Hz → `0,05τ`
- 200 Hz → `0,025τ`

Pour le TP, `200 Hz` est plus exploitable qu’un `1 kHz` très pauvre en points par période avec l’échantillonnage actuel.

À haute fréquence avec un carré 0–5 V, la tension du condensateur tend vers une faible ondulation autour de la valeur moyenne (~2,5 V en régime établi), pas vers 0 V.

---

## 18. Ce qu’il ne faut pas faire automatiquement

Ne pas :
- lancer des audits globaux inutiles ;
- refactorer « au passage » ;
- refaire une UI déjà validée ;
- remplacer un composant harmonisé par un widget Qt brut ;
- changer le firmware pendant une tâche purement applicative ;
- changer le protocole sans plan de compatibilité ;
- lancer plusieurs suites complètes redondantes ;
- commit/push avant validation si le workflow prévoit une inspection manuelle ;
- publier une release sans vérification publique des assets ;
- inventer une validation matérielle non réalisée.

---

## 19. Mise à jour de ce fichier

À la fin d’un milestone important, mettre à jour ce fichier avec uniquement les informations durables.

Ajouter ou remplacer :
- version actuelle ;
- commit/tag actuels ;
- état des branches importantes ;
- nouvelle fonctionnalité structurante ;
- décision d’architecture durable ;
- nouvelle convention UI durable ;
- nouvelle commande de référence ;
- état des tests/release ;
- prochaine étape clairement décidée.

Ne pas en faire un journal exhaustif.

Quand une information devient obsolète :
- la remplacer ;
- ou la supprimer.

Éviter de conserver plusieurs « états actuels » contradictoires.

---

## 20. Consigne à utiliser au début d’un nouveau chat

Message recommandé :

> On continue le développement de Physalix.
> Le fichier `PROJECT_CONTEXT.md` joint est la source de référence actuelle du projet.
> Lis-le avant toute proposition et respecte notamment les conventions UI, le workflow Codex, les niveaux GPT-5.6 Sol et l’état Git/version qui y sont décrits.
> Si une information du chat courant est plus récente que le fichier, elle prévaut et le fichier devra être mis à jour au prochain checkpoint.

---

## 21. Prochaine étape

À définir dans le chat courant.

Avant de commencer une nouvelle fonctionnalité importante :
- créer une branche dédiée si nécessaire ;
- choisir explicitement le niveau GPT-5.6 Sol ;
- décrire d’abord le comportement attendu ;
- éviter de coder avant d’avoir clarifié l’ergonomie et les invariants importants.
