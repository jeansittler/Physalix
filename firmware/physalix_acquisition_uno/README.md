# Physalix Acquisition Uno

La version canonique du firmware, la version du protocole et les capacités
annoncées par `HELLO_ACK` sont définies dans `firmware_metadata.h`.

- Cible : Arduino Uno R3 / ATmega328P 16 MHz, logique et référence ADC AVcc 5 V.
- V1 : entrée A0 uniquement ; sortie D8 par défaut (D2 à D13 acceptées).
- Liaison : 115200 bauds, protocole Physalix V1 binaire avec CRC-16/CCITT-FALSE.
- Cadencement : Timer1 en CTC ; l'ISR compare lance le CAN 10 bits à 125 kHz et l'ISR ADC range le résultat dans un anneau statique de 64 valeurs. Les paquets DATA contiennent au plus 48 valeurs.
- Période garantie : 250 µs à 4 194 304 µs. Le firmware choisit le plus petit préscaler Timer1 utilisable et renvoie la période quantifiée dans CONFIG_ACK.
- Synchronisation : le niveau final est appliqué immédiatement avant le lancement de la conversion portant l'index demandé. Pour l'index 0, l'échelon et la première conversion sont lancés au START, puis Timer1 est démarré en dernier : l'intervalle 0→1 vaut donc au moins `Te` (à quelques cycles d'instructions près), sans jamais être raccourci ; les intervalles suivants valent exactement une période CTC.
- Sécurité logique : à la fin, sur STOP ou sur erreur, la sortie revient au niveau initial configuré. Cela ne remplace aucune protection électrique de l'entrée.

Pour flasher manuellement : ouvrir `physalix_acquisition_uno.ino` dans Arduino IDE, sélectionner **Arduino Uno** et le port série, puis cliquer sur **Téléverser**. Fermer le moniteur série avant de connecter Physalix.

## Produire l'artefact officiel

Prérequis développeur épinglés :

- Arduino CLI `1.5.1` ;
- core `arduino:avr@1.8.8` ;
- FQBN `arduino:avr:uno` ;
- environnement Python du dépôt.

Le script ne télécharge ni outil ni core. Si nécessaire, installer explicitement
le core sur une machine de développement connectée :

```powershell
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
```

Depuis la racine du dépôt :

```powershell
.\scripts\build_firmware.ps1
```

Le dossier `build/firmware/physalix_acquisition_uno/` reçoit les sorties de
compilation temporaires. Seul le HEX applicatif normal est copié vers
`physalix/resources/firmware/uno/physalix_acquisition_uno.hex`; le fichier
`*.with_bootloader.hex` n'est jamais copié dans les ressources. Le manifeste
déterministe `physalix/resources/firmware/uno/manifest.json` est ensuite généré
avec la version, le protocole, les capacités et le SHA-256 du HEX.
