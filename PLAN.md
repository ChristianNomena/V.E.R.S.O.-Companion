# Plan d'Exécution : V.E.R.S.O. — Pilier 1 (L'OS Inversé)

*Cas d'usage initial : Délégation silencieuse et traitement d'intentions sur Slack*

---

## Phase 1 : Environnement, Dépendances & Structure

- [x] Créer l'environnement virtuel avec Python 3.13 sur macOS
- [x] Activer l'environnement virtuel
- [x] Installer les paquets requis via `pip` :
  - `flet` (interface graphique)
  - `sqlmodel` (ORM agnostique et gestion de base de données)
  - `pyperclip` (détection du presse-papiers)
  - `requests` (communication HTTP avec l'API)
  - `python-dotenv` (chargement des variables d'environnement)
- [x] Figer les dépendances dans un fichier `requirements.txt`
- [x] Créer les fichiers de base et l'architecture modulaire du projet :
  - `.env`
  - `.gitignore`
  - `main.py`
  - Modules internes sous `verso/` (`database/`, `sentinel/`, `services/`, `workers/`, `ui/`)
- [x] Préparer le dossier `deliverables/` pour recueillir les livrables générés en tâche de fond

---

## Phase 2 : Configuration Système & Variables d'Environnement

- [x] Configurer les variables dans le fichier `.env` :
  - Chaîne de connexion SQLite (`DATABASE_URL`)
  - Clé d'API Meta Muse (`META_MUSE_API_KEY`)
  - Point de terminaison HTTP de l'API (`META_MUSE_ENDPOINT`)
- [x] Valider les autorisations macOS :
  - Autoriser le terminal ou l'IDE dans *Réglages Système > Confidentialité et sécurité > Accessibilité*
  - Vérifier l'autorisation des notifications système natives

---

## Phase 3 : Modèle de Données & Persistance Locale (SQLModel)

- [x] Configurer le moteur SQLModel agnostique avec support multi-thread pour SQLite
- [x] Déclarer la table des tâches avec les champs :
  - Identifiant unique
  - Horodatage
  - Source du déclencheur (fixée à `SLACK_INTENT`)
  - Titre de l'action réalisée
  - Statut de complétion
- [x] Écrire la fonction d'initialisation automatique du schéma au démarrage
- [x] Écrire la fonction d'insertion d'une nouvelle tâche exécutée
- [x] Écrire la fonction de récupération des dernières tâches enregistrées pour l'affichage

---

## Phase 4 : Client Cognitif Meta Muse & Fallback

- [x] Rédiger les instructions système (System Prompt) orientées Pilier 1 :
  - Rôle : orchestrateur silencieux qui prépare une réponse claire et professionnelle
  - Format attendu : JSON strict contenant la notification push, le titre de tâche et le corps du brouillon
- [x] Créer la fonction d'envoi de requête POST vers l'endpoint Meta Muse
- [x] Mettre en place un mécanisme de réponse locale préformatée (fallback) en cas d'absence de clé API ou de coupure réseau

---

## Phase 5 : Sentinelle Silencieuse Spécialisée Slack

- [x] Implémenter la détection de la fenêtre active sous macOS via AppleScript
- [x] Mettre en place la boucle d'observation en tâche de fond (thread séparé)
- [x] Définir la règle de filtrage d'intention :
  - Détecter les notifications émises par Slack ou le navigateur web (`NotificationSensor`)
  - Surveiller les nouveaux textes copiés dans le presse-papiers
  - Appliquer un délai de temporisation (cooldown) pour éviter les doublons
- [x] Connecter le déclencheur à l'appel du worker en arrière-plan

---

## Phase 6 : Worker d'Arrière-Plan & Notifications Natives

- [x] Créer la fonction de notification native macOS via AppleScript
- [x] Configurer l'exécution asynchrone du traitement :
  - Signaler à l'interface graphique que V.E.R.S.O. traite l'intention
  - Interroger Meta Muse pour obtenir la proposition de réponse
  - Écrire le fichier de livrable Markdown (`SLACK_DRAFT.md`) dans le dossier `deliverables/`
  - Sauvegarder la trace de l'opération dans la base SQLModel
  - Déclencher la notification push annonçant la disponibilité du brouillon
  - Réinitialiser l'indicateur d'activité de l'interface

---

## Phase 7 : Interface Utilisateur Flet (Vue Compagnon)

- [x] Configurer la fenêtre Flet en mode sombre et format compact
- [x] Ajouter le bouton de bascule pour démarrer ou suspendre la sentinelle Slack
- [ ] Ajouter l'indicateur d'état en direct (icône ou anneau animé + message textuel)
- [ ] Ajouter la liste dynamique affichant l'historique des intentions Slack traitées
- [ ] Implémenter le rafraîchissement automatique de la liste dès qu'une tâche se termine

---

## Phase 8 : Validation & Démonstration

- [ ] Lancer l'application Flet et activer la surveillance
- [ ] Ouvrir Slack, copier un message reçu appelant une réponse
- [ ] Vérifier la réception de la notification push sans interaction clavier/souris supplémentaire
- [ ] Vérifier la génération correcte du fichier `deliverables/SLACK_DRAFT.md`
- [ ] Vérifier l'ajout instantané de la ligne dans l'historique de l'interface Flet