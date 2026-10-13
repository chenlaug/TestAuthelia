# Espace licences

Petite app web où tes clients voient leurs licences et leur date d'expiration.
Toi, tu les gères depuis `/admin`.

La connexion est entièrement gérée par Authelia + LLDAP : l'app ne stocke aucun
mot de passe, elle lit juste qui est connecté.

## Installation

1. Copie le dossier `licences-app` à côté de ton `docker-compose.yml`.
2. Ajoute le service de `docker-compose.extrait.yml` dans ton `docker-compose.yml`,
   sur le même réseau que ton reverse proxy et Authelia.
3. Lance-le :
   ```bash
   docker compose up -d --build licences
   ```
4. Dans ton reverse proxy, fais pointer ton domaine (par ex. `app.localtest.me`)
   vers `http://licences:8000`, avec la protection Authelia (forward auth) active.
   Le proxy doit transmettre les en-têtes `Remote-User`, `Remote-Groups` et `Remote-Name`.
   Si tu as suivi la doc Authelia pour ton proxy, c'est normalement déjà le cas.

## Règles Authelia

Si l'app est servie sur `app.localtest.me`, tes règles actuelles conviennent telles quelles :
les clients accèdent à `/` avec leur mot de passe, et `/admin` est réservé au groupe
`admins` avec 2FA. L'app vérifie aussi elle-même le groupe `admins` sur `/admin`.

Sur un autre domaine, recopie les trois règles en changeant `domain:`.

## Utilisation

- **Ajouter une licence** : va sur `/admin`, saisis l'identifiant du client
  (son User ID dans LLDAP), le produit et les dates.
- **Côté client** : il se connecte et voit toutes ses licences, avec le statut
  (active, expire bientôt, expirée, à venir) et le nombre de jours restants.

## Réglages

Dans la section `environment` du compose :

- `APP_NAME` : nom affiché en haut de page.
- `ADMIN_GROUP` : groupe LLDAP autorisé sur `/admin` (par défaut `admins`).
- `LOGOUT_URL` : adresse de déconnexion Authelia (lien masqué si vide).
- `SOON_DAYS` : nombre de jours avant l'échéance pour afficher « Expire bientôt » (30 par défaut).

## Sauvegarde

Toutes les licences sont dans un seul fichier : `licences_data/licences.db`.
Copie-le régulièrement ailleurs pour ne rien perdre.

## Sécurité

N'ajoute **jamais** de section `ports:` à ce service. L'app fait confiance à
l'en-tête `Remote-User` envoyé par le proxy : si elle était joignable directement,
n'importe qui pourrait se faire passer pour un client.
