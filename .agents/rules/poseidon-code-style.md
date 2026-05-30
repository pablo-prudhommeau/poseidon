---
trigger: always_on
---
# Introduction

Pour chaque portion de code générée, je souhaiterais que tu te mettes dans un mindset de développeur très expérimenté afin de te préparer à un potentiel audit de code extrêmement sérieux.

# Généralités
* Tu dois homogénéiser et améliorer l'ensemble des nommages (variables, méthodes, etc.) afin d'avoir des noms limpides, sans AUCUNE abréviations, et parfaitement lisibles, et cohérents dans tout le code. Tu peux exceptionnellement utiliser avec parcimonie des acronymes ultra mainstream (DCA, PnL, DB, DAO, etc.)
* Tu dois bannir toute forme de commentaire quels qu'ils soient (`# ...", docstrings `"""`, `/**`, etc.) qui sont complètement inutiles, car le code est autoporteur de l'information s'il est bien écrit avec des nommages explicites
* Tout le code doit être évidemment en anglais  
* Explicite systématiquement les types via `: type` sur les paramètres, les retours de fonctions, les propriétés de classe, et toute variable intermédiaire dont le type n'est pas immédiatement trivial. Tu ne dois pas t'appuyer sur une inférence implicite pour `[]`, `{}`, `null`, `undefined`, `Map`, `Set`, `Promise`, `signal`, `computed`, les objets littéraux structurants, ni sur des callbacks exportés ou publics. Un typage implicite qui affaiblit la structure du code est interdit.
* Tu dois produire des lignes de codes et des fichiers en respectant les conventions générales de `.editorconfig` (ex : `indent_size`, `end_of_line`, etc.)

# Backend (Python)
## Généralités
* Tu dois homogénéiser l'ensemble des phrases de log, et tu dois t'assurer d'avoir à la fois du logging "info" et du logging "verbose" dans les endroits clés, en gardant un niveau de log décent et en gardant une cohérence dans toute la codebase
* Les phrases de logging doivent utiliser des tags en préfixes [TAG1][...][TAGN][...] en gardant une cohérence dans toute la codebase
* Tu ne dois pas indenter artificiellement les affectations de variables pour les aligner
* Tu ne dois pas utiliser l'unpacking de dictionnaires (`**kwargs`), l'unpacking de listes (`*args`) ou le type `Any`, et donc instancier les objets et appeler tes fonctions en passant chaque paramètre explicitement, un par un.
* Privilégie les appels de fonctions avec arguments nommés (`object.function(argument_name=value)`) uniquement quand cela améliore clairement la lisibilité (booléens, paramètres optionnels, plusieurs paramètres du même type, valeurs numériques sans unité explicite). Conserve les appels positionnels pour les APIs courtes et idiomatiques (`append`, `min`, `max`, signatures évidentes).
* Privilégie l'utilisation de structure typée via BaseModel plutôt que des `dict` / `Tuple` / `Mapping` de types primitifs et n'utilise pas de dict.get() ni de dict["..."] ni de getattr() pour récupérer les attributs des structures (`structure.attribute` plutôt que `structure.get("attribute")` ou `structure["attribute"]`)
* Ne retype pas inutilement des types déjà établis float() d'un float, int() d'un int, etc.
* N'affecte pas de manière hasardeuse des valeurs par défaut `0`, `""`, utilise proprement `Optional` ou throw des exceptions
* L'ensemble des dates gérées dans l'application doivent utiliser la timezone locale système (et non UTC).
* Lorsque tu `except` une exception, tu dois utiliser logger.exception pour pouvoir afficher la stacktrace
* Place les imports (`import`, `from ... import ...`) en tête de fichier, regroupés selon les conventions du projet. N'utilise un import local à l'intérieur d'une fonction ou d'une méthode que lorsqu'il est indispensable pour éviter une dépendance circulaire avérée — jamais par convenance ou par habitude.

## Organisation du code
* Tu dois respecter une organisation et des nommages comme suit : \<NOM_MODULE\>\[\_\<NOM_SOUS_MODULE\>\]\_\[\<TYPE\>\].py où :
  * \<NOM_MODULE\> est le nom du module python (ex : `trading`, `dca`, `aavesentinel`, etc.)
  * \<NOM_SOUS_MODULE\> est le nom du sous-module python (ex : `shadowing`, `cortex`, etc.)
  * \<TYPE\> est le type du module / classe :
    * `service` pour les **modules** qui implémentent des fonctions métiers
    * `dao` pour les **classes** qui implémentent des Data Access Objects
    * `helpers` pour les **modules** qui fournissent des fonctions d'aide à l'implémentation métier, avec possibilité d'accès au DAO, avec notamment des fonctions de mapping de structure d'objets
    * `utils` pour les **modules** qui fournissent des fonctions utilitaires pures
    * `structures` pour les **modules** qui définissent des structures regroupées par module ou sous-module applicatif
* L'ensemble     

# Backend (SQLAchemy / Alembic)
* Tu ne dois en aucun cas utiliser l'idempotence dans les migrations SQLAchemy car nous nous appuyons sur le DDL transactionnel de PostgreSQL et le versioning strict d'Alembic.
* Tu dois utiliser des syntaxes compatibles SQLite et PostgreSQL.
* Tu dois utiliser un nom de fichier de migration au format `YYYYMMDDHHMMSS_<description>.py` avec une description respectant les conventions de nommage de migration SQLAchemy.

# Frontend (TypeScript, HTML, CSS)
* Respecte strictement le schéma `<nom>.<type>.ts` avec un suffixe qui décrit la responsabilité dominante du fichier (`component`, `service`, `builder`, `formatter`, `adapter`, `models`, `utils`, etc.).
* Tu dois proscrire la typographie "Title Case" (majuscule à chaque mot) dans les wordings côté frontend, mais garder une majuscule initiale au premier mot
* Après un chantier agentique IA, relance systématiquement `npm run format:prettier`, `npm run format:biome` puis `npm run lint` avant de considérer le travail comme livrable