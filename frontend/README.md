# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## Engine at Work demo

Open `/#/engine` (for example `http://localhost:5173/#/engine`), or choose
**Engine at work** in the caregiver dashboard / the seeded demo link in onboarding.
No backend or profile setup is required for this page.

The replay follows five fictional conversations in a single-screen knowledge graph.
Play, pause, jump to a conversation, step backward/forward, or reset using the fixed
footer controls. Change Breakfast / Playtime / School to explore six suggestions.
Select graph nodes (mouse or keyboard) to open a right-side details panel with their
source and initial suggestion. Conversation nodes show dialogue, confirmed replies,
and caregiver additions without changing the replay step. Close the panel with its
close button, Escape, or by dragging its header at least 80px to the right. Focus
returns to the item that opened it. The panel is closed initially and has no fixed
card inside the graph.
Drag any node (including hubs and Alex) to rearrange it; connections follow. Drag
background space to pan, and scroll or use trackpad pinch to zoom around the pointer.
The fixed graph toolbar provides zoom buttons, Fit graph, and Reset layout. Layout
changes remain during replay/context changes but are not saved after a page reload.
Keyboard: focus a node and use arrows to move it (Shift for larger steps); focus the
graph background and use arrows to pan. Plus/minus zoom; zero fits the graph.
Personal vocabulary, caregiver-approved profile facts, and confirmed speech accumulate
only through the selected step. The graph fits the viewport without page scrolling;
a desktop or landscape display gives the clearest view of all labels.

Edit `src/data/engineDemo.ts` to change the fixture. Its small deterministic ranker
illustrates favorites, context-matching history, broader history, and starter phrases;
it does not call the production predictor, use time buckets/recency decay, learn
profile facts automatically, or persist any demo data. The shared word bank is unchanged.

Run replay checks with `node --experimental-strip-types --test src/data/engineDemo.test.ts`.
