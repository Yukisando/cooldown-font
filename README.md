# Cooldown Sans

The typeface of [ColdSnap](https://coldsnap.fr). We make serious games, museum exhibits and
learning tools, and the people who play them include children, dyslexic readers and people with
low vision. So we built a typeface for them, and we use it in every project.

**Try it:** [coldsnap.fr/lab/cooldown](https://coldsnap.fr/lab/cooldown/)

## What it does

- **Dyslexia.** `d` and `q` can end in a rounded tail (stylistic set `ss03`), so they are never
  `b` and `p` turned around. Letters sit a little apart so words don't blur together.
- **Low vision.** The height of the lowercase letters is an axis (`XHGT`, 470–600, default
  547): taller for small text and for screens read from a few steps away. Capitals stay put.
- **For fun.** Each letter can tilt its own way (`WOBL`, 0–1), as if written by hand. We use a
  light wobble instead of italics. Dots on i, j and punctuation can turn into little snowflakes
  (`ss02`), and there is a ❄ on U+2744–2746.
- Weights 300 to 700 (`wght`). Round shapes, round ends, no sharp corners.

## Use it on a website

```css
@font-face {
  font-family: "Cooldown Sans";
  src: url("Cooldown-Lab.woff2") format("woff2");
  font-weight: 300 700;
  font-display: swap;
}
body        { font-family: "Cooldown Sans", sans-serif; }
p           { font-feature-settings: "ss03" 1; }            /* tails on d and q */
em, i, cite { font-style: normal; font-variation-settings: "WOBL" 0.35; }
```

Install `fonts/Cooldown-Lab.ttf` to use it on Windows or macOS. Animating
`font-variation-settings` re-draws the text every frame: fine on a short title, not on long text.

## Files

| File | What |
|---|---|
| `fonts/Cooldown-Lab.woff2` / `.ttf` | The variable font |
| `index.html`, `lab/` | Playground with sliders and switches (serve the folder, e.g. `python -m http.server`) |
| `build.py` | Builds the font from `src/` (`pip install fonttools brotli`, then `python build.py`) |

## License

- **The font** (`fonts/`, `src/`) is under the [SIL Open Font License 1.1](OFL.txt), with
  **Reserved Font Name "Cooldown Sans"**. You can use it freely, in personal and commercial
  work. If you share the font files, keep the copyright notice and the license with them. You
  can modify it, but a modified version must not be called Cooldown Sans, and the font may not
  be sold on its own.
- **The code** (`build.py`, `index.html`, `lab/`) is under the [MIT License](LICENSE-CODE.txt).

Made by Nathan de Castro, [ColdSnap](https://coldsnap.fr).
