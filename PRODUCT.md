# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **The child (primary):** an 8 year old with cerebral palsy who is nonverbal and has limited hand control. Mostly uses two Arduino buttons (NEXT, SELECT) to drive scanning, and the touchscreen when able. Uses the board in the classroom and at home to build sentences from symbols and have them spoken aloud.
- **Communication partners:** the adults around the child. They hear the spoken output and read the sentence strip, often from across the room.
- **Parents and teachers:** use the caregiver dashboard to see what the child said today and how predictions are adapting.
- **Speech therapists (secondary):** use the same dashboard to review history.

## Product Purpose

Give a nonverbal child with limited motor control a fast, affordable way to say what they want. The child builds a sentence from symbols, the board speaks it aloud, and it predicts likely phrases from time of day, activity, and the child's own history so each sentence takes fewer selections. Success: the child communicates with fewer selections, and caregivers can see what was said.

## Positioning

Compared with Proloquo2Go or TD Snap: much cheaper hardware (an Arduino with simple physical switches and a vocal switch, plus any laptop or tablet), no manual programming, and context-aware phrase predictions.

## Operating Context

- Runs in a browser on a laptop or tablet in a bright classroom and at home.
- Input arrives from the touchscreen, the keyboard fallback (Space = NEXT, Enter = SELECT), or the Arduino switches (NEXT and SELECT buttons, a touch sensor, a vocal switch) through a serial bridge and WebSocket.
- Speech plays on the device and can be cast to a Google Home so the room hears it.
- Built in 36 hours for HackPrinceton 2026; the live demo path comes first.

## Capabilities and Constraints

- Core flows: the symbol grid, sentence strip, prediction row, switch scanning, input settings, and the caregiver dashboard.
- Six phrase predictions at a time, from Claude Haiku on Bedrock, falling back to the most frequent phrases for the time of day when the call fails or takes longer than 2 seconds.
- Speech uses a neural, child-sounding Polly voice. Spoken sentences are logged to DynamoDB.
- No auth. Contracts between frontend, backend, and hardware are fixed in CLAUDE.md.
- Undecided: which symbol image set to use; the demo persona's seed data (planned for `backend/seed/`, not yet written).

## Brand Commitments

Feel: warm, clear, calm, trustworthy, never babyish.

## Evidence on Hand

None yet: no user testing, testimonials, therapist endorsements, or usage data. Do not invent any. The demo uses seed data for the persona above.

## Product Principles

1. **The child's voice comes first.** Every interaction serves getting a sentence spoken with the fewest selections.
2. **Every input path is equal.** Switches, vocal switch, touch, and keyboard all drive the same scanning; none is an afterthought.
3. **Respect the child.** Treat an 8 year old as a capable communicator, never as a toddler.
4. **Readable across the room.** Spoken output and the sentence strip are for the partners listening too.
5. **Predictions help, never get in the way.** When they are slow or wrong, the board stays fully usable.

## Accessibility & Inclusion

- Limited motor control: large targets (at least 120px), debounced switches, and a vocal switch that fires only on sustained sound (about half a second).
- Switch scanning needs a highlight that is unmistakable from a distance.
- WCAG AAA (7:1) text contrast on the child's board; the modified Fitzgerald Key colors that AAC users and therapists already know.
- Respect `prefers-reduced-motion`.
