# Cooldown

ColdSnap's own typeface. A variable font built on Comfortaa, made easier to read
for kids and dyslexic readers, with a little frost on top.

## The story

Cold Snap is the frost mage spell that makes every cooldown ready again. The font
does the same thing for reading: it gives letters a fresh start. It keeps
Comfortaa's round, friendly shapes, and fixes the parts that make readers stumble.

- **More room.** Every letter gets 6 more units on each side (a touch airier than Comfortaa) and
  the space gets 20 more, so words stay clearly apart.
- **No mirror letters (optional).** In Comfortaa, `d` and `q` are exact mirrors
  of `b` and `p`. Switch on `ss03` (`font-feature-settings: "ss03" 1`) and they
  end in a rounded foot like Comfortaa's own `l`. Off by default.
- **Sparkles.** Stylistic set `ss02` (on/off, `font-feature-settings: "ss02" 1`):
  the dots on i, j, ! ? . : ; and the accents become four-point ice sparkles.
- **Axes.** Weight 300–700, x-height `XHGT` 470–600 (547 = Comfortaa),
  Wobble `WOBL` 0–1 (each letter tilts its own way, up to 10°, for a goofy look).
  Spacing is fixed at +6 per side; tracking is a CSS job.
- **❄** A snowflake glyph on U+2744, U+2745 and U+2746 that follows the weight.

- **Soft everywhere.** Every sharp corner is rounded, and where a curve meets a
  stem (b, d, p, q, a, g, n...) it melts into it instead of making a sharp notch.

`Il1` and `O0` were already easy to tell apart in Comfortaa, so they stay.

## Files

| File | What |
|---|---|
| `fonts/Cooldown-Lab.woff2` | For websites |
| `fonts/Cooldown-Lab.ttf` | To install on Windows / Mac |
| `index.html` | Lab page with a slider per axis (serve the folder, e.g. `python -m http.server`) |
| `build.py` | Rebuilds everything from `src/` |

## Use on a website

```css
@font-face {
  font-family: "Cooldown";
  src: url("Cooldown-Lab.woff2") format("woff2");
  font-weight: 300 700;
  font-display: swap;
}
body  { font-family: "Cooldown", sans-serif; }
h1    { font-feature-settings: "ss02" 1; }
```

## Rebuild or rename

`pip install fonttools brotli`, then `python build.py`.
To rename, change `FAMILY` at the top of `build.py` and rebuild.

## License

SIL Open Font License 1.1, see [OFL.txt](OFL.txt). It's based on
[Comfortaa](https://github.com/alexeiva/comfortaa) by Johan Aakerlund and the Comfortaa
Project Authors. "Comfortaa" is a Reserved Font Name, so this font must never be
called Comfortaa (the build checks for it).
