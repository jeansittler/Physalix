# Physalix — Contexte technique de la spectrophotométrie

Ce document conserve les informations techniques, matérielles et historiques du
module Spectrophotométrie. `PROJECT_CONTEXT.md` reste la source principale pour
l'état courant du projet, les règles Codex et le workflow de release.

Les informations ci-dessous sont séparées entre fonctionnement confirmé, historique
des prototypes et pistes qui ne doivent pas être présentées comme intégrées.

## 1. Fonctionnement actuel confirmé

La Spectrophotométrie est intégrée à `main` par le commit de fusion
`852eb5f987ce6140d3ad9944d6dbc1b01a3c3c9a`. Celui-ci conserve les six commits de
`feature/spectrophotometry`, dont le dernier est
`9c2577e46af869b203988285c3781fa1391bf4d0`.

Le module fournit actuellement :

- connexion série et identification du firmware Spectro ;
- acquisition des huit bandes visibles de l'AS7341 ;
- mesures noire, blanche et échantillon ;
- calcul des huit absorbances expérimentales ;
- affichage du spectre sans faire passer l'interpolation visuelle pour une mesure ;
- absorbance à une longueur d'onde choisie ;
- étalonnage Beer-Lambert, régression linéaire et concentration inconnue ;
- suivi cinétique de l'absorbance ;
- diagnostics de cinétique exportables ;
- transfert vers Données et Graphique ;
- persistance des expériences dans les projets Physalix ;
- installation explicite du firmware Nano, suivie d'une reconnexion et d'une
  vérification de compatibilité.

Le module réutilise le modèle de données partagé de Physalix. Il ne constitue pas
un second système de données parallèle.

### Validations acquises

- `615 tests` complets réussis avant la fusion, sur le même arbre de code ;
- firmware Nano programmé et testé sur le matériel réel ;
- reconnexion et réutilisation du Nano après flash validées ;
- build PyInstaller final incluant le firmware Nano validé ;
- validation visuelle utilisateur réalisée.

Ces résultats ne valent pas validation d'une nouvelle release publique, d'un
installateur signé ou d'une mise à jour réelle depuis `1.5.2`.

## 2. Matériel de référence

Prototype validé :

- Arduino Nano officiel A000005 ;
- ATmega328P, logique 5 V, horloge 16 MHz ;
- capteur spectral Adafruit AS7341 ADA4698 ;
- adresse I²C `0x39` ;
- câble Qwiic / STEMMA QT QW-4C ;
- `A4 = SDA`, `A5 = SCL` ;
- alimentation AS7341 en 5 V et GND ;
- LED blanche externe 5 mm L5FWH ;
- LED pilotée en PWM par `D3` avec résistance série de `220 Ω` ;
- liaison PC par USB mini-B ;
- cuve standard placée dans un boîtier noir imprimé en 3D ;
- aucun LCD dans la version Physalix.

Le gros carré jaune du breakout Adafruit est la LED intégrée, pas le capteur. Le
capteur spectral est le petit composant sombre central. La LED verte d'alimentation
du breakout peut perturber la mesure optique ; la révision utilisée possède au dos
un jumper `LED` permettant de couper sa piste dédiée.

## 3. Firmware Nano et protocole

Firmware Spectro actuel :

- version `1.0.0` ;
- protocole `1` ;
- capacités `0x0000001F` / `31` ;
- signature de handshake `SPCT` ;
- liaison série à `115200` bauds en fonctionnement normal.

Framing partagé Physalix V1 :

`A5 5A | version:u8 | type:u8 | length:u16 LE | payload | CRC16:u16 LE`

Le CRC est CRC-16/CCITT-FALSE sur `version/type/length/payload`. La limite commune
est de 512 octets.

Messages Spectro :

- `SPECTRO_HELLO` / `SPECTRO_HELLO_ACK` ;
- `SPECTRO_CONFIG` / `SPECTRO_CONFIG_ACK` ;
- `SPECTRO_MEASURE` / `SPECTRO_DATA` ;
- `SPECTRO_ERROR` ;
- `SPECTRO_STOP` / `SPECTRO_STOP_ACK`.

Capacités V1 :

- F1 à F8, Clear et NIR ;
- LED externe D3 commandée en PWM ;
- mesures LED éteinte et LED éclairée ;
- annulation coopérative par `STOP` ;
- indicateurs de saturation par canal.

