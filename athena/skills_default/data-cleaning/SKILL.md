---
description: Systematic data cleaning before analysis, with auditable transformations
name: data-cleaning
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Data Cleaning

Disciplined approach to cleaning a dataset before downstream
analysis. Distinct from [[data-exploration]] — EDA characterizes
what's there; cleaning decides what to do about it. The premise:
data cleaning is where most analytical mistakes are seeded, because
it's where assumptions get baked in and never revisited.

## When to use this skill

Use after EDA, before modeling / aggregation / claims. Skip when the
dataset is already known-clean (you've cleaned it before in this
session or downstream of a vetted pipeline).

## The cleaning protocol

### 1. Snapshot the raw data

Before any transformation:

```python
df_raw = df.copy()
df_raw.to_parquet("data_raw_snapshot.parquet")
```

Every transformation downstream is reversible because the raw is
preserved. When a stakeholder asks "did you drop the rows with
negative values?", you can re-derive and check.

### 2. Build a transformation log

Every transformation gets recorded as you go:

```python
log = []
def step(name, fn):
    before = len(df)
    fn()
    after = len(df)
    log.append({"step": name, "rows_before": before, "rows_after": after})

step("drop nulls in id", lambda: df.dropna(subset=["id"], inplace=True))
step("clip outliers in price", lambda: df.assign(price=df.price.clip(0, 1e6)))
```

At the end, ``log`` reads like a recipe. Anyone can re-derive your
cleaned dataset from raw + log. (For production pipelines, this log
becomes the actual ETL code.)

### 3. The cleaning categories

Address each category explicitly. Don't skip — silent skips are how
bad assumptions hide.

#### Missing values

For each column with nulls:

- **Drop the row?** Justified if the column is essential AND nulls
  are a small fraction.
- **Fill with a default?** Justified if there's a domain-defined
  default (zero, "unknown", median).
- **Mark and keep?** Add a ``<col>_is_null`` indicator and keep the
  row. Often the right answer — the fact of missingness can be
  signal.

Whichever you choose, the choice goes in the log. Default-filling
without recording it is how silent bias enters models.

#### Duplicates

```python
dupes = df[df.duplicated(subset=["id"], keep=False)]
```

For each duplicate cluster: are they truly duplicates (drop) or
legitimate repeated observations (keep with an order field)?

#### Type coercions

Strings that should be dates, numbers in object columns, booleans
encoded as 0/1/null. Coerce explicitly:

```python
df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
n_failed = df["ts"].isna().sum()
log.append({"step": "coerce ts to datetime",
            "failures": int(n_failed)})
```

The ``errors="coerce"`` + count-the-NaTs pattern is the right
default. Silent ``errors="ignore"`` hides parse failures.

#### Outliers

Decide upfront: are these errors (clip or drop) or rare-but-real
(keep)? Heavy-tailed distributions (revenue, view counts) almost
always have real outliers — clipping them destroys signal. Recording
errors (sensor glitches, scraping artifacts) usually need dropping.

#### Categorical canonicalization

```python
df["country"] = df["country"].str.strip().str.upper()
df["country"] = df["country"].replace({"USA": "US", "U.S.": "US"})
```

Without this step, ``"US"``, ``"USA"``, ``"U.S.A."``, ``"us"`` are
four different countries to your group-by.

#### Time zones

If timestamps come from multiple sources, normalize to UTC at the
boundary. Mixing naive and aware datetimes is the single most common
source of off-by-N-hours bugs.

### 4. Validation gates

After cleaning, assert invariants you expect to hold:

```python
assert df["id"].notna().all(), "id should never be null after cleaning"
assert df["ts"].between(START, END).all(), "ts out of expected range"
assert (df["price"] >= 0).all(), "negative prices should be cleaned"
assert len(df) > 0, "cleaning shouldn't drop ALL rows"
```

Asserts are documentation that runs. When a future pipeline run
violates them, you find out at the cleaning step, not three layers
downstream when the model produces garbage.

## What NOT to do in cleaning

- **Imputation of the target variable**: filling missing labels with
  predictions guarantees a self-fulfilling-prophecy model.
- **Cleaning the test set with statistics from the train set's mean**
  — actually, do exactly this; the inverse leaks the test distribution
  into training. Worth re-checking the direction each time.
- **Aggressive duplicate dropping without checking the keep-first vs
  keep-last semantics** — order matters when records have timestamps.
- **Type coercion with silent failures** — always count and log the
  parse failures.

## When to STOP cleaning

When the cleaning log shows you've changed more than ~20% of rows or
~20% of cell values: STOP and reconsider. At that magnitude you're no
longer cleaning, you're synthesizing. Either accept the loss of
fidelity (and document it clearly) or fix the upstream data source.
