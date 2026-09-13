# 🔎 Brocantes Alert

Surveillance automatique de brocantes/vide-greniers autour de **Fourchambault (Nièvre)**, avec un rayon de **50 km à vol d'oiseau** et notification par Gmail.

## Sources prévues

- Brocabrac — départements 58, 18 et 03
- Vide-Greniers.org — Nièvre

> Les sites peuvent modifier leur structure HTML ou leurs règles d'accès. Les parseurs sont donc volontairement séparés et devront être ajustés si une source ne renvoie plus correctement les annonces.

## Fonctionnement

Toutes les 15 minutes, GitHub Actions :

1. récupère les pages ;
2. extrait les annonces ;
3. tente de géocoder la ville avec Nominatim/OpenStreetMap ;
4. calcule la distance à vol d'oiseau depuis Fourchambault ;
5. ignore les événements à plus de 50 km ;
6. dédoublonne avec `data/state.json` ;
7. envoie un e-mail HTML pour chaque nouvelle annonce.

GitHub Actions n'est pas garanti à la seconde près : une exécution planifiée peut être légèrement décalée.

## Configuration Gmail

Le projet utilise le compte expéditeur :

`brocanteinfoo@gmail.com`

**Ne mets jamais le mot de passe normal Gmail dans GitHub.**

Utilise un **mot de passe d'application Google** après avoir activé la validation en deux étapes.

Dans GitHub : **Settings → Secrets and variables → Actions → New repository secret**

Crée :

- `GMAIL_USER` = `brocanteinfoo@gmail.com`
- `GMAIL_APP_PASSWORD` = ton mot de passe d'application Google
- `EMAIL_TO` = une ou plusieurs adresses séparées par des virgules
- `EMAIL_CC` = facultatif
- `EMAIL_BCC` = facultatif

Exemple :

```text
EMAIL_TO=toi@gmail.com,ami@gmail.com
```

## Installation

1. Crée un dépôt GitHub, par exemple `brocantes-alert`.
2. Envoie tous les fichiers de cette archive dans le dépôt.
3. Ajoute les secrets Gmail ci-dessus.
4. Va dans **Actions**.
5. Sélectionne **Surveillance brocantes**.
6. Clique sur **Run workflow** pour le premier test.
7. Vérifie les logs et la réception du mail.

Ensuite le workflow est planifié toutes les 15 minutes.

## Désabonnement

Le mail contient un lien qui ouvre un nouveau message vers `brocanteinfoo@gmail.com` avec l'objet :

`DESABONNEMENT - Alertes brocantes`

Le désabonnement n'est volontairement pas automatisé : il faut ensuite retirer l'adresse de `EMAIL_TO` dans les secrets GitHub.

## Structure

```text
brocantes-alert/
├── main.py
├── requirements.txt
├── data/
│   └── state.json
├── .github/
│   └── workflows/
│       └── brocantes.yml
├── .gitignore
└── README.md
```

## Important

Cette V1 fournit une base prête pour GitHub Actions, mais l'extraction réelle des annonces dépend de la structure actuelle des deux sites. Si un site utilise du JavaScript, une protection anti-bot, ou change son HTML, le parseur devra être adapté.

La géolocalisation utilise Nominatim : il faut rester raisonnable avec les requêtes et respecter les conditions d'utilisation du service.