Le firmware mesure uniquement les données brutes. Il ne calcule ni transmission ni
absorbance. La LED est forcée à l'arrêt au démarrage, après chaque mesure, après
`STOP` et lors d'une erreur de mesure.

`CONFIG` accepte les gains AS7341 de 0,5× à 512×. `ASTEP=65535` est refusé. Les
paramètres ne sont confirmés qu'après écriture et relecture exactes du capteur.

La saturation numérique est évaluée par rapport à
`min((ATIME+1)×(ASTEP+1), 65535)`. La saturation du canal Clear n'invalide pas à
elle seule les huit bandes visibles.

Le traitement de `STOP` est coopératif. Un changement de SMUX peut retarder son
traitement ; la borne théorique documentée est d'environ 1,1 s et reste à confirmer
spécifiquement par une mesure matérielle dédiée.

## 4. Flash et ressources distribuées

Le firmware officiel est distribué dans
`physalix/resources/firmware/nano-spectro` avec un manifeste SHA-256 strict :

- HEX : `physalix_spectrophotometer_nano.hex` ;
- SHA-256 du HEX :
  `9e28edd2b807ca46658b6b1f0cdfbae9bb603855e528fce86c68f14005590777` ;
- schéma de manifeste : `2`.

Le Nano partage AVRDUDE 8.1 et sa configuration avec les ressources Uno :

- AVRDUDE exe SHA-256 :
  `b08186071b0877ceed6ec3e86dd42ee6d2b7556859659b34d4e326069cafbf45` ;
- configuration SHA-256 :
  `690c40a8163ae845bf2b6d4635e8a3534ea75c263d8e7e59d693b182c738cf41`.

Le flash reste explicite. L'utilisateur choisit le profil de bootloader :

- bootloader récent : `115200` bauds ;
- ancien bootloader : `57600` bauds.

Physalix ne tente jamais automatiquement l'autre profil après un échec. Le succès
final exige la reconnexion, la signature `SPCT`, le capteur AS7341, le protocole 1,
les capacités attendues et la version firmware distribuée.

Toolchain de référence :

- Arduino CLI 1.5.1 ;
- core `arduino:avr@1.8.8` ;
- bibliothèque `Adafruit AS7341` 1.4.1 ;
- dépendance transitive `Adafruit BusIO` ;
- FQBN `arduino:avr:uno`, adapté au Nano ATmega328P utilisé.

Ne jamais toucher aux fuses, à l'EEPROM ou au bootloader. Utiliser le HEX
applicatif, jamais une image avec bootloader.

Lors d'un futur essai matériel demandant un programme Arduino, fournir un sketch
complet prêt à copier-coller, et pas seulement des lignes isolées à modifier.

## 5. Mesure scientifique

Bandes visibles réellement mesurées :

- F1 : environ 415 nm ;
- F2 : environ 445 nm ;
- F3 : environ 480 nm ;
- F4 : environ 515 nm ;
- F5 : environ 555 nm ;
- F6 : environ 590 nm ;
- F7 : environ 630 nm ;
- F8 : environ 680 nm.

Pour chaque bande :

- mesure noire LED éteinte : `I_dark(λ)` ;
- mesure blanche : `I0(λ)` ;
- mesure de l'échantillon : `I(λ)` ;
- transmission corrigée :
  `T(λ) = (I(λ) - I_dark(λ)) / (I0(λ) - I_dark(λ))` ;
- absorbance : `A(λ) = -log10(T(λ))`.

Une absorbance est indisponible si la calibration manque, si les sessions ou les
paramètres d'acquisition diffèrent, si une mesure utile est saturée, si
`I0 <= I_dark` ou si `I <= I_dark`. Aucun arrondi ni valeur de remplacement n'est
injecté dans le calcul scientifique.

Les huit points restent identifiables comme mesures expérimentales. Une courbe
interpolée ou lissée est uniquement une aide visuelle et ne représente jamais des
longueurs d'onde réellement mesurées entre les bandes.

### Beer-Lambert

Le mode Beer-Lambert utilise une bande visible choisie, des étalons à concentration
positive ou nulle et au moins deux concentrations distinctes. La régression suit
`A = k c` avec intercept fixé à zéro. Une pente non positive ou numériquement nulle
est refusée. La concentration inconnue est signalée lorsqu'elle se situe hors du
domaine des étalons.

