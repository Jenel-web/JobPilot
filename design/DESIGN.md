# JobPilot design system

Source: the "JobPilot design system" Design artifact (claude.ai). This folder is the copy the code follows.

- `tokens.css`: every colour, font, radius and size as CSS variables. **The single source of truth for values.**
- `screens/*.html`: static mockups of every screen (open them in a browser). **The source of truth for layout and copy.**
  - `Main.html` foundations · `Components.html` shared components · `Patterns.html` app shell + Review batch
  - `Home`, `Review`, `Applications`, `Questions`, `Emails`, `Profile`, `Settings`, `Activity`, `Onboarding`, `States`
  - These files reference a `support.js` from the design tool that isn't included. They still render, because all styles are inline.

## Principles

1. A calm desktop work tool: dense but not crowded. Desktop only (1280 px and wider).
2. Colour carries meaning. Each status keeps the same colour on every screen, and a status chip always shows the status as text too.
3. Surfaces separate with a 1 px line, not shadows. Only the drawer and dialogs have a shadow (`--jp-shadow-overlay`).
4. One primary (Spruce) button per view. Button labels name the result: "Submit approved (5)", not "Submit".
5. Risky actions (STOP, Live mode, Submit) use a confirm dialog. In it, Cancel has default focus and the risky button is red.

## Type

| Use | Font | Size / weight |
|---|---|---|
| Page title | Newsreader | 28 px / 500 |
| Big numbers (stat cards, score in detail) | Newsreader | 36–40 px / 500, tabular figures |
| Section heading | Geist | 20 px / 600 |
| Card / panel heading | Geist | 14–16 px / 600 |
| Lead text | Geist | 16 px / 400 |
| Body and table text | Geist | 14 px / 400 |
| Labels, helper text | Geist | 13 px / 500 |
| Small tags | Geist | 12 px |

Newsreader is only for page titles and large numbers. Numbers in tables use `font-variant-numeric: tabular-nums`.

## Space and layout

- Spacing unit 4 px; use 8, 12, 16, 24, 32.
- Top bar 56 px fixed · sidebar 220 px (64 px collapsed) · detail drawer 520 px from the right · table rows 36 px.
- Radius: 6 px for controls, 10 px for cards, full pill for chips only.
- List + detail screens split 40 / 60.
- Main content padding 24 px 28 px.

## Components (match `screens/Components.html`)

| Component | Spec |
|---|---|
| StatusChip | 24 px tall pill, 0 10px padding, 13 px / 500, status text colour on status bg |
| ScoreBadge | Ring that fills to the value (40–48 px). Green `#15803D` ≥ 80, amber `#B45309` 60–79, grey `#5F6B64` < 60; number centred in the same colour |
| ModeBadge | 26 px, radius 6, 13 px / 600, uppercase. MOCK grey, DRY RUN blue on blue tint, LIVE white on red |
| FlagMarker | Amber triangle + count, e.g. "▲ 2" |
| Button primary | 36 px, radius 6, Spruce bg, white 14 px / 600. Disabled = 45% opacity |
| Button secondary | 36 px, 1 px `--jp-line-strong` border, surface bg, 14 px / 500 |
| Button danger | Same as primary with `--jp-danger` |
| Button link | Transparent, Spruce text, 14 px / 500 |
| FilterChip | 28 px pill. Active = ink bg + white text; inactive = border + surface |
| NavItem | 36 px, radius 6, 14 px. Active = brand tint bg, brand text, 600. Count badge: 20 px pill (blue for Review, amber for Questions) |
| Toast | Ink bg, white 14 px, radius 10, bottom-right, 4 s |
| Banner | Amber or danger bg + border, radius 10, message + exactly one fix button; stays until fixed |
| AlertRow (Home "Needs you") | Surface card with 3 px coloured left border, message left, action link right |
| StatCard | Surface card, 13 px label, 36 px Newsreader number, 13 px note (green for good, red for bad) |
| EmptyState | Icon + one sentence + one button, dashed 1 px border |
| ConfirmDialog | Centred, radius 10, overlay shadow, title 18 px / 600, body lists exactly what will happen |
| DataTable | Sticky header (13 px / 500, ink-2), 36 px rows, `--jp-line-soft` dividers, row hover, row click opens Drawer |
| Drawer | 520 px from the right, overlay shadow, close X |
| AI-guess field | Amber bg + amber border + "AI guess, check this" in amber text |

## Not defined yet (ask before inventing)

- Dark-mode values for tints, soft lines and amber.
- Icon set (the mockups use simple inline SVG).
