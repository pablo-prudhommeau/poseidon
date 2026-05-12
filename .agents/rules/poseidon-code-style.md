---
trigger: always_on
---

Pour chaque portion de code générée, je souhaiterai que tu te mettes dans un mindset de développeur très expérimenté afin de te préparer à un potentiel audit de code extrêmement sérieux :  

* Tu dois homogénéiser et améliorer l'ensemble des nommages (variables, méthodes, etc.) afin d'avoir des noms limpides, sans AUCUNE abréviations, et parfaitement lisibles, et cohérents dans tous le code. Tu peux exceptionnellement utiliser avec parcimonie des acronymes ultra mainstream (DCA, PnL, DB, DAO, etc.)

* Pour les fichiers TypeScript frontend, respecte strictement le schéma `<nom>.<type>.ts` avec un suffixe qui décrit la responsabilité dominante du fichier (`component`, `service`, `builder`, `formatter`, `adapter`, `models`, `utils`, etc.).

* Tu dois bannir toute forme de commentaire quels qu'ils soient (`# ...", docstrings `"""`, `/**`, etc.) qui sont complètement inutiles car le code est autoporteur de l'information si il est bien écrit avec des nommages explicites

* Tu dois homogénéiser l'ensemble des phrases de log, et tu dois t'assurer d'avoir à la fois du logging "info" et du logging "verbose" dans les endroits clés, en gardant un niveau de log décent et en gardant une cohérence dans toute la codebase

* Les phrases de logging doivent utiliser des tags en préfixes [TAG1][...][TAGN][...] en gardant une cohérence dans toute la codebase

* Ces règles de logging exhaustives ne s'appliquent évidemment pas côté frontend, pas de console.log(...)

* Tout le code doit être évidemment en anglais  

* Tu ne dois pas indenter artificiellement les affectations de variables pour les aligner

* Évite l'utilisation de `*` / `*args` / `**kwargs` / `Any` qui rendent le code faussement modulaire et illisible

* En TypeScript, explicite systématiquement les types via `: Type` sur les paramètres, les retours de fonctions, les propriétés de classe, et toute variable intermédiaire dont le type n'est pas immédiatement trivial. Tu ne dois pas t'appuyer sur une inférence implicite pour `[]`, `{}`, `null`, `undefined`, `Map`, `Set`, `Promise`, `signal`, `computed`, les objets littéraux structurants, ni sur des callbacks exportés ou publics. Un typage implicite qui affaiblit la structure du code est interdit.

* Privilégie les appels de fonctions avec arguments nommés (`object.function(argument_name=value)`) uniquement quand cela améliore clairement la lisibilité (booléens, paramètres optionnels, plusieurs paramètres du même type, valeurs numériques sans unité explicite). Conserve les appels positionnels pour les APIs courtes et idiomatiques (`append`, `min`, `max`, signatures évidentes).

* Privilégie l'utilisation de structure typées via BaseModel plutôt que des `dict` / `Tuple` / `Mapping` de types primitifs et n'utilise pas de dict.get() ni de dict["..."] ni de getattr() pour récupérer les attributs des structures (`structure.attribute` plutôt que `structure.get("attribute")` ou `structure["attribute"]`)

* Ces structures typées backend doivent être regroupées dans des `*_structures.py` par "module applicatif"

* Ne retype pas inutilement des types déjà établis float() d'un float, int() d'un int, etc.

* N'affecte pas de manière hasardeuse des valeurs par défaut `0`, `""`, utilise proprement `Optional` ou throw des exceptions

* L'ensemble des dates gérées dans l'application doivent utiliser la timezone locale système (et non UTC). 

* Assure-toi systématiquement que les comparaisons et soustractions de dates tiennent compte des pertes potentielles d'offset (offset-naive) souvent causées par SQLite, en garantissant que les dates réhydratées soient explicitement converties en offset-aware local via un utilitaire adéquat.

* Tu dois proscrire la typographie "Title Case" (majuscule à chaque mot) dans les wordings côté frontend, mais garder une majuscule initiale au premier mot

* Lorsque tu `except` une exception, tu dois utiliser logger.exception pour pouvoir afficher la stacktrace