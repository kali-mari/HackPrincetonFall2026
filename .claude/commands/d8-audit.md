---
description: D8b: accessibility and responsiveness audit with fixes
---

Use the impeccable skill's audit command on the frontend for accessibility and responsiveness. In addition to its usual checks, verify:
- every interactive target matches LAYOUT.md sizes on the board and is at least 44px on the dashboard
- text contrast meets WCAG AAA (7:1) on the board
- the spoken sentence is announced through an aria-live region
- keyboard focus order matches the scanning order
- nothing on the board moves position when predictions update
- prefers-reduced-motion removes all scaling and fading
Then fix every failure, smallest change first.

Done when: the audit passes.
