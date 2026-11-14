# Design System

Tokens live in `frontend/src/styles/tokens.css`. Components use the tokens, never raw values.

## Who it's for
An 8 year old nonverbal child with limited motor control, using a laptop or tablet in a bright classroom, often through switch scanning. Every choice favors legibility at a distance and zero ambiguity about what is selected.

## Color
- **Fitzgerald Key fills**: soft pastels in the colors AAC users and therapists already know, so the board needs no relearning.
- **People & pronouns `#FFF3A3` (yellow), verbs `#C9F2C2` (green), describing `#C9E2FF` (blue), nouns `#FFD8A8` (orange), social `#FFD4EA` (pink), negation `#FFC8C2` (red)**: black text on each is 14:1 to 19:1, well past AAA (7:1), so labels stay readable under classroom glare.
- **Black text; 2px tile borders in a darker shade of the tile's own fill** (the fill mixed 50% with black): tiles stay distinct from the white page and from each other even for color-blind viewers, without a heavy black grid. Controls without a Fitzgerald fill keep a 2px black border.
- **Speak is solid black with white text and a speaker icon**: the largest, darkest box on the board, so it is the most prominent control without adding a new color. While the strip is empty it is an outlined white box like Delete (and `aria-disabled`), so turning black with the first word says "ready to speak".
- **White page**: the pastel tiles are the only color on the board, so category reads instantly.
- **Caregiver palette (slate `#1E293B` on `#F6F8FA`, teal `#0F5257` accent)**: a calm, separate world so adults never confuse the dashboard with the child's board; all text pairs pass AAA.
- **Caregiver surfaces share one treatment**: the dashboard, the input settings dialog, and the demo clock dialog all use the slate-on-`#F6F8FA` page, white bordered panels, 16px text, and a thin 3px violet focus ring (not the board's 6px scan outline). Load problems and setup problems (blocked mic, backend down) are plain ink on a quiet panel, never red: they say what didn't work and the one step that fixes it. Red stays for the child's "Couldn't speak. Try again." banner.
- **Tap to start** wears Speak's look (black box, speaker icon, 40px white text) on the white page, with one gray line under it for adults, so the child's first sight is the board's own "go" button.

## Scanning highlight
- **Violet `#5B00D6`**: no Fitzgerald category uses it, and it contrasts 5.9:1 to 7.7:1 with every tile fill and 8.7:1 with the page, so it stands out from 3 meters.
- **6px solid outline drawn inside the box**: it covers the thin black border, so it reads as "this one" rather than as a tile border, and it is never clipped by the screen edge.
- **Group level**: every box in the active group gets the outline plus a lavender inner ring; the tile fills keep their true Fitzgerald colors.
- **Item level**: only the active item gets the outline and a 1.05 scale, a second, non-color cue for color-blind viewers.
- **Back-out**: the whole group again, but with a dashed outline and no tint, so "leave this row" never looks like "choose this row".
- **Everything else dims to 75%**: the eye goes straight to the active group from across the room, and dimmed labels still meet AAA (7.8:1 or more; 60% dropped them to 4.6:1).

## Typography
- **Atkinson Hyperlegible**: designed by the Braille Institute so similar letters (I/l/1, O/0) never get mixed up.
- **Tile labels 24px bold**: the required minimum, bold for distance reading.
- **Sentence strip 40px**: above the 36px floor; this is the line the child and listeners read together. The strip is a white bar with a 4px black border; each word sits in a mini tile chip with its own Fitzgerald fill and darker border, so the sentence keeps the colors it was built from. Two rows of chips fit; when a sentence is longer, the oldest words scroll out of view at the top.
- **Prediction row 28px bold**: sits between tile labels and the strip in importance; bold so the phrases read as things to say, not as controls like Delete and Clear.

## Spacing and size
- **8px grid**: every space is a multiple of 8, so layouts line up without guesswork.
- **Tiles 120px**: the required minimum, and the largest size that fits the full board on a 1280x800 screen (see LAYOUT.md).
- **16px gaps**: enough to prevent mis-taps between neighbors without shrinking the grid.
- **Caregiver cell text is 16px, one line each**: Listening or Backup voice, then the dot row, always fit inside the 120×120 cell; a too-long word is cut with an ellipsis rather than pushing the dot row out.

## Motion
- **The scanning highlight, 120ms**: the outline, dimming, and scale all change together, fast enough to keep up with switch scanning, slow enough to follow.
- **Tile press, 120ms**: a tapped tile darkens and shrinks to 0.97, so the child sees the press land before audio plays. A tap clears the scan highlight, so the press never meets the 1.05 scan scale.
- **Speaking pulse**: while audio plays, the sentence strip's border fades slowly between black and gray (1.2s). Gray, not violet, so it is never mistaken for the scan highlight.
- **Reduced motion**: under `prefers-reduced-motion`, every change is instant, with no scale, no dimming, and no pulse; the outline alone shows what is highlighted, and a pressed tile only darkens.
