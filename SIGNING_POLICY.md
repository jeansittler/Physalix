# Politique de signature des versions officielles

Free code signing provided by SignPath.io, certificate by SignPath Foundation

La signature numérique avec SignPath n’est pas encore configurée pour Physalix.
Cette politique décrit le fonctionnement prévu sans prétendre qu’un certificat est
déjà opérationnel.

## Responsabilités

- **Committer / reviewer :** Jean Sittler (`jeansittler`)
- **Approver :** Jean Sittler (`jeansittler`)

Le projet est actuellement maintenu par une seule personne. Chaque demande de
signature officielle devra faire l’objet d’une approbation par l’approver désigné.

## Artefacts concernés

Seuls les artefacts construits depuis le dépôt officiel public
`jeansittler/Physalix`, via le workflow officiel, sont destinés à être signés. Les
builds locaux de développement ne sont pas nécessairement signés et ne constituent
pas des versions officielles.

Aucun certificat, mot de passe, jeton ou secret de signature ne doit être stocké
dans le dépôt. L’intégration devra séparer le build, la demande de signature, son
approbation, la vérification de la signature et la publication, tout en limitant les
permissions du workflow au strict nécessaire.

La gestion des données et des connexions réseau est décrite dans la
[politique de confidentialité](PRIVACY.md).
