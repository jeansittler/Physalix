# Physalix Acquisition Uno

La version canonique du firmware, la version du protocole et les capacités
annoncées par `HELLO_ACK` sont définies dans `firmware_metadata.h`.

- Cible : Arduino Uno R3 / ATmega328P 16 MHz, logique et référence ADC AVcc 5 V.
- Firmware 1.2.0 : entrée A0 ; STEP et SQUARE_BURST sur D8 par défaut ; GBF continu exclusivement sur D8.
- Génération : échelon historique ou carré fini `SQUARE_BURST` 0/5 V sur exactement N périodes. La capacité `0x00000008` annonce le support du carré.
- Liaison : 115200 bauds, protocole Physalix V1 binaire avec CRC-16/CCITT-FALSE.
- Cadencement : Timer1 en CTC ; l'ISR compare lance le CAN 10 bits à 125 kHz et l'ISR ADC range le résultat dans un anneau statique de 64 valeurs. Les paquets DATA contiennent au plus 48 valeurs.
- Période garantie : 250 µs à 4 194 304 µs. Le firmware choisit le plus petit préscaler Timer1 utilisable et renvoie la période quantifiée dans CONFIG_ACK.
- Synchronisation STEP : le niveau final est appliqué immédiatement avant le lancement de la conversion portant l'index demandé. Pour l'index 0, l'échelon et la première conversion sont lancés au START, puis Timer1 est démarré en dernier : l'intervalle 0→1 vaut donc au moins `Te` (à quelques cycles d'instructions près), sans jamais être raccourci ; les intervalles suivants valent exactement une période CTC.
- Synchronisation SQUARE_BURST : le front montant et le lancement de l'échantillon 0 définissent `t = 0`. Chaque front suivant est appliqué avant la conversion du même index. Avec N périodes et H intervalles par demi-période, le dernier index `2×N×H` maintient la sortie à LOW avant le dernier échantillon, puis l'acquisition se termine.
- Plage pédagogique visée pour SQUARE_BURST : 0,1 à 100 Hz, avec un nombre de points par période adapté à l'expérience.
- Sécurité logique : à la fin, sur STOP ou sur erreur, la sortie revient au niveau initial configuré. Cela ne remplace aucune protection électrique de l'entrée.

## GBF carré continu — firmware 1.2.0

La capacité `0x00000010` annoncée dans `HELLO_ACK` active le GBF carré continu
dans Physalix.

- Timer2 est indépendant de Timer1 et commute D8 entre LOW et HIGH à 50 %.
- La sortie est un carré 0/5 V sur D8, de 0,1 à 1000 Hz, à rapport cyclique 50 %.
- Timer2 utilise un préscaler 64 et un tick de 4 µs.
- Une demi-période est découpée en chunks CTC de 1 à 256 ticks ; chaque chunk
  de `N` ticks utilise `OCR2A = N - 1`.
- Un keepalive série renouvelle un bail de 2,5 s. À son expiration, après
  `GEN_STOP`, au boot ou lors d'une faute interne, Timer2 est arrêté et D8
  revient à LOW.
- `GEN_CONFIG`, `GEN_START`, `GEN_STOP`, `GEN_STATUS` et `GEN_KEEPALIVE` sont
  traités dans la boucle principale ; aucune opération série n'a lieu dans
  l'ISR Timer2.
- Un `START` reçu pendant que le GBF tourne arme l'acquisition sans démarrer
  Timer1 ni lancer de conversion. Le prochain front physique LOW→HIGH de D8
  devient `t = 0` : l'ISR Timer2 capture `E_0`, déclenche l'ADC pour `k = 0`,
  réinitialise Timer1 puis le démarre en dernier afin que `k = 1` arrive un
  `Te` complet plus tard.
- `ACQ_STARTED(session)` est émis une seule fois depuis `loop()`, avant tout
  `DATA_GBF`, après que le front réel a eu lieu et que la conversion de `k = 0`
  a été déclenchée. Aucune trame ni aucun CRC n'est construit dans une ISR.
- Pour chaque `k >= 1`, l'ISR Timer1 lit le niveau physique de D8 immédiatement
  avant de lancer la conversion. L'ISR ADC range ensuite la mesure et ce niveau
  au même index dans deux anneaux statiques. `loop()` compacte les niveaux en
  bitmap LSB-first dans `DATA_GBF`; le `DATA` historique reste inchangé.
- La décision `DATA_GBF` est attachée à la session. Un `GEN_STOP` ou une
  expiration de keepalive après le déclenchement force D8 à LOW, mais laisse
  Timer1 terminer l'acquisition avec des bits E suivants à zéro. Avant le
  front, ces événements annulent l'armement et produisent une erreur explicite
  de déclenchement annulé. Un `STOP` acquisition pendant l'armement renvoie un
  `END` avec zéro mesure sans arrêter le GBF.
- À la fin normale, Timer1 et l'ADC s'arrêtent, les derniers `DATA_GBF` puis
  `END` sont envoyés, mais Timer2 continue : le générateur reste `RUNNING` tant
  qu'il reçoit son keepalive.

L’installation intégrée de Physalix utilise le HEX applicatif et l’AVRDUDE
embarqués, puis valide le firmware par un nouveau handshake. Arduino IDE n’est
pas nécessaire pour ce workflow.

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
