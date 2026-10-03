# UI explorations

Independent static sketches of the app's UI. They exist to argue about layout, hierarchy and tone
before anything is built for real in [`frontend/`](../../frontend).

## How to open

Double-click [`index.html`](index.html) to open the gallery, or open any exploration's own
`index.html` directly. There is no build step, no package manager, no server and no network
access — plain HTML, CSS and classic JavaScript, so every page works straight from `file://`.

## Explorations

| Folder | Exploration | Covers | By |
| --- | --- | --- | --- |
| _none yet_ | | | |

## Folder rules

**Keep UI files out of this root folder.** It holds only the gallery `index.html` and this README.
Every exploration — its pages, stylesheets, scripts and assets — lives entirely inside its own
numbered folder, so explorations never collide with each other and any one of them can be added,
changed or removed on its own.

To add another direction:

1. Create the next numbered folder (`01-your-direction/`, `02-…`).
2. Put everything it needs inside it, including its own `index.html`.
3. Add a row to the table above and a card to the gallery (`index.html`).

## Notes

Sketches use made-up sample data. No Allsolve call, backend or API key is connected here.
