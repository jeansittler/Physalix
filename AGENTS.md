# Instructions permanentes pour Codex

- Lire `PROJECT_CONTEXT.md` avant toute intervention dans le dépôt.
- Préserver les crédits et le temps d’exécution sans réduire la fiabilité : limiter l’exploration aux fichiers utiles et éviter les opérations redondantes.
- Prévenir l’utilisateur avant une opération potentiellement longue et en estimer la durée. En cas de problème de permissions ou d’environnement, diagnostiquer avant de relancer une opération coûteuse.
- Choisir le niveau GPT-5.6 Sol adapté à la difficulté : minimal pour une opération locale et mécanique, moyen pour une évolution circonscrite à plusieurs fichiers, élevé pour une intégration complexe ou une release, très élevé seulement pour un problème exceptionnellement ambigu ou transversal.
- Utiliser des tests ciblés pendant le développement. N’exécuter qu’une seule suite complète aux checkpoints techniques pertinents et ne pas répéter les tests ou builds déjà validés lorsque le code concerné n’a pas changé.
- Ne pas créer de commit, pousser, taguer ou publier avant validation explicite de l’utilisateur.
- Pour tout test manuel demandé, fournir une commande PowerShell directement prête à copier.
- Respecter la chaîne de release et de signature Authenticode Certum décrite dans `PROJECT_CONTEXT.md`. Ne jamais publier un installateur non signé ou insuffisamment vérifié.
- L’authentification SimplySign reste interactive. Ne jamais stocker ni exposer de PIN, OTP, jeton, clé privée ou accès au compte Certum.
