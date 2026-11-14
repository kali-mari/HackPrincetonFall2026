⚠️ DEGRADED: single-context (run as a delegated subagent; nested sub-agents not spawned, so Assessment A was written before reading detector output, in one context)

# Design critique (D8a)

Target: the child's board (`frontend/src/App.tsx`, `/`) and the caregiver dashboard (`frontend/src/Caregiver.tsx`, `#/caregiver`).
Rendered in headless Chrome at 1280×800 and 1024×768 against a `vite preview` build of `Nirmal` (b2dca7b), with the seeded backend on :8000. No code was changed for this critique.

## Design health score (board, with the dashboard folded into 9 and 10)

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Speaking pulse, spinner and error banner work; Speak on an empty strip does nothing and shows nothing. |
| 2 | Match system / real world | 2 | Fitzgerald colors are right, but there are no symbols: every tile is a word, which an AAC user cannot rely on. |
| 3 | User control and freedom | 2 | Clear wipes a sentence that took ~35 presses in one press, with no undo. |
| 4 | Consistency and standards | 3 | Predictions, tabs, Delete and Clear share one white box, so the shortcut row reads like more controls. |
| 5 | Error prevention | 2 | Clear has no guard; Speak looks live when there is nothing to say. |
| 6 | Recognition rather than recall | 2 | Text-only tiles and tabs; the child must read every word. |
| 7 | Flexibility and efficiency | 3 | Touch, keyboard, buttons, touch pad and voice switch all drive one scanner; predictions save selections. |
| 8 | Aesthetic and minimalist design | 3 | Calm, legible, no decoration; the white control boxes are a little clinical. |
| 9 | Error recovery | 3 | "Couldn't speak. Try again." is plain and keeps the sentence; a failed prediction silently keeps the old row (by design). |
| 10 | Help and documentation | 2 | Dialog hints are good; nothing tells a new adult how scanning works. |
| **Total** | | **25/40** | **Acceptable** |

Scores by the three areas the brief asked for:

| Area | Board | Dashboard |
|---|---|---|
| Hierarchy | 3/4: Speak is unmistakably primary; predictions lack their own weight | 3/4: clear cards, but the left column is empty in the demo |
| Clarity | 2/4: labels-only tiles, silent empty Speak | 3/4: plain headings and copy |
| Emotional tone | 3/4: warm pastels, never babyish | 3/4: calm slate and teal, a little bare |

## Design specificity verdict

**LLM assessment.** The board is authored for this product, not a template: the 6-band 1280×800 geometry, the pinned core words, the Fitzgerald fills with same-hue darker borders, the violet inside-the-box scan ring and the black double-width Speak are all decisions an AAC board needs and a generic grid would not make. The caregiver cell (gear, demo clock, connection dot, source flash) is a smart, demo-specific touch. The weakest part is the white bordered box used for every non-word control, which is the most generic element on screen. The dashboard is competent but category-interchangeable: three bordered cards on a gray page.

**Deterministic scan.** `impeccable detect --json frontend/src` returned `[]` (0 findings). The in-page detector overlay, injected on `/` and `#/caregiver`, logged "No anti-patterns found" on both. Nothing for the detector to add or to flag as a false positive; every issue below came from the manual review and the renders. (Overlay ran in a private headless profile, so no [Human] tab exists.)

## Overall impression

A solid, honest board whose geometry, color and scanning are right. The single biggest gap is that it is a word board, not a symbol board: the 64px symbol slot is empty on every tile. The second is that a long sentence can be lost in one press.

## What's working

- **Speak is the loudest thing on the screen.** Solid black, double width, icon plus word; the eye and the scanner both find it first.
- **The scan highlight is unmistakable.** Violet outline with a white inner ring reads on every fill, including black, and the 1.05 scale gives a non-color cue.
- **The Fitzgerald fills and same-hue borders** keep categories legible without a heavy grid, and the strip chips carry the colors into the sentence.

## Priority issues (top 5, ranked by impact on the child)

