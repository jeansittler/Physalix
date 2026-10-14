# Physalix Spectrophotometer Nano

Firmware du spectrophotomètre Physalix pour Arduino Nano officiel A000005
(ATmega328P, 5 V, 16 MHz) et capteur Adafruit AS7341 à l'adresse I²C `0x39`.

## Matériel

- AS7341 : SDA sur A4, SCL sur A5, alimentation 5 V et GND ;
- LED blanche externe : D3 PWM, résistance série 220 Ω ;
- liaison USB série : 115200 bauds ;
- aucun LCD.

La LED est forcée à l'arrêt au démarrage, après chaque mesure, après `STOP` et
sur toute erreur de mesure. Le firmware ne calcule ni transmission ni
absorbance.

## Dépendances de compilation

- Arduino CLI 1.5.1 ;
- core `arduino:avr@1.8.8` ;
- bibliothèque `Adafruit AS7341` 1.4.1 ;
- dépendance transitive `Adafruit BusIO`.

Commandes d'installation à exécuter explicitement si ces dépendances manquent :

```powershell
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli lib install "Adafruit AS7341@1.4.1"
```

Compilation seule, sans téléversement :

```powershell
cd C:\Physalix-spectro
arduino-cli compile --fqbn arduino:avr:uno --clean --warnings all `
  .\firmware\physalix_spectrophotometer_nano
```

Le FQBN `arduino:avr:uno` produit le code ATmega328P demandé. Les paramètres de
téléversement propres au bootloader du Nano seront traités lors des essais
matériels et ne font pas partie de ce lot.

## Protocole

Framing partagé Physalix V1 :

`A5 5A | version:u8 | type:u8 | longueur:u16 LE | payload | CRC16:u16 LE`

Le CRC est CRC-16/CCITT-FALSE sur `version/type/longueur/payload`. Le parseur
accepte la limite commune de 512 octets tout en ne conservant que les 7 octets
nécessaires à la plus grande commande PC, afin d'économiser la SRAM.

Messages implémentés :

- 32 `SPECTRO_HELLO` → 33 `SPECTRO_HELLO_ACK` ;
- 34 `SPECTRO_CONFIG` → 35 `SPECTRO_CONFIG_ACK` ;
- 36 `SPECTRO_MEASURE` → 37 `SPECTRO_DATA` ;
- 38 `SPECTRO_ERROR` ;
- 39 `SPECTRO_STOP` → 40 `SPECTRO_STOP_ACK`.

La version initiale du firmware spectro est `1.0.0`. `HELLO_ACK` contient la
signature `SPCT`, le type de capteur AS7341 (`1`) et le bitmask de capacités.

## Capacités

| Bit | Valeur | Fonction |
| --- | ---: | --- |
| 0 | `0x00000001` | F1 à F8, Clear et NIR |
| 1 | `0x00000002` | LED externe D3 commandée en PWM |
| 2 | `0x00000004` | mesures LED éteinte et LED éclairée |
| 3 | `0x00000008` | annulation coopérative par `STOP` |
| 4 | `0x00000010` | flags de saturation par canal |

Bitmask V1 : `0x0000001F`.

## Codes ERROR

| Code | Signification |
| ---: | --- |
| 1 | version de protocole incompatible |
| 2 | taille ou valeur de payload invalide |
| 3 | commande inconnue |
| 4 | configuration AS7341 invalide |
| 5 | capteur absent ou indisponible |
| 6 | configuration non appliquée ou non relue à l'identique |
| 7 | `config_id` absent ou différent de la configuration active |
| 8 | mesure déjà en cours |
| 9 | démarrage de mesure impossible |
| 10 | timeout de mesure |
| 11 | erreur ou timeout I²C |
| 12 | CRC invalide |
| 13 | payload supérieur à 512 octets |

Pour une erreur sans requête corrélable, `request_id` vaut zéro.

## Mesure AS7341

`CONFIG` accepte les gains Adafruit `0..10` (0,5× à 512×). `ASTEP=65535` est
rejeté car cette valeur est réservée par la documentation AS7341. L'ACK ne
renvoie les paramètres qu'après écriture et relecture exactes du capteur.

La lecture utilise l'API asynchrone Adafruit et un tableau de 12 `uint16_t` :

- indices 0 à 3 : F1 à F4 ;
- indices 4 et 5 : première paire Clear/NIR, non transmise ;
- indices 6 à 9 : F5 à F8 ;
- indices 10 et 11 : paire Clear/NIR transmise.

Le timestamp est capturé à la fin des deux groupes successifs. Le seuil de
saturation numérique vaut `min((ATIME+1)×(ASTEP+1), 65535)` et alimente les
bits 0–7 pour F1–F8, 8 pour Clear et 9 pour NIR. La saturation de Clear ne
rejette pas les autres bandes.

Le timeout est calculé à partir du temps d'intégration des deux groupes, avec
une marge de 2,5 s. `STOP` éteint immédiatement la LED puis désactive la mesure
du capteur. L'appel Adafruit qui change le SMUX peut toutefois occuper une
itération pendant environ une seconde ; avec le timeout I²C de 25 ms, le délai
maximal observé par le firmware avant de traiter `STOP` est donc théoriquement
d'environ 1,1 s. Cette borne devra être vérifiée sur le matériel réel.
