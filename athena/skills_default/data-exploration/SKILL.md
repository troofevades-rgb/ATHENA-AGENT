---
description: Exploratory data analysis before modeling or claims
name: data-exploration
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Data Exploration

Disciplined exploratory data analysis. The premise: most ML and data-
science mistakes are upstream of the model — bad assumptions about
shape, distribution, leakage, or scope. EDA catches them cheap.

## When to use this skill

Use when the user hands you a dataset and asks ANY question about it —
even "just plot X." Run a quick EDA pass before you plot, model, or
make claims. Skip only for datasets you've previously characterized
in this session.

## The seven-question pass

Answer each, in order, before anything else.

### 1. What's the unit?

What does one row represent? Make this explicit. "One row = one
customer-month" vs "one row = one event" changes every subsequent
analysis. Print one row and read it field by field.

### 2. What's the shape?

```python
df.shape, df.dtypes, df.memory_usage(deep=True).sum()
```

- Row count, column count, dtypes, total memory
- If memory > 1 GB, decide now whether to subsample for exploration

### 3. What's missing?

```python
df.isna().mean().sort_values(ascending=False).head(20)
```

- Which columns are mostly null? Are they NULL-as-missing or
  NULL-as-meaningful (e.g., "no churn date" = active customer)?
- Are nulls clustered by time / segment? (Often signals data-collection
  changes.)

### 4. What's the distribution?

For numeric columns: ``df.describe()``. For categorical:
``df[col].value_counts(dropna=False).head(20)``.

Look for: heavy-tail (mean ≫ median), bimodality (two populations
masquerading as one), suspicious clean values (suspicious 0s, sentinel
99999s, all-same values).

### 5. What's the time axis?

If there's a timestamp:

```python
df.groupby(df.ts.dt.to_period('D')).size().plot()
```

- Coverage range. Gaps. Sudden jumps in volume (often signal a backfill
  or schema change).
- Does the dataset cross a known event (product launch, outage,
  policy change)? Note it.

### 6. What's correlated with what?

```python
df.select_dtypes(include='number').corr().abs()
```

Hunt for: features ≥0.95 correlated (collinearity / accidental dupes),
features ≥0.95 correlated with the LABEL (likely leakage), features
trivially derivable from each other.

### 7. What's the leakage story?

For any column you might use as a feature: could it have been recorded
AFTER the event you're trying to predict? If yes, exclude it or
timestamp-gate it.

## After EDA

You should now be able to write three sentences:

1. "One row is one ___."
2. "The dataset covers ___ to ___, with ___ rows and these caveats: ___."
3. "If I'm modeling ___ from ___, the leakage risks are ___."

If you can't write those three sentences, you're not ready to model.
