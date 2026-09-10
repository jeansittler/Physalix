# Confidentialité

Physalix est une application de bureau. L’audit du code de la version 1.1.3 n’a
identifié ni télémétrie, ni publicité, ni compte utilisateur, ni envoi volontaire
des projets, tableaux, vidéos ou résultats de calcul.

## Données locales

Les projets et exports sont enregistrés uniquement aux emplacements choisis par
l’utilisateur. Les vidéos peuvent être décodées dans un dossier temporaire local,
supprimé lorsque la vidéo est remplacée ou à la fermeture normale de l’application.

Le mécanisme de mise à jour conserve dans
`%LOCALAPPDATA%\Physalix\updates` l’heure de la dernière vérification et un journal
rotatif limité. Un installateur téléchargé est placé dans un dossier temporaire.

## Connexion réseau

Après le démarrage, Physalix peut vérifier automatiquement, au plus une fois par
24 heures, la présence d’une mise à jour sur GitHub. Une vérification peut aussi
être demandée manuellement. Cette requête transmet nécessairement à GitHub et aux
intermédiaires réseau habituels l’adresse IP et un en-tête `User-Agent` contenant
le nom et la version de Physalix. Si l’utilisateur accepte une mise à jour,
l’installateur est téléchargé depuis l’URL HTTPS du manifeste puis contrôlé par
SHA‑256 avant son lancement.

Le code audité n’effectue aucune autre transmission réseau volontaire. Les règles
de confidentialité de GitHub et la configuration réseau du poste s’appliquent aux
requêtes de mise à jour.
