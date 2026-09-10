# Politique de signature des versions officielles

Ce document décrit l’objectif du projet ; **la signature numérique n’est pas encore
active** pour Physalix.

- Les versions officielles devront être produites à partir du dépôt public
  `jeansittler/Physalix` par le workflow de build officiel.
- Le projet prévoit de demander l’accès à SignPath Foundation afin de signer les
  exécutables et installateurs officiels.
- Après activation, seuls les artefacts issus du workflow officiel, contrôlés puis
  publiés par les responsables du projet devront être présentés comme versions
  officielles.
- Un build local de développeur est utile pour tester une contribution, mais il
  n’est pas nécessairement signé et ne constitue pas une release officielle.
- Aucun certificat, mot de passe, jeton ou secret de signature ne doit être stocké
  dans le dépôt.

L’intégration future devra séparer le build reproductible, la demande de signature,
la vérification de la signature et la publication. Elle devra aussi conserver les
empreintes des artefacts et limiter les permissions du workflow au strict nécessaire.

Avant une demande à SignPath Foundation, ce document devra être complété avec les
noms ou groupes publics correspondant aux rôles de committers/reviewers et
d’approbateurs. La politique de confidentialité devra être présentée pendant
l’installation et la vérification automatique des mises à jour devra disposer d’une
option de désactivation conforme aux conditions alors applicables. La mention
officielle de fourniture du certificat ne sera ajoutée qu’après acceptation du projet
et activation effective du service.