1. **[P1] No symbols on any tile.** `frontend/public/symbols/` does not exist, so every `<img>` fails and the tile falls back to a label. A nonverbal 8 year old should not have to read to communicate. **Fix:** choose an openly licensed set (ARASAAC or Mulberry) and drop `{id}.svg` files into `frontend/public/symbols/`; the code already loads them, so no layout change. This is an asset decision for the team; do not invent artwork. *Position-safe.* Suggested command: `/impeccable polish` once assets exist.
2. **[P1] Dimmed groups fail AAA contrast.** While scanning, every other group drops to 60% opacity, which takes label contrast to 4.6:1 to 5.7:1 (5.7:1 on Speak). Those tiles are still tappable, so the AAA rule applies. **Fix:** dim to 75% instead (7.8:1 to 10.4:1); the active group still stands out. *Position-safe.* Suggested command: `/impeccable audit`.
3. **[P1] The spoken sentence is not announced, and Speak on an empty strip is silent.** There is no `aria-live` region carrying what was said, and selecting Speak with no words gives no response at all, so the child cannot tell a dead press from a slow one. **Fix:** a visually hidden `aria-live="polite"` status that announces each spoken sentence; mark Speak `aria-disabled` and visibly muted while the strip is empty, keeping it in the scan order. *Position-safe; scan order unchanged.* Suggested command: `/impeccable harden`.
4. **[P1] Clear loses a whole sentence in one press, with no undo.** "I want go outside" costs about 35 presses; one stray SELECT on Clear (or a tap on the far corner) throws it away. **Fix:** after Clear, let the next Delete restore the cleared sentence when the strip is still empty (no new button, no new position). *Position-safe.* Suggested command: `/impeccable harden`.
5. **[P2] Predictions look like controls.** The six phrases share the white box and regular weight of Delete, Clear and the tabs, so the row that saves the most presses has no visual identity. **Fix:** bold the prediction text (it is already 28px) so the row reads as "things to say", not "buttons to manage". *Position-safe; no size change.* Suggested command: `/impeccable typeset`.

No issue above requires moving or resizing a symbol tile or changing the scanning order, which LAYOUT.md forbids.

## Persona red flags

**The child, switch scanning (project persona).** Entering the message bar and pressing SELECT on Speak with an empty strip does nothing visible, so the child repeats the press. Six of seven groups are 60% gray during every scan step, which is harder to read from the side of a wheelchair tray. A slip onto Clear costs the whole sentence.

**Communication partner across the room (project persona).** The strip empties the moment the audio ends, so a partner who missed the audio has nothing to read. Screen reader users get nothing at all, since nothing is announced.

**Jordan, first-time parent on the dashboard.** "Said today" says "Nothing spoken yet today" in the demo even though the backend holds 20 seeded sentences: the seed is timestamped in UTC and falls on yesterday's local date, so the main card is empty and the left column is mostly blank space. Nothing explains what "How predictions adapt" compares or why 12:15 PM was chosen.

## Minor observations

- Unselected tabs are regular weight and only the selected one gets an 8px inset bar; fine, but the bar is black on a white box, the same ink as every border.
- The Listening badge reuses the error red, so it reads as an alarm.
- `Caregiver.tsx` calls `new Date()` during render (oxlint impure-call warning); harmless today.
- `main.tsx` defines `Root` next to the render call (oxlint only-export-components); fast refresh only.
- Dashboard text is 16px slate on near-white; AAA passes (7.1:1 muted on page), but the `×` count suffix and time column are the same muted gray as body hints.

## Questions to consider

- What would the board look like if the phrase row were the first thing a partner noticed after Speak?
- Should the last spoken sentence stay on the strip, grayed, until the first new word, so the room can read it?
- Does the dashboard need "today" at all in a demo, or should it show the most recent day with sentences?

Questions skipped: run as a delegated subagent with no way to ask the user; the caller's brief (apply the top 5 in D8b where LAYOUT.md allows) stands in for the answers.
