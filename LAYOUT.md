# Board Layout (approved)

The main AAC board screen. Colors, type, and motion come from `DESIGN.md` and `frontend/src/styles/tokens.css`.

## Screen

- Designed for **1280x800, fullscreen** (browser bars hidden). This is the demo setup.
- Height: 6 bands of 120px plus 5 gaps of 16px = exactly 800px. No top or bottom margin.
- Width: 16px margin left and right, leaving 1248px.
- **Normal window fallback:** scale the whole board down uniformly to fit the viewport. Positions and proportions never change; tiles shrink below 120px only in this fallback.

## Regions

```
x: 16    176 192                                                        1264
   ┌─────────────────────────────────┬──────┬──────────────┬───────┬───────┐ y 0
 1 │ SENTENCE STRIP 568×120 (40px)   │⚙ ⏲  │ SPEAK 256×120│DELETE │ CLEAR │
   │                                 │● src │              │       │       │
   └─────────────────────────────────┴──────┴──────────────┴───────┴───────┘ 120
   ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐         136
 2 │ phrase 1 │ phrase 2 │ phrase 3 │ phrase 4 │ phrase 5 │ phrase 6 │
   └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘         256
   ┌──────┐ ┌───┬───┐┌───┬───┬───┬───┬───┬───┐                               272
 3 │ TAB 1│ │ I │want││ category slots 1-6    │
 4 │ TAB 2│ │like│go ││ category slots 7-12   │
 5 │ TAB 3│ │more│help│ category slots 13-18  │
 6 │ TAB 4│ │stop│not││ category slots 19-24  │                               800
   └──────┘ └───┴───┘└───────────────────────┘
   160 wide  core      category (cols 3-8)
```

| Region | Position (x, y) | Size | Notes |
|---|---|---|---|
| Sentence strip | 16, 0 | 568×120 | 40px words as Fitzgerald-colored chips, 2 rows; longer sentences keep the newest words in view. Spans the tab column plus grid columns 1-3. Tapping it speaks the sentence. |
| Caregiver cell | 600, 0 | 120×120 | Above grid column 4. **Not in the scan order**; adults only. Top row: the input settings gear (48×48, an adult tap target above the 44px minimum), then the demo clock (48×48), which opens a time picker; while a demo time is set, the clock is filled teal and every prediction uses that time. Bottom row: the switch connection dot (green and filled when connected, gray and hollow when not), then the current activity ("Lunch"). For one second after each switch message, the source name ("button", "touch", "voice") replaces the activity so the demo audience sees which input fired. |
| Speak | 736, 0 | 256×120 | Double width; the most important action. |
| Delete | 1008, 0 | 120×120 | Removes the last word. On an empty strip right after Clear, it brings the cleared sentence back (until a new word is added). |
| Clear | 1144, 0 | 120×120 | Far corner, hardest to hit by accident. |
| Predictions | 16, 136 | 6 × ~195×120 | Equal widths with 16px gaps. 28px text, 2 lines. |
| Category tabs | 16, 272 | 4 × 160×120 | One tab per grid row. Selected tab marked by a thick bar and bold text, not color alone. Labels wrap to 2 lines at 24px. |
| Symbol grid | 192, 272 | 1072×528 | 8 columns × 4 rows of 120×120 tiles, 16px gaps. Each tile has a 64px symbol, a 24px bold label, and its Fitzgerald Key fill. |

Grid column x positions: 192, 328, 464, 600, 736, 872, 1008, 1144. Row y positions: 272, 408, 544, 680.

## Slot rules

- The grid has 32 numbered slots. A word always stays in its slot; nothing ever reflows.
- **Core words (columns 1-2) stay the same on every tab:**

  | Row | Column 1 | Column 2 |
  |---|---|---|
  | 1 | I (people, yellow) | want (verb, green) |
  | 2 | like (verb, green) | go (verb, green) |
  | 3 | more (describing, blue) | help (verb, green) |
  | 4 | stop (verb, green) | not (negation, red) |

- **Category slots (columns 3-8):** 24 per tab. Switching tabs changes only these 24 words.
- **Tabs, in order:** Food and Drink, Feelings, Play and Places, People and School.
- An unused slot stays as a blank space.

## Predictions

- Exactly 6 phrases, each **22 characters or fewer** (about 4 words). The Bedrock prompt must say so, and the backend trims or drops longer ones.
- **Tapping or selecting a phrase speaks it immediately** and logs it. The sentence strip is left as it is.
- Fetched from `POST /api/predict` on load, every 60 seconds, and right after each spoken sentence. `recent` is the last 3 sentences spoken this session; `time` is local ISO with the UTC offset, or the demo clock's time when one is set.
- While a fetch is in flight, or if it fails, the previous phrases stay. The row is never empty: it starts with 6 default phrases.
- The current activity (for example "Lunch") shows in the caregiver cell, read from an optional `activity` field in the reply. It is hidden if the backend does not send one.
- Predictions only change the text inside the 6 boxes; no symbol tile ever moves.

## Switch scanning

Step scanning only: **no timers anywhere**. Nothing moves unless the child presses NEXT or SELECT (or the keyboard fallback, Space and Enter).

Scanning is always ready; there is no on/off toggle. The first NEXT shows the highlight, and any tap hides it. Logic lives in `frontend/src/scanning.ts`.

1. **Group level.** NEXT moves the highlight through the groups in this order, wrapping at the end:
   1. Message bar
   2. Predictions
   3. Category tabs
   4. Grid row 1
   5. Grid row 2
   6. Grid row 3
   7. Grid row 4
2. **Item level.** SELECT enters the highlighted group; NEXT then steps through its items from left to right (top to bottom for the tabs). The message bar's items are Speak, Delete, Clear; the sentence strip is not a scan item, since it only repeats Speak. Empty grid slots are skipped.
3. **Back out.** Stepping past the last item highlights the whole group again; SELECT then returns to the group level without choosing anything.
4. **After a choice.** Selecting an item acts on it (a tile adds its word, a prediction speaks its phrase, Speak speaks the strip, a tab switches category), then scanning returns to the group level **on the same group**, so a nearby next word takes fewer presses.
5. **Touch** works at any time and clears the scan highlight.
   **Tab focus** follows the same order (Speak, Delete, Clear, predictions, tabs, grid rows); the sentence strip is skipped, and the caregiver cell comes last.
6. **Switches.** The Arduino buttons, touch sensor, and vocal switch reach the board over `WS /ws/input/` and call the same NEXT and SELECT. The input settings dialog (from the gear) chooses which sources count; messages from a disabled source are ignored. While the dialog is open, Space and Enter work its own controls instead of scanning.

The scan highlight is drawn inside each box, because the top and bottom rows touch the screen edge where an outside outline would be cut off. A white ring inside the violet keeps it visible on every fill, including the black Speak button.

Example: building and speaking "I want go outside" from the Food and Drink tab takes 35 presses (about 21 seconds at 0.6 seconds per press).
