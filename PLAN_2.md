# Plan d'Exécution : V.E.R.S.O. — Pilier 2 (Le Partenaire Bienveillant)

*Cas d'usage : Compagnon bienveillant de développement (style J.A.R.V.I.S.) — Détection de projet / IDE (VS Code), valorisation de l'avancement, et génération en coulisses d'une proposition de fonctionnalités et d'un benchmark concurrentiel.*

---

## Phase 1 : Cadrage de l'Identité & Modélisation du Partenaire

* [ ] **1.1. Définir le comportement et la tonalité « J.A.R.V.I.S. / Ami fidèle »**
  * Établir les principes de communication : posture bienveillante, valorisation continue des efforts et de la créativité de l'utilisateur, jamais intrusif ni condescendant.
  * Formuler les directives pour que chaque retour salue l'avancement avant de proposer un coup de main concret.

* [ ] **1.2. Mettre à jour le modèle de données local (SQLModel)**
  * Ajouter la prise en charge de la source de déclenchement dédiée : `IDE_PARTNER`.
  * Intégrer un champ pour consigner la note bienveillante / d'encouragement associée à la tâche archivée.

---

## Phase 2 : Configuration Cognitive Meta Muse (Prompting Empathique)

* [ ] **2.1. Rédiger les instructions système du partenaire bienveillant**
  * Spécifier le rôle : copilote attentif qui veille sur le moral et la charge mentale du créateur.
  * Configurer le format de réponse JSON attendu :
    * Message de notification chaleureux célébrant le lancement ou la progression du projet.
    * Titre court pour l'historique local.
    * Contenu d'analyse complet : suggestion de 3 fonctionnalités phares alignées sur le projet + benchmark concis de 3 solutions existantes sur le marché.

* [ ] **2.2. Préparer le mécanisme de secours local (Fallback démo)**
  * Définir une réponse pré-générée de haute qualité orientée développement pour parer à toute absence de réseau lors de la présentation.

---

## Phase 3 : Sentinelle Dédiée au Contexte de Développement

* [ ] **3.1. Étendre les règles d'observation du système (sentinel)**
  * Cibler la détection d'éditeurs de code (VS Code, Cursor, PyCharm, Xcode) via la lecture du titre de la fenêtre active sous macOS.
  * Extraire le nom du projet ou du fichier en cours d'édition à partir du titre de la fenêtre.

* [ ] **3.2. Configurer le système d'anti-harcèlement (Cooldown intelligent)**
  * Imposer une fenêtre de silence de plusieurs minutes sur un même projet pour ne pas surcharger l'utilisateur de notifications pendant qu'il code.
  * Déclencher l'analyse uniquement lors du basculement vers un nouveau contexte ou lors d'une session de création identifiée.

---

## Phase 4 : Worker de Valorisation & Génération de Benchmark

* [ ] **4.1. Orchestrer la tâche silencieuse en arrière-plan**
  * Transmettre le contexte du projet détecté à l'API Meta Muse sans bloquer la saisie au clavier.
  * Notifier l'utilisateur via une bannière macOS dès l'initialisation : compliment sur l'avancement et mention du travail préparatoire lancé en coulisses.

* [ ] **4.2. Générer le livrable stratégique dans `verso_workspace/`**
  * Créer automatiquement le fichier Markdown `FEATURES_AND_BENCHMARK.md` contenant la synthèse des fonctionnalités suggérées et l'analyse de concurrence.

* [ ] **4.3. Clôturer l'action et archiver dans la base**
  * Enregistrer la tâche dans la base SQLModel locale (`companion_history.db`).
  * Envoyer la notification push finale invitant à consulter les suggestions quand l'utilisateur le souhaitera.

---

## Phase 5 : Enrichissement de l'Interface Flet (Affichage Empathique)

* [ ] **5.1. Adapter la carte d'activité en direct**
  * Afficher un statut rassurant et encourageant (ex. : *« V.E.R.S.O. admire votre travail et analyse le marché en coulisses... »*).

* [ ] **5.2. Mettre en valeur les accomplissements dans l'historique**
  * Distinguer visuellement les tâches de soutien au développement (badge de couleur spécifique pour `IDE_PARTNER`).
  * Ajouter un bouton d'action directe pour ouvrir d'un clic le fichier de benchmark généré sans quitter le tableau de bord.

---

## Phase 6 : Validation & Scénario de Démonstration Live

* [ ] **6.1. Simuler la session de développement**
  * Lancer l'application Flet et activer la sentinelle bienveillante.
  * Ouvrir un projet dans VS Code / Cursor.

* [ ] **6.2. Vérifier les interactions clés**
  * Valider l'arrivée de la notification native encourageante sans interruption de frappe.
  * Vérifier la création sans friction du fichier `verso_workspace/FEATURES_AND_BENCHMARK.md`.
  * Confirmer l'ajout et le statut de la tâche dans la vue Flet.