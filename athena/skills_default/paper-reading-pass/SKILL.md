---
description: Efficiently extract value from a research paper without reading every word
name: paper-reading-pass
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Paper Reading Pass

Disciplined approach to reading a research paper for engineering or
research purposes. The premise: reading every paper top-to-bottom is
slow and unfocused. A three-pass protocol gets the value faster and
helps you decide whether the paper deserves a full read.

## When to use this skill

Use when the user asks "what does this paper say?", "is this idea
relevant to X?", or hands you a paper to inform a design decision.
Use during [[literature-survey]] when triaging candidate references.

Skip for textbooks, blog posts, and documentation — those need
different reading strategies.

## The three-pass protocol

Read in passes, each ~10–15 minutes. After each pass, decide whether
to continue.

### Pass 1: The 10-minute skim

Goal: understand what the paper claims and decide if it's worth a
deeper read.

Read in this order:

1. **Title and abstract** — what's the claim?
2. **Introduction** (just the last paragraph) — usually states "our
   contributions are: 1) ... 2) ... 3) ..." — the contribution list
   is the paper's actual claim
3. **Figures, captions, and tables** — they show the headline
   results without you having to parse the prose
4. **Conclusion** — restates the claim in light of results
5. **Section headings** — gives you the structure

After this pass, you should be able to answer:

- What problem is this paper attacking?
- What's their proposed approach (in one sentence)?
- What's the headline result?
- Is the paper rigorous or speculative? (theory paper? empirical?
  position paper?)

**Decision**: stop here if it's clearly not relevant. Continue if
you need to understand HOW or WHY they got their result.

### Pass 2: The 30-minute structure pass

Read each section's first and last paragraph. Read all figures and
tables in full. Skim the math.

Goals:

- Map the architecture / method to a block diagram you can sketch
  in 30 seconds
- Identify the key empirical claim AND the experimental setup that
  supports it
- Identify the comparison baselines (what are they claiming to beat?)
- Spot the limitations section (often the most honest part)

After pass 2, you should be able to:

- Sketch the method
- Name the dataset(s) and metrics used
- Name the baselines compared against
- State the magnitude of improvement claimed

**Decision**: stop here if the structural understanding is enough
for your purposes. Continue if you need to reproduce, build on, or
critique the work.

### Pass 3: The 2-hour deep read

For papers you'll cite, reproduce, or build on directly.

- Read each section carefully
- Work through the math (write it out by hand if needed)
- Re-derive at least one of their results from the equations
- Check the supplementary material / appendix for assumptions and
  caveats
- Find the code (if released) and skim its structure
- Read 2–3 of the papers in their reference list

After pass 3, you should be able to critique the paper at a research-
seminar level — what's strong, what's weak, what they swept under the
rug, what's the obvious next paper.

## What to extract

For every paper you finish reading, record (in a notes file or wiki):

```
Title:
Authors:
Year:
Venue:
Link:

One-sentence claim:

Method (1-2 sentences):

Empirical result (specific numbers):

Baselines beaten / not beaten:

Most important limitation:

Why I read it / how it might be useful:
```

That's the paper's working memory. Next time you face a similar
problem, you can grep your notes faster than you can re-read the
paper.

## Red flags during reading

Signals that the paper is weaker than it claims:

- Comparison to obviously-weak baselines (not the SoTA)
- No standard datasets (cherry-picked evaluation set)
- "Statistically significant" without a confidence interval
- Tables where the bold-best is highlighted but the gap is within
  noise of the second-best
- Ablations missing the most obviously-important ablation
- Limitations section is a single paragraph at the end (real
  limitations get a section)

None of these necessarily kill the paper, but they should temper
your confidence in the claim.

## Specific to ML / AI papers

- Read the dataset section before the method. If the dataset is
  fishy (synthesized in a way that favors the method, subsetted to
  what works), the method evaluation is meaningless.
- Check the eval split: train/test or train/val/test? Held-out
  through how many iterations?
- Compute requirements often matter as much as accuracy: a 0.5pp
  improvement at 10x compute is usually not worth it.

## Specific to systems papers

- The bottleneck the system addresses is the key claim
- Benchmark setup matters MORE than benchmark numbers — what
  workload? what hardware? what configuration?
- "Production deployment" claims should specify scale (how many
  users / requests / nodes)
