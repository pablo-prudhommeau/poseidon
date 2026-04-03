---
trigger: always_on
---

Pour chaque portion de code générée, je souhaiterai que tu te mettes dans un mindset de développeur très expérimenté afin de te préparer à un potentiel audit de code extrêmement sérieux :  

* Tu dois homogénéiser et améliorer l'ensemble des nommages (variables, méthodes, etc.) afin d'avoir des noms limpides, sans AUCUNE abréviations, et parfaitement lisibles, et cohérents dans tous le code. Tu peux exceptionnellement utiliser avec parcimonie des acronymes ultra mainstream (DCA, PnL, DB, DAO, etc.)

* Tu dois bannir toute forme de commentaire quels qu'ils soient (`# ...", docstrings `"""`, `/**`, etc.) qui sont complètement inutiles car le code est autoporteur de l'information si il est bien écrit avec des nommages explicites

* Tu dois homogénéiser l'ensemble des phrases de log, et tu dois t'assurer d'avoir à la fois du logging "info" et du logging "verbose" dans les endroits clés, en gardant un niveau de log décent et en gardant une cohérence dans toute la codebase

* Les phrases de logging doivent utiliser des tags en préfixes [TAG1][...][TAGN][...] en gardant une cohérence dans toute la codebase

* Tout le code doit être évidemment en anglais  

* Tu ne dois pas indenter artificiellement les affectations de variables pour les aligner

* Évite l'utilisation de `*` / `*args` / `**kwargs` / `Any` qui rendent le code faussement modulaire et illisible

* Privilégie l'utilisation de structure typées via BaseModel plutôt que des `dict` / `Tuple` / `Mapping` de types primitifs et n'utilise pas de dict.get() ni de dict["..."] ni de getattr() pour récupérer les attributs des structures (`structure.attribute` plutôt que `structure.get("attribute")` ou `structure["attribute"]`)

* Ces structures typées backend doivent être regroupées dans des `*_structures.py` par "module applicatif"

* Ne retype pas inutilement des types déjà établis float() d'un float, int() d'un int, etc.

* N'affecte pas de manière hasardeuse des valeurs par défaut `0`, `""`, utilise proprement `Optional` ou throw des exceptions

* L'ensemble des dates gérées dans l'application doivent utiliser la timezone locale système (et non UTC)

* Lorsque tu `except` une exception, tu dois utiliser logger.exception pour pouvoir afficher la stacktrace