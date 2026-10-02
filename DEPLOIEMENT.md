# Mettre « Mon IA » en ligne gratuitement (Render + Neon)

Render fait tourner le programme (gratuit, il se met en veille après 15 min sans visite :
la première page met alors ~50 s à se réveiller). Neon garde les comptes, les
conversations et les fichiers (Postgres gratuit) : rien n'est perdu quand Render redémarre.

## 1. Base de données (2 min)
1. Crée un compte sur https://neon.tech → « New project ».
2. Copie la **Connection string** (commence par `postgresql://`). C'est ta `DATABASE_URL`.

## 2. Mettre le code sur GitHub
1. Crée un dépôt **privé** sur https://github.com/new.
2. Dans le dossier du projet :
   ```
   git init
   git add .
   git commit -m "Mon IA"
   git branch -M main
   git remote add origin https://github.com/TON_COMPTE/TON_DEPOT.git
   git push -u origin main
   ```
   Le fichier `.env` (tes clés) et le dossier `data/` sont exclus par `.gitignore` : ils ne partent pas sur GitHub.

## 3. Render
1. https://render.com → **New + → Blueprint** → choisis ton dépôt (il lit `render.yaml`).
2. Renseigne les variables demandées :
   - `DATABASE_URL` : la chaîne Neon
   - `GROQ_API_KEY` et `GEMINI_API_KEY` : tes clés
   - `SIGNUP_CODE` : un code secret que tu donnes aux personnes invitées
3. Déploie. L'adresse `https://mon-ia.onrender.com` (ou similaire) apparaît ; chaque personne y crée son compte avec le code d'invitation.

## Bon à savoir
- **Quotas gratuits partagés** : tous les utilisateurs utilisent TES clés Groq/Gemini. `DAILY_LIMIT` limite chaque personne (50 messages/jour par défaut dans `render.yaml`).
- **Sécurité** : ne laisse pas les inscriptions ouvertes sans `SIGNUP_CODE`. Si tu n'as confiance en personne, mets `ENABLE_EXCEL_SCRIPTS=0` (l'IA analyse les Excel mais ne les modifie plus) : c'est la fonction la plus sensible, car l'IA écrit du code exécuté sur le serveur (il est filtré et isolé, mais le risque zéro n'existe pas).
- **Mots de passe** : stockés hachés (scrypt), jamais en clair. Pas de « mot de passe oublié » : un utilisateur qui oublie le sien doit recréer un compte.
- **Local** : `start.bat` / l'icône « Mon IA » fonctionnent toujours ; les données sont dans `data/app.db`.
