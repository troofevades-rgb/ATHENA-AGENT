---
description: Sketch UI structure before writing components or styling
name: design-wireframe-first
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Wireframe First

Before writing a single React/Ink/Vue/whatever component or CSS rule,
sketch the layout. The premise: layout decisions made implicitly via
flexbox tweaks are 10x more expensive than the same decisions made
explicitly at the wireframe stage.

## When to use this skill

Use when implementing any new UI surface: a panel, a dialog, a screen,
a CLI render that's more than one line. Skip for one-line text output
or trivial tweaks to existing layouts.

## The wireframe pass

### 1. Block diagram first

ASCII or napkin sketch, with explicit box widths and heights. Don't
skip to "I'll figure it out as I code." That's how you ship the panel
that's 2px off and you can't tell why.

```
┌─ Header ─────────────────────────────────────┐
│  ▰▰ title              [search] [⋯] [×]      │
├─────────────┬────────────────────────────────┤
│  Sidebar    │  Main                          │
│  (16 cols)  │  (flex)                        │
│             │                                │
│  • item     │  [scrollable content]          │
│  • item     │                                │
├─────────────┴────────────────────────────────┤
│  Status bar (1 row, pinned)                  │
└──────────────────────────────────────────────┘
```

### 2. Annotate the layout rules

For each region:

- **Fixed vs flex.** Which boxes have fixed dimensions, which grow?
- **Overflow.** What happens when content exceeds the box? Scroll?
  Clip? Wrap? Ellipsize?
- **Resize behavior.** At small terminal/window sizes, what collapses,
  hides, or stacks?

### 3. State variants

Sketch the EMPTY state, the LOADING state, the ERROR state, and the
FULL state separately. Each is a real screen the user will see.

### 4. Interaction targets

Annotate every clickable / focusable / keybindable target with its
trigger:

- Sidebar items: click + arrow keys
- Status bar: not interactive
- Header X: click + Esc

### 5. Now write the code

The component code now has clear answers for: which container is
``flex-grow``, which has a fixed height, what the empty-state render
looks like, what overflow behavior is. The flexbox tweaks that
otherwise eat hours become five-second decisions.

## Why this works

Implicit layout decisions are made in the IDE under time pressure with
incomplete information about state variants and edge cases. Explicit
layout decisions are made in a sketch with the full structure in view.
The latter is 10x cheaper and the result is more coherent.

Worth noting: 5 minutes of wireframing saves the next person reading
your code 30 minutes of inferring intent from CSS.
