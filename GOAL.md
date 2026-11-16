<!--
SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
SPDX-License-Identifier: Apache-2.0
-->

# Goal prompt for the next agent

Written in French on purpose: it is the owner's own prompt, to paste as the
goal of a new session (`/goal`). Read [`HANDOFF.md`](./HANDOFF.md) for the state
it refers to. Edit the prompt freely; keep its limits and checkpoints.

## Prompt

```text
Tu reprends le projet Lexis (dépôt julienawonga/lexis). C'est un moteur
text-to-SQL d'entreprise : un backend FastAPI (auto_ontology/), un frontend
Next.js (frontend/), un service d'ingestion, Postgres avec pgvector.

Lis d'abord, dans cet ordre : CLAUDE.md, HANDOFF.md, docs/evaluation.md,
docs/verification-status.md, docs/experiments.md, la section Roadmap du
README.md. Ne commence pas à coder avant d'avoir fini cette lecture.

OBJECTIF
Rendre le moteur et le frontend robustes et réellement opérationnels, pas
seulement qui passent les tests. Tu identifies les limites avec des preuves,
tu corriges les plus graves, tu améliores l'évaluation, puis tu avances la
roadmap dans l'ordre du README.

"Opérationnel" veut dire, et tu le prouves point par point :
- Déploiement : un chemin documenté et testé pour installer de zéro, des
  contrôles de santé, des erreurs claires, pas de plantage sous la limite de
  charge (8 chats simultanés en local), sauvegarde et restauration documentées.
- Sécurité : l'authentification de l'API (jeton interne) essayée en direct,
  le SQL des agents toujours en lecture seule et plafonné.
- Frontend : les parcours principaux (connexion, connexion d'une base,
  ingestion, chat, clarification, page Terms, cartes d'exploration) sans
  erreur, avec des états de chargement, d'erreur et de vide corrects. Build,
  lint et tests au vert.
- Moteur : les limites connues (HANDOFF.md, "Known limits") traitées ou
  expliquées, un refus propre quand une question n'a pas de réponse, jamais
  une réponse silencieusement à côté.

PHASES (avec point d'arrêt à la fin de chacune)
0. Audit en lecture seule. Livrable : docs/audit-<date>.md, la liste des
   limites du moteur et du frontend, chacune avec sa preuve (log, test,
   mesure, capture), sa gravité et son coût de correction. Aucun code produit.
   ARRÊTE-TOI et présente le résultat au propriétaire avant la phase 1.
1. Opérationnel : déploiement, santé, erreurs, charge, authentification en
   direct, parcours du frontend. Demande l'accord avant de redémarrer la pile.
2. Robustesse du moteur : une cause à la fois, une petite PR par correction,
   chaque changement de ce que voit le modèle passe la barrière d'évaluation
   de CLAUDE.md (ACCEPT exigé).
3. Évaluation : amener dans le dépôt le protocole qui gère les conversations
   (aujourd'hui il est hors dépôt dans HomeLab/lexis-evals/clarification),
   ajouter des jeux gelés sur d'autres bases, réduire le bruit (répétitions,
   tests appariés), garder un historique de régression, mesurer les questions
   sans réponse.
4. Roadmap : les étapes 5, 7, 8, 9, 10, 11, 12 du README, dans l'ordre. L'étape
   6 (vraies questions du propriétaire) est bloquée : il n'en a pas.

RÈGLES NON NÉGOCIABLES
- Ne fusionne rien sans l'accord explicite du propriétaire, PR par PR.
  Aucune action destructive (downgrade Alembic, restauration de base,
  suppression de dossiers ou de branches non fusionnées) sans demande.
- Une PR n'est finie que si toute la CI est verte : attends-la, corrige,
  rends compte honnêtement. Utilise toujours gh --repo julienawonga/lexis.
- Honnêteté : dis ce qui est vérifié et ce qui ne l'est pas (niveaux de
  docs/verification-status.md). Ne rends jamais une affirmation plus forte
  que la preuve. Si un critère échoue, tu le consignes, tu ne l'assouplis pas.
- Évaluation stricte : fige les cas avant de mesurer, jamais de question,
  valeur attendue ou littéral de jeu d'évaluation dans le code, les prompts ou
  les ressources (python -m dev_tools.integrity le vérifie).
- Ne règle aucune constante (seuil, taille) sur Chinook, Pagila ou LiveSQLBench
  sans le dire noir sur blanc : ces bases sont publiques et ne prouvent rien
  sur les données d'une entreprise. Les gains doivent venir de mécanismes, pas
  de réglages sur un jeu.
- Consigne chaque expérience, échecs compris, dans docs/experiments.md.
- Un changement qui traverse la frontière worker puis serveur doit avoir un
  essai en direct sur la pile, pas seulement des tests avec doublures.
- Annonce le coût (temps, appels au modèle) et ce que ça va apprendre avant
  tout protocole de plus de 15 minutes. Évite les mesures qui n'aident pas à
  décider.
- Ne jamais afficher le contenu de .env. Travaille dans des worktrees
  (.claude/worktrees/), pas en changeant la branche du dossier principal.
- Réponds au propriétaire en français simple et court. Code, commits et
  documentation restent en anglais.

CE QUE TU NE PEUX PAS RÉSOUDRE SEUL (dis-le au lieu de le contourner)
- Il n'y a pas de vraies questions ni de vraies données d'entreprise : toute
  mesure actuelle vient de bases publiques.
- Le bruit entre deux passes identiques est d'environ 4 points sur 180
  questions LiveSQLBench : une petite différence n'est pas un résultat.
- Les mesures complètes coûtent des heures de modèle et de machine.

FIN D'UNE ÉTAPE
Pour chaque PR : ce qui change, ce qui a été vérifié et comment, ce qui ne
l'est pas, le résultat de la CI, et ta recommandation (fusionner ou non).
```
