# Snap Sans (working name)

ColdSnap's own typeface. A variable font built on Comfortaa, made easier to read
for kids and dyslexic readers, with a little frost on top.

## The story

Cold Snap is the frost mage spell that makes every cooldown ready again. The font
does the same thing for reading: it gives letters a fresh start. It keeps
Comfortaa's round, friendly shapes, and fixes the parts that make readers stumble.

- **More room.** Every letter gets 15 more units on each side (3% of the em) and
  the space gets 40 more, so words don't blur together.
- **No mirror letters.** In Comfortaa, `d` and `q` are exact mirrors of `b` and
  `p`. Here they end in the same curved foot as Comfortaa's own `l`, so each
  letter has a shape of its own and can't be read flipped.
- **Frost.** A second axis, `FRST` (0–100). At 0 the font is clear and calm for
  reading. Turned up, the dots on i, j, ! ? . : ; and the accents become
  four-point ice sparkles. Use it for titles and logos.
- **❄** A snowflake glyph on U+2744, U+2745 and U+2746 that follows the weight.

`Il1` and `O0` were already easy to tell apart in Comfortaa, so they stay.

## Files

| File | What |
|---|---|
| `fonts/SnapSans[wght,FRST].woff2` | For websites |
| `fonts/SnapSans[wght,FRST].ttf` | To install on Windows / Mac |
| `index.html` | Specimen with Weight / Frost / Size sliders (serve the folder, e.g. `python -m http.server`) |
| `build.py` | Rebuilds everything from `src/` |

## Use on a website

```css
@font-face {
  font-family: "Snap Sans";
  src: url("SnapSans[wght,FRST].woff2") format("woff2");
  font-weight: 300 700;
  font-display: swap;
}
body  { font-family: "Snap Sans", sans-serif; }
h1    { font-variation-settings: "FRST" 100; }
```

## Rebuild or rename

`pip install fonttools brotli`, then `python build.py`.
To rename, change `FAMILY` at the top of `build.py` and rebuild.

## License

SIL Open Font License 1.1, see [OFL.txt](OFL.txt). It's based on
[Comfortaa](https://github.com/alexeiva/comfortaa) by Johan Aakerlund and the Comfortaa
Project Authors. "Comfortaa" is a Reserved Font Name, so this font must never be
called Comfortaa (the build checks for it).