### Cinétique

Le mode Cinétique suit l'absorbance d'une bande choisie en fonction du temps. Les
expériences, points valides, interruptions et diagnostics sont conservés sans
présenter une acquisition interrompue comme complète. Les résultats peuvent être
transférés vers Données et Graphique.

## 6. Persistance et intégration Physalix

La sauvegarde de projet conserve notamment :

- configuration d'acquisition ;
- mesures noire et blanche ;
- spectres et provenance scientifique ;
- étalons et état Beer-Lambert ;
- expériences et historique cinétiques ;
- transferts déjà effectués vers Données et Graphique.

Au chargement, une cinétique restaurée reste inactive. Les callbacks, minuteries et
états matériels doivent être nettoyés lors d'un remplacement ou de la fermeture du
projet.

## 7. Interface et ergonomie

Le module suit les conventions desktop de Physalix : graphique principal, réglages
compacts, panneaux scrollables localement et composants harmonisés. Les modes
intégrés sont Spectre, Absorbance, Beer-Lambert et Cinétique.

Le workflow matériel reste explicite : connexion, noir, blanc, échantillon, analyse
et transfert. L'installation du firmware est une action utilisateur distincte ; elle
n'est jamais automatique.

## 8. Validation matérielle historique

Le prototype fermé a réellement validé :

- communication Nano ↔ PC ;
- détection AS7341 à `0x39` ;
- LED externe D3 ;
- trajet optique LED → cuve → AS7341 ;
- lecture des huit bandes ;
- lumière extérieure très faible dans les conditions de test.

Réglages du diagnostic de référence : `ATIME=100`, `ASTEP=999`, gain 8×, PWM 255.

Mesure représentative sans cuve :

- 415 nm : `3175` ; 445 nm : `26177` ; 480 nm : `9618` ;
- 515 nm : `19108` ; 555 nm : `21899` ; 590 nm : `18696` ;
- 630 nm : `13496` ; 680 nm : `5221` ;
- Clear : `65535` ; NIR : `2429`.

Le canal Clear saturait, contrairement aux huit bandes utiles. LED éteinte, les huit
bandes étaient à zéro dans ce test. Il ne faut donc pas réduire automatiquement le
gain uniquement à cause de Clear.

## 9. Historique du prototype

Le prototype dérive du Mini Spectro du lycée Valin, utilisé uniquement comme
référence matérielle initiale. Physalix ne dépend pas de son logiciel.

Un LCD 16×2 I²C a été câblé, détecté à `0x27` et testé, puis abandonné pour la
version Physalix afin de centraliser l'interface sur le PC.

Éléments mécaniques jugés satisfaisants :

- logement et orientation de la cuve ;
- cuve légèrement dépassante ;
- quatre vis et principe d'assemblage ;
- logement AS7341 et trajet optique ;
- emplacement Nano/breadboard ;
- ouverture mini-USB.

Points historiques à améliorer si un besoin réel est confirmé :

- passage du câble QW-4C ;
- maintien de la LED 5 mm ;
- maintien de la breadboard et du Nano ;
- suppression de l'ouverture LCD.

Une première V2 du boîtier a prévu un couvercle plein, le passage AS7341 élargi et
la conservation des fixations. La géométrie optique sensible n'a volontairement pas
été refaite sans validation réelle. Les évolutions mécaniques doivent rester
ciblées, démontables et réparables, sans multiplier les soudures ou composants sans
nécessité observée.

Le chantier a été développé dans `C:\Physalix-spectro` sur
`feature/spectrophotometry`, puis fusionné localement avec `--no-ff` et poussé sur
`main`. Cette organisation est historique ; les corrections courantes se font
désormais dans `C:\Physalix`, sauf nouveau chantier isolé.

## 10. Expérimentations et idées non garanties

Solutions envisagées pour des essais pédagogiques : eau distillée ou déminéralisée
comme blanc, permanganate de potassium dilué, sulfate de cuivre et colorants
alimentaires. Le permanganate est particulièrement intéressant autour de 515–555 nm.

Ces choix de solutions ne constituent pas des fonctionnalités logicielles ni une
validation générale de performances analytiques.

La confirmation instrumentée du délai maximal de traitement de `STOP` reste une
vérification matérielle spécialisée éventuelle. Elle ne doit pas être présentée comme
déjà réalisée.
