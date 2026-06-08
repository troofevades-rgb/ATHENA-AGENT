---
description: Evaluate models beyond accuracy — slice analysis, calibration, failure modes
name: model-evaluation
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Model Evaluation

Disciplined evaluation of a trained model. The premise: top-line
accuracy hides every interesting failure mode. A model with 92%
accuracy might be 99% on the easy slice and 50% on the slice that
matters most.

## When to use this skill

Use whenever you have a trained model and need to decide whether to
ship it, iterate on it, or kill it. Skip for hello-world tutorials.

## The five-lens evaluation

Run all five before drawing conclusions.

### 1. Top-line metric (but with context)

Compute the metric the stakeholder cares about — accuracy, AUC, F1,
RMSE, BLEU. Then immediately compute the baseline:

- For classification: majority class predictor + class-balanced
  random predictor
- For regression: predict the mean + predict the median
- For ranking: random ranking
- For LLM tasks: a simpler model on the same task

If your model beats the baseline by 1pp, that's NOT a 1pp
improvement — it's a 1pp improvement that might be noise. Compute
the confidence interval too.

### 2. Slice analysis

The aggregate metric is a weighted average of per-slice metrics.
Compute metrics PER slice for every meaningful slice:

```python
for slice_col in ["country", "age_bucket", "device_type"]:
    print(df.groupby(slice_col).apply(lambda g: accuracy(g.y, g.yhat)))
```

Look for: slices where the model performs much worse than average,
slices where it performs much better. The worse-performing slices are
where harm concentrates. The better-performing slices often reveal
that the model is winning on easy cases.

The slice that matters MOST often isn't in the obvious feature
columns. Try: "users who signed up this month", "queries with
non-English characters", "transactions on weekends".

### 3. Calibration

For probabilistic predictions, calibration is the question: when the
model says "80% confident," is it right 80% of the time?

```python
# Bin predictions by confidence and compute actual accuracy per bin
import numpy as np
bins = np.linspace(0, 1, 11)
df["conf_bin"] = pd.cut(df.confidence, bins)
df.groupby("conf_bin").apply(lambda g: (g.y == g.yhat).mean())
```

A well-calibrated model lets downstream consumers make threshold
decisions. An uncalibrated model — even an accurate one — gives
misleading confidence scores.

### 4. Failure-mode analysis

Take the 50 worst predictions (highest-loss or wrong-with-high-
confidence) and ACTUALLY READ THEM. This is the most important step
and the most often skipped.

For each, ask:
- What's the true label? Is the label correct?
- What's the model's prediction? Why might it have made that
  mistake?
- Is this an ambiguous case (humans would disagree)?
- Is it a data quality issue (bad input)?
- Is it a systematic blind spot (a CLASS of inputs the model can't
  handle)?

A pattern across 5+ of the 50 worst is a systematic issue worth
fixing. One-offs are noise.

### 5. Compare to deployment cost

Before shipping, ask:

- **Latency budget**: does inference fit the latency the surface
  requires?
- **Memory budget**: does the model fit production hardware?
- **Cost per prediction**: if external API, what's monthly cost at
  expected QPS?
- **Failure mode if model misbehaves**: graceful degradation? noisy
  page? silent wrong answer?

A great model that costs 10x too much in inference is a research
artifact, not a production model.

## Specific pitfalls

### Train/test leakage

Re-run the seven-question pass from [[data-exploration]]. The most
common leakage source: a feature was computed AFTER the event
predicted (target leakage). Less common but devastating: the test set
includes rows from entities (users, items) the model saw in training
(group leakage). Always split by group when groups exist.

### Distribution shift

The eval set should resemble production. If the production data is
this month's traffic but the eval set is from last year, the metric
is reporting on a distribution that no longer exists.

### Overfitting to the eval set

Iterating model designs against the same eval set N times = the
eval set is now training data. Reserve a held-out test set that's
touched only at the END.

### Sensitive subgroup performance

For models that affect humans (hiring, lending, healthcare,
moderation): compute per-protected-class metrics. A model with 95%
overall accuracy that's 99% on one demographic and 70% on another is
a fair-housing-act problem waiting to happen.

## Reporting

After evaluation, write a one-page evaluation memo:

1. **Headline metric + confidence interval**
2. **Baseline gap**: model is X pp above baseline
3. **Worst slice**: this slice is the area of concern
4. **Failure mode summary**: 50-error review found these patterns
5. **Recommendation**: ship / iterate / kill, and why

Stakeholders read the memo. They don't read your notebook.
