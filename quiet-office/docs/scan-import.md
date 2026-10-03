# From a phone scan to a simulated office

The scenario: walk through a real office with a phone, open the scan in Allquiet, mark
where people sit and talk, and get the screen placement for *that* room.

**Status: built.** A scan can be opened and traced in the app. This page records how to scan,
what the export actually contains, what the first real scan taught us, and how to use it.

## How to scan

Needs an iPhone or iPad with LiDAR (the Pro models, iPhone 12 Pro and later).

1. Install Polycam and choose **Room** mode.
2. Lights on. Start in a corner with the phone upright.
3. Walk slowly round the room and sweep every wall from floor to ceiling. Get each corner.
4. Point at the large furniture too: desks, cabinets, meeting tables.
5. **Close the loop**: end where you started, with every wall seen at least once.
6. Export: **Mesh → GLTF**. It is the only free format, and it is enough.

If you have a paid Polycam tier, **Floor Plan → DXF** is better still: it is already the
clean 2D outline, with no slicing needed.

Things that go wrong:

- **Glass walls, windows and mirrors** are mostly invisible to LiDAR and come out as gaps.
- **Range is a few metres.** Walls further away than that are not captured, so in a large
  open office you have to walk to them.
- **Moving fast** loses tracking and bends the walls.
- Give colleagues a heads-up first. The export contains a photo texture of the room.

## What the export contains

Checked on the first scan (`scans/10_3_2026.glb`, Polycam Room mode, GLTF export):

| Property | Value |
|----------|-------|
| Container | Binary glTF 2.0 (`.glb`), no compression extensions |
| Structure | **One node, one mesh, one material** with one JPEG texture |
| Size | 179,035 vertices, 274,087 triangles, 8.9 MB (2 MB of it texture) |
| Units and axes | Metres, **Y is up**. The floor is the x-z plane |
| Origin | Arbitrary: wherever the scan started. Not aligned to the walls |
| Extent | About 8.7 m by 10.9 m, floor to ceiling about 2.7 m |

So even in Room mode the free export is **a single textured surface mesh, not separate walls
and furniture**. There are no named objects to read. A floor plan has to be derived by cutting
the mesh with a horizontal plane.

## What the first scan taught us

Cutting that scan at 0.65 m, 1.2 m and 1.8 m above the floor gives wall *fragments*: one
long straight wall, one angled wall, and two short pieces. The outline is **not closed**; two
sides of the space are missing, most likely glass or walls that were out of range.

That decides the design:

- A scan cannot be turned into a room automatically. The solver needs a closed air region,
  and a real scan has gaps.
- A scan is very good as a **tracing underlay**: the walls that were captured are straight,
  to scale and in the right place.

## Opening a scan in the app

In the app, open the **Edit office** tab.

1. **Open 3D model (.glb).** The file is read in the browser; nothing is uploaded. This works
   for phone scans and for models from CAD or other tools. The app guesses which axis points
   up (the floor is normally the largest flat surface) and the units (whichever of metres,
   centimetres or millimetres gives a believable room height), and says what it guessed. If
   the model lies on its side or is the wrong size, correct it with **Up axis**, **Upside
   down** and **Units** above the plan. The app finds
   the floor (the lowest height holding a large share of the horizontal surface) and cuts the
   mesh 1.2 m above it, which is over the desks and under most wall clutter.
   The ceiling height is read from the scan too, when the scan shows a clear ceiling, and can
   be corrected in the line under the plan.
2. **Adjust.** *Cut height* moves the cut: lower it to about 0.7 m to see desks and tables.
   *Rotate scan* turns the underlay; it starts at the angle that lines most wall length up
   with the screen, and often needs a nudge.
3. **Trace room.** Click each corner of the room in order over the blue lines, closing any
   gaps by eye. Click the first corner again, or press Finish, to close the outline.
   Undo corner and Cancel are in the toolbar; Backspace, Enter and Escape do the same.
4. **Mark up.** The traced outline replaces the room. Desks and screen positions that fall
   outside it are removed; add new ones with *Add desk* and *Add screen position*, and drag
   the conversation to where people talk.
5. **Check in 3D.** The 3D view tab shows the scan as a blue shape inside the room you drew,
   with desks and panels at their real height, so you can see whether the trace fits.
6. **Result.** Switch to the Result tab. The quick estimate has already been redone for the
   new room, and *Run on Allsolve* sends the same room to the backend.

The same editor works without a scan: drag the room corners, use the dot in the middle of a
wall to add a corner, and move everything else by dragging or with the arrow keys. The office
is remembered in the browser; *Reset to demo office* brings the demo back.

How it is built:

- [`frontend/src/scan/glb.ts`](../frontend/src/scan/glb.ts) reads the `.glb`, finds the floor
  and slices. No external library: positions and triangle indices are plain arrays in the
  file's binary chunk. Draco-compressed and quantized files are refused with a message.
- [`frontend/src/components/OfficeEditor.vue`](../frontend/src/components/OfficeEditor.vue)
  is the editor and the tracing tool.
- The office model now has an `outline` (a list of corners) where it used to have a width
  and a height, in both the frontend and the backend.

Limits:

- Tracing is by hand. The app does not detect walls or furniture in the scan.
- Up-axis detection is a guess. A model that is mostly one big wall can fool it, and nothing
  in a mesh says which way is up along the axis, so *Upside down* is always manual.
- Only `.glb` is read, not `.gltf` with separate files, DXF or USDZ.
- Rooms with slanted walls work in the quick estimate. On Allsolve they depend on rotated
  rectangles in the SDK geometry builder, which has not been run yet; see the
  [backend README](../backend/README.md).

## Sample files

Both live in [`scans/`](scans).

| File | What it is |
|------|------------|
| `sample-office.glb` | The Allquiet demo office as a clean 3D model: 16 x 10 m room, closed walls, the 16 desks, a coffee counter and a column. **Generated by a script, not scanned and not downloaded.** Use it to test scan import against a known answer |
| `make-sample-office.mjs` | The script that writes it: `node quiet-office/docs/scans/make-sample-office.mjs` |
| `10_3_2026.glb` | The first real scan. Not committed to the repository by default: it is large and contains photos of a real space |

The sample uses the same container and conventions as the scan (binary glTF 2.0, one mesh,
metres, Y up), with two differences: it has no texture, and its origin is a room corner so
its coordinates match the demo office.

Either file can be viewed in any glTF viewer, for example by dragging it onto
https://gltf-viewer.donmccurdy.com.
