---
description: Minimum-viable accessibility review before shipping any UI surface
name: accessibility-baseline
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Accessibility Baseline

Minimum-viable accessibility pass before shipping a UI. The premise:
80% of accessibility wins come from 20% of practices, and those
practices are mostly free to implement at design time but expensive
to retrofit. Skipping this baseline locks out a non-trivial fraction
of users.

## When to use this skill

Use before shipping any user-facing surface: web app, mobile app,
CLI with TUI, terminal output that's expected to be parsed by a
screen reader. Skip for purely internal tooling that only the team
uses (and even there, your colleagues might benefit).

## The baseline checklist

These eight items, in order. Each is a low-effort high-impact check.

### 1. Keyboard navigation

EVERY interactive element must be reachable and operable with a
keyboard only:

- Tab cycles through interactive elements in a sensible order
- Enter/Space activates the focused element
- Escape dismisses modals / cancels in-progress actions
- Arrow keys navigate within composite widgets (menus, tabs, grids)

Quick test: unplug your mouse. Can you use the feature? If anything
is keyboard-inaccessible, fix before shipping.

### 2. Focus indicators

When an element has keyboard focus, it must be VISUALLY indicated.
Default browser focus rings count. Custom focus styles must have at
least 3:1 contrast against the unfocused state.

```css
/* good — visible custom focus */
button:focus-visible {
  outline: 2px solid #0066cc;
  outline-offset: 2px;
}

/* bad — outline removed with no replacement */
button:focus { outline: none; }
```

### 3. Color contrast

Text needs:
- 4.5:1 contrast for normal text
- 3:1 for large text (18pt+ or 14pt+ bold)

UI components (button borders, form field outlines, focus indicators)
need 3:1 against adjacent colors.

Tools: WebAIM Contrast Checker, axe DevTools, Chrome Lighthouse.

### 4. Don't rely on color alone

If the only way to distinguish two states is color (a red error
message vs green success), users with color blindness can't tell.
Add a non-color cue:

- Error: red AND an icon AND prefix text "Error:"
- Required field: red asterisk AND "(required)" in the label

### 5. Semantic HTML

Use the right element for the job:

- ``<button>`` for buttons, NOT ``<div onclick=...>``
- ``<a href>`` for navigation, NOT ``<span onclick=...>``
- ``<label for=...>`` for every form input
- ``<h1>``...``<h6>`` for actual heading hierarchy

Semantic HTML gives screen readers the structure they need to let
users skim. Generic divs give them nothing.

### 6. Alt text on meaningful images

Every ``<img>`` either has descriptive alt text OR ``alt=""`` (if
decorative). Empty alt is fine — MISSING alt is not.

- Icon next to "Save" text: ``alt=""`` (text already says it)
- Standalone icon button: ``aria-label="Save"`` on the button
- Content image (chart, photo): describe what it shows

### 7. Form labels and errors

Every input has an associated label. Errors are announced (use
``aria-live="polite"`` for error containers, or ``aria-describedby``
linking the input to the error message).

```html
<label for="email">Email</label>
<input id="email" type="email" aria-describedby="email-err" />
<div id="email-err" role="alert">Please enter a valid email.</div>
```

### 8. Reduced motion

Respect ``prefers-reduced-motion``:

```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

Some users get nauseated by parallax / animations. The OS-level
setting tells you who; honor it.

## Automated checks

Wire into your CI / dev workflow:

- **axe-core** (browser DevTools or CI plugin) — catches most
  programmatic a11y issues
- **Lighthouse** (Chrome) — accessibility score, run on every page
- **pa11y** (CLI) — scriptable axe runs against URLs

Automated tools catch ~30% of accessibility issues. The rest needs
manual checks.

## Manual checks (the other 70%)

- Screen reader pass: NVDA (Windows free), VoiceOver (Mac built-in),
  or TalkBack (Android). Spend 5 minutes navigating your feature
  with the screen reader. You'll find issues no automated tool
  catches.
- Zoom to 200%: does anything overflow / get cut off?
- Keyboard-only pass: as above, no mouse for 5 minutes.

## What this skill is NOT

- This is a BASELINE, not WCAG AAA compliance. If your product has
  legal or contractual obligations (government, healthcare,
  education), you need a deeper audit.
- It's not a substitute for testing with users who actually use
  assistive tech. Their feedback is more valuable than any checklist.

But shipping the baseline covers most users, costs little, and is
infinitely easier than retrofitting later.
