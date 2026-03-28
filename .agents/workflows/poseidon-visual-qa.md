---
description: Workflow de QA visuelle autonome
---

**Contexte d'Exécution (CRITIQUE)**
Le backend Python (FastAPI sur port 8000) et le frontend Angular (port 4200) tournent DÉJÀ en arrière-plan sur ma machine avec le rechargement à chaud (Hot-Reload) activé.
* Règle absolue 1 : Ne tente JAMAIS d'ouvrir un terminal pour démarrer, arrêter ou redémarrer les serveurs. 
* Règle absolue 2 : Ne gère aucune base de données ni variable d'environnement. Tout est géré en externe.
Ton SEUL rôle est de modifier le code et d'utiliser le navigateur pour valider le résultat.

**Validation Visuelle Autonome (À exécuter après chaque modification de code)**
1. Une fois tes modifications sauvegardées, le Hot-Reload externe va recompiler l'application. Attends simplement 2 ou 3 secondes.
2. Utilise ton outil 'Browser' (Ghost Browser) en mode 'Always Proceed'.
3. Ouvre un onglet interne sur `http://localhost:4200/` (ou navigue vers la route spécifique que tu viens de modifier).
4. Prends une capture d'écran du rendu final et affiche-la moi dans le chat pour validation.
5. Audit de qualité : Signale impérativement TOUTE erreur présente dans la console JavaScript du navigateur, ou toute erreur réseau (HTTP 500) provenant du backend lors du chargement de la page.