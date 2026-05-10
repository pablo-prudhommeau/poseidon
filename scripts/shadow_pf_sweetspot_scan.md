# Shadow PF sweet-spot scan

Documentation du script [`shadow_pf_sweetspot_scan.py`](shadow_pf_sweetspot_scan.py) : exploration systématique de **niches statistiques** (golden niches) et de **pistes de gate** à partir de l’historique des **verdicts shadow**, en comparant deux régimes définis par la **SMA du profit factor** (PF) sur buckets chronicle.

---

## Table des matières

1. [Objectif](#objectif)
2. [Prérequis d’exécution](#prérequis-dexécution)
3. [Artefacts de sortie (`logs/` et `csv/`)](#artefacts-de-sortie-logs-et-csv)
4. [Modèle analytique](#modèle-analytique)
5. [Les métriques (pentaptyque verdict × 2 + pentaptyque SMA)](#les-métriques-pentaptyque-verdict--2--pentaptyque-sma)
6. [Tri et filtres (`--rank-by`, `--min-regime-*`)](#tri-et-filtres)
7. [Référence CLI](#référence-cli)
8. [Configurations d’exploration recommandées](#configurations-dexploration-recommandées)
9. [Lecture d’une niche « golden »](#lecture-dune-niche-golden)

---

## Objectif

Le script balaie une grille de paramètres :

`lookback (jours) × granularité de bucket (secondes) × période SMA × seuil sur la SMA(PF))`

Pour chaque combinaison, il calcule des métriques **par régime** (SMA au-dessus du seuil vs au niveau ou en dessous) et des métriques **sur la série SMA / PF brut** de la fenêtre. L’usage typique est de repérer des combinaisons où le régime « chaud » se distingue du « froid » sur des critères économiques ou de robustesse, **sans présumer de causalité** avec la stratégie de trading réelle.

---

## Prérequis d’exécution

| Élément | Détail |
|---------|--------|
| Racine du dépôt | Répertoire contenant `backend/`, `scripts/`, `.venv`, `.env`. |
| Variables d’environnement | Fichier **`.env`** à la racine du dépôt (voir chemins relatifs ci-dessous). |
| Interpréteur | **Toujours** le Python du projet : **`.venv`** à la racine — ne pas utiliser un Python système ou un autre venv. |
| Base de données | Les paramètres de connexion attendus par l’application (ex. `DATABASE_URL`) doivent être présents dans `.env`. |
| Imports Python | Le script ajoute `backend/` au `sys.path` pour les modules `src.*`. Si `ModuleNotFoundError: No module named 'src'`, définir `PYTHONPATH` sur le répertoire **`backend`** (parent du package `src`), pas `backend/src`. |

### Chemins depuis `scripts/` (pour agents et CLI)

Le script vit dans **`scripts/shadow_pf_sweetspot_scan.py`**. La racine du repo est le **parent** de `scripts/` ; le code charge `load_dotenv(ROOT / ".env")` où `ROOT` est cette racine.

| Ressource | Depuis la racine du dépôt | Depuis le dossier `scripts/` |
|-----------|---------------------------|-------------------------------|
| Environnement virtuel | `.venv` | **`../.venv`** |
| Fichier d’environnement | `.env` | **`../.env`** |

**Exécution typique (racine du repo)** — Windows :

```powershell
cd <racine-poseidon>
.\.venv\Scripts\python.exe scripts/shadow_pf_sweetspot_scan.py --help
```

**Exécution depuis `scripts/`** (même interpréteur, même `.env` chargé par le script) :

```powershell
cd <racine-poseidon>\scripts
..\.venv\Scripts\python.exe shadow_pf_sweetspot_scan.py --help
```

Sous Unix (bash) : depuis la racine, `.venv/bin/python scripts/shadow_pf_sweetspot_scan.py` ; depuis `scripts/`, **`../.venv/bin/python shadow_pf_sweetspot_scan.py`**.

Ne pas placer une copie du `.env` dans `scripts/` : le fichier attendu est **`../.env`** par rapport à `scripts/` (fichier unique à la racine).

---

## Artefacts de sortie (`logs/` et `csv/`)

Convention du dépôt pour garder le dépôt **propre** et un `.gitignore` localisé :

| Type | Emplacement | Comportement du script |
|------|-------------|-------------------------|
| **Journaux** | [`scripts/logs/`](logs/) | À chaque exécution, un fichier horodaté est créé : `shadow_pf_sweetspot_scan_YYYYMMDD_HHMMSS.log`. Les messages `INFO` du sweep y sont **dupliqués** (sortie console + fichier). Désactiver avec `--no-log-file` (CI, environnement en lecture seule, etc.). |
| **CSV** | [`scripts/csv/`](csv/) | Si `--csv` est un **simple nom de fichier** (ex. `run.csv`), le fichier est écrit dans **`scripts/csv/run.csv`**. Les chemins absolus ou relatifs avec répertoires (ex. `exports/run.csv` depuis le répertoire courant) sont résolus normalement ; les répertoires parents sont créés si nécessaire. |

Ces dossiers sont listés dans [`scripts/.gitignore`](.gitignore) (`logs/` et `csv/`). Ils peuvent être absents du clone jusqu’à la première exécution ; le script les crée au besoin.

---

## Modèle analytique

1. Construction d’une série **sparse** de PF par bucket (alignée sur la logique chronicle : agrégation des verdicts par bucket, PF bucket via `_compute_profit_factor`).
2. Option **winsorize** sur cette série (comme le chart), puis **SMA** (`--sma-periods`).
3. Pour chaque verdict résolu, rattachement au bucket temporel ; lecture de la **SMA(PF)** de ce bucket.
4. **Partition** :
   - **Au-dessus du seuil** : `SMA(PF) > seuil`
   - **Au niveau ou en dessous** : `SMA(PF) ≤ seuil`
5. Agrégation des métriques **verdict** dans chaque régime ; agrégation **série** sur les buckets de la fenêtre (métriques « côté SMA / PF brut »).

Les **deltas** entre régimes (`*_delta`) servent au tri et à la comparaison « gate » entre monde chaud et monde froid.

---

## Les métriques (pentaptyque verdict × 2 + pentaptyque SMA)

### Verdicts — cinq métriques par régime (`_above` / `_below`)

| Concept | Colonnes | Description courte |
|---------|----------|--------------------|
| PnL moyen | `avg_pnl_*_usd` | Moyenne des PnL réalisés dans le régime (espérance empirique sur l’échantillon). |
| Taux de gain | `win_rate_*` | Proportion de verdicts marqués gagnants selon le modèle ORM. |
| PF réalisé | `empirical_pf_*` | Agrégat type gross profit / gross loss du régime. |
| Vélocité | `velocity_*_per_day` | `nombre de verdicts dans le régime / lookback_days`. |
| Payoff | `payoff_ratio_*` | (PnL moyen des trades gagnants) / ( \|PnL moyen des trades perdants\| ). |

### Série (côté SMA / PF brut de la fenêtre) — cinq champs

| Colonne | Description |
|---------|-------------|
| `sma_series_mean` | Moyenne de la ligne SMA sur les buckets de la fenêtre. |
| `sma_series_std` | Écart type de la ligne SMA. |
| `sma_time_fraction_above_threshold` | Fraction des buckets où `SMA > seuil` (le seuil est celui de la ligne du tableau). |
| `raw_pf_mean_when_sma_above_threshold` | Moyenne du **PF brut de bucket** lorsque la SMA est au-dessus du seuil. |
| `raw_pf_mean_when_sma_at_or_below_threshold` | Idem lorsque la SMA est au niveau ou en dessous. |

### Deltas entre régimes

`avg_pnl_delta_usd`, `win_rate_delta`, `empirical_pf_delta`, `velocity_delta_per_day`, `payoff_ratio_delta`.

### Colonnes d’identification du sweep

`lookback_days`, `bucket_seconds`, `sma_period`, `pf_threshold`, `winsorize`, `sparse_buckets`, `verdicts_above`, `verdicts_below`.

---

## Tri et filtres

### `--rank-by`

| Valeur | Usage |
|--------|--------|
| `win_rate_delta` | Priorité au **tri qualitatif** (écart de win rate entre régimes). |
| `avg_pnl_delta` | Priorité à l’**écart de PnL moyen** entre régimes. |
| `empirical_pf_delta` | Priorité à l’**écart de PF réalisé** entre régimes. |
| `payoff_ratio_delta` | Priorité au **payoff** (taille des gains vs pertes). |
| `velocity_above` | Priorité au **débit** de verdicts dans le régime au-dessus du seuil (à interpréter avec prudence selon le lookback). |
| `composite` | Ordre lexicographique multi-critères (compromis exploratoire). |

### `--min-regime-n` / `--min-regime-below-n`

Filtrent les lignes exportées : effectifs minimums dans le régime au-dessus du seuil et, optionnellement, dans le régime en dessous. Augmente la **robustesse statistique** au prix d’une grille plus clairsemée.

---

## Référence CLI

```text
python scripts/shadow_pf_sweetspot_scan.py --help
```

| Argument | Défaut | Rôle |
|----------|--------|------|
| `--lookbacks` | `7,14,30` | Fenêtres en jours (liste séparée par virgules). |
| `--granularities` | `300,900,1800` | Largeur du bucket en secondes (`300` = 5 min). |
| `--sma-periods` | `10,30,50,100,200` | Périodes SMA sur la série PF sparse. |
| `--thresholds` | voir `--help` | Seuils sur la **SMA(PF)** pour couper les régimes. |
| `--no-winsorize` | désactivé | Désactive la winsorisation avant SMA. |
| `--min-regime-n` | `50` | Effectif minimum — régime au-dessus du seuil. |
| `--min-regime-below-n` | `0` | Effectif minimum — régime en dessous (`0` = pas de filtre). |
| `--rank-by` | `win_rate_delta` | Clé de tri des lignes imprimées / CSV. |
| `--csv` | — | Export CSV ; nom seul → `scripts/csv/<nom>`. |
| `--no-log-file` | — | Ne pas écrire de fichier dans `scripts/logs/`. |

---

## Configurations d’exploration recommandées

Toutes les commandes ci-dessous supposent que le répertoire courant est la **racine du dépôt**, avec **`python` = interpréteur du `.venv`** (voir [Prérequis — chemins depuis `scripts/`](#chemins-depuis-scripts-pour-agents-et-cli)). Préfixez par `.\.venv\Scripts\python.exe` sous Windows ou `.venv/bin/python` sous Unix si `python` n’est pas déjà ce venv.

Les journaux partent dans `scripts/logs/` ; utilisez `--csv <nom>.csv` pour écrire sous `scripts/csv/`.

Si vous exécutez **depuis `scripts/`**, remplacez `python scripts/shadow_pf_sweetspot_scan.py` par **`..\.venv\Scripts\python.exe shadow_pf_sweetspot_scan.py`** (Windows) ou **`../.venv/bin/python shadow_pf_sweetspot_scan.py`** (Unix).

### 1 — Large sweep « split signal » (win rate)

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 7,14 \
  --granularities 300,900 \
  --sma-periods 50,100 \
  --thresholds 1.35,1.45,1.55 \
  --min-regime-n 30 \
  --rank-by win_rate_delta \
  --csv win_rate_delta.csv
```

### 2 — Espérance / PnL moyen (delta entre régimes)

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 14,21,30 \
  --granularities 300 \
  --sma-periods 30,50,80 \
  --thresholds 1.2,1.35,1.5 \
  --min-regime-n 40 \
  --min-regime-below-n 40 \
  --rank-by avg_pnl_delta \
  --csv avg_pnl_delta.csv
```

### 3 — Vélocité du régime « au-dessus du seuil »

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 7 \
  --granularities 300,600 \
  --sma-periods 40,60 \
  --thresholds 1.4,1.45,1.5 \
  --min-regime-n 25 \
  --rank-by velocity_above \
  --csv velocity_above.csv
```

**Note** : la vélocité est normalisée par `lookback_days` ; les lookbacks courts produisent des ratios plus élevés **pour la même intensité** — comparer surtout **à lookback fixe**.

### 4 — Robustesse du PF réalisé (régime)

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 14,30 \
  --granularities 300 \
  --sma-periods 50,100 \
  --thresholds 1.3,1.45,1.6 \
  --min-regime-n 35 \
  --min-regime-below-n 35 \
  --rank-by empirical_pf_delta \
  --csv empirical_pf_delta.csv
```

### 5 — Payoff (buckets plus larges)

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 14 \
  --granularities 900 \
  --sma-periods 40,80 \
  --thresholds 1.35,1.5 \
  --min-regime-n 40 \
  --rank-by payoff_ratio_delta \
  --csv payoff_ratio_delta.csv
```

### 6 — Sensibilité sans winsor + compromis composite

```bash
python scripts/shadow_pf_sweetspot_scan.py \
  --lookbacks 14 \
  --granularities 300 \
  --sma-periods 50 \
  --thresholds 1.35,1.4,1.45,1.5 \
  --rank-by composite \
  --no-winsorize \
  --csv composite_no_winsor.csv
```

---

## Lecture d’une niche « golden »

1. **Ne pas confondre** le critère de tri (`--rank-by`) avec une « vérité » unique : une ligne dominante sur `velocity_above` peut être faible sur `avg_pnl_delta`.
2. **Stabilité** : tester des seuils et des SMA voisins ; une niche qui disparaît avec de petites variations est fragile.
3. **Alignement produit** : les paramètres explorés doivent correspondre à ceux affichés ou utilisés dans la **chronicle** (lookback, granularité, winsor, SMA) si l’objectif est un gate cohérent avec l’UI.
4. **Limite statistique** : résultats observés sur **historique shadow** ; toute généralisation à du trading réel ou à du papier nécessite validation supplémentaire.


---

## Fichiers associés

| Fichier | Rôle |
|---------|------|
| [`shadow_pf_sweetspot_scan.py`](shadow_pf_sweetspot_scan.py) | Implémentation du sweep. |
| [`.gitignore`](.gitignore) | Ignore `logs/` et `csv/`. |
