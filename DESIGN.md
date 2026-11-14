# Design System

Tokens live in `frontend/src/styles/tokens.css`. Components use the tokens, never raw values.

## Who it's for
An 8 year old nonverbal child with limited motor control, using a laptop or tablet in a bright classroom, often through switch scanning. Every choice favors legibility at a distance and zero ambiguity about what is selected.

## Color
- **Fitzgerald Key fills**: soft pastels in the colors AAC users and therapists already know, so the board needs no relearning.
- **People & pronouns `#FFF3A3` (yellow), verbs `#C9F2C2` (green), describing `#C9E2FF` (blue), nouns `#FFD8A8` (orange), social `#FFD4EA` (pink), negation `#FFC8C2` (red)**: black text on each is 14:1 to 19:1, well past AAA (7:1), so labels stay readable under classroom glare.
- **Black text and 2px black tile borders**: maximum contrast, and tiles stay distinct even for color-blind viewers.
- **White page**: the pastel tiles are the only color on the board, so category reads instantly.
- **Caregiver palette (slate `#1E293B` on `#F6F8FA`, teal `#0F5257` accent)**: a calm, separate world so adults never confuse the dashboard with the child's board; all text pairs pass AAA.

## Scanning highlight
- **Violet `#5B00D6`**: no Fitzgerald category uses it, and it contrasts 5.9:1 to 7.7:1 with every tile fill and 8.7:1 with the page, so it stands out from 3 meters.
- **6px solid outline drawn inside the box**: it covers the thin black border, so it reads as "this one" rather than as a tile border, and it is never clipped by the screen edge.
- **Slight scale (1.04)**: a second, non-color cue, so the highlight is visible to color-blind viewers too.

## Typography
- **Atkinson Hyperlegible**: designed by the Braille Institute so similar letters (I/l/1, O/0) never get mixed up.
- **Tile labels 24px bold**: the required minimum, bold for distance reading.
- **Sentence strip 40px**: above the 36px floor; this is the line the child and listeners read together.
- **Prediction row 28px**: sits between tile labels and the strip in importance.

## Spacing and size
- **8px grid**: every space is a multiple of 8, so layouts line up without guesswork.
- **Tiles 120px**: the required minimum, and the largest size that fits the full board on a 1280x800 screen (see LAYOUT.md).
- **16px gaps**: enough to prevent mis-taps between neighbors without shrinking the grid.

## Motion
- **One transition: the highlight moves in 120ms**: fast enough to keep up with switch scanning, slow enough to follow.
- **Reduced motion**: under `prefers-reduced-motion`, the duration drops to 0ms and the scale to none; the outline alone carries the highlight.
