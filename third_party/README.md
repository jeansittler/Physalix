# Conformité des composants tiers

Ce dossier décrit les composants réellement embarqués dans la distribution
Windows de Physalix 1.1.3. Il ne contient pas les archives de code source, afin
de ne pas alourdir le dépôt Git.

- `components.json` est la source de vérité versionnée pour les versions,
  licences, provenances et obligations.
- `licenses/` contient les textes génériques qui ne sont pas déjà couverts par
  la licence GPL-3.0 du projet.
- `scripts/generate_compliance.py` vérifie l'environnement et le bundle, puis
  produit un inventaire avec les empreintes des binaires distribués.

Avant toute distribution publique d'un binaire, le responsable de la release
doit également récupérer les archives indiquées par `source_url`, conserver les
scripts et correctifs de `pyav-ffmpeg` et rendre le code source correspondant
accessible depuis le même emplacement que le binaire. Le manifeste ne remplace
pas cette mise à disposition.

Commande de contrôle locale :

```powershell
.venv\Scripts\python.exe scripts\generate_compliance.py dist\Physalix
```

La liste est volontairement auditable et doit être mise à jour lors de chaque
changement de roue PyAV, PySide6 ou de chaîne de compilation.
