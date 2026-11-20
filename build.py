"""Build the ColdSnap font from Comfortaa (SIL OFL 1.1).

    python build.py

Reads  src/Comfortaa-VariableFont_wght.ttf
Writes fonts/<Family>[wght,FRST].ttf and .woff2

Changes on top of Comfortaa:
  - more letter and word spacing (easier for dyslexic readers)
  - d and q get the foot of Comfortaa's own l, so they stop being
    mirror images of b and p
  - a new Frost axis (FRST 0-100): i/j tittles and punctuation dots
    turn into four-point ice sparkles
  - a snowflake glyph on U+2744 / U+2745 / U+2746
Rename the font by changing FAMILY below; nothing else needs to change.
"""
import math
from pathlib import Path

from fontTools.designspaceLib import (AxisDescriptor, DesignSpaceDocument,
                                      InstanceDescriptor, SourceDescriptor)
from fontTools.otlLib.builder import buildStatTable
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import (Glyph, GlyphCoordinates,
                                             flagOverlapSimple)
from fontTools.varLib import build as varlib_build
from fontTools.varLib.featureVars import addFeatureVariations
from fontTools.varLib import instancer

FAMILY = "Cooldown"
VERSION = 1.0
DESIGNER = "Nathan de Castro (ColdSnap)"
VENDOR = "CSNP"

SPACING = 15        # extra units on each side of every glyph (UPM 1000)
WORD_SPACING = 40   # extra units on the space on top of that
FROST_MAX = 100
SPARKLE_N = 0.65    # superellipse exponent: 1 = diamond, < 1 = concave star
SPARKLE_K = 1.45    # how far the sparkle points reach, in dot radii

MASTER_WEIGHTS = [300, 400, 700]
STYLES = [(300, "Light"), (400, "Regular"), (500, "Medium"),
          (600, "SemiBold"), (700, "Bold")]

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src" / "Comfortaa-VariableFont_wght.ttf"
BUILD = ROOT / "build"
OUT = ROOT / "fonts"
PS_FAMILY = FAMILY.replace(" ", "")


# ---------------------------------------------------------------- helpers
def ranges(g):
    start = 0
    for end in g.endPtsOfContours:
        yield start, end
        start = end + 1


def area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def append_contour(g, pts, oncurve):
    g.coordinates = GlyphCoordinates(list(g.coordinates) + [(round(x), round(y)) for x, y in pts])
    g.flags = bytearray(list(g.flags) + [1 if o else 0 for o in oncurve])
    g.endPtsOfContours.append(len(g.coordinates) - 1)
    g.numberOfContours = len(g.endPtsOfContours)
    g.flags[0] |= flagOverlapSimple


# ------------------------------------------------------------- d / q feet
def add_foot(font, base, stem_zone, drop):
    """Union Comfortaa's l onto the stem of `base` so it ends in the same foot."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    l = glyf["l"]
    lpts = list(l.coordinates)
    lstem = [p for p in lpts if p[1] > 300]
    lx0, lx1 = min(p[0] for p in lstem), max(p[0] for p in lstem)
    l_curve_y = min(p[1] for p in lpts if p[0] == lx0)       # where the left edge starts to curve
    l_top = max(p[1] for p in lpts)
    l_rsb = hmtx["l"][0] - max(p[0] for p in lpts)

    g = glyf[base]
    bpts = list(g.coordinates)
    bstem = [p for p in bpts if stem_zone(p[1])]
    bx0, bx1 = min(p[0] for p in bstem), max(p[0] for p in bstem)
    scale = (bx1 - bx0) / (lx1 - lx0)
    lc, bc = (lx0 + lx1) / 2, (bx0 + bx1) / 2

    if drop:   # q: foot sits on the descender; trim both stems so nothing pokes out
        b_bottom = min(p[1] for p in bpts)
        dy = b_bottom
        cap_lift = (l_curve_y + dy) - b_bottom
        cap_y = b_bottom + (bx1 - bx0) / 2 + 1
        g.coordinates = GlyphCoordinates(
            [(x, y + cap_lift) if y <= cap_y else (x, y) for x, y in bpts])
        hide_top = 200                                       # l's top cap ends inside q's stem
        foot = [(bc + (x - lc) * scale, y + dy - ((l_top + dy) - hide_top if y >= 700 else 0))
                for x, y in lpts]
    else:      # d: same baseline, l's stem simply overlaps d's stem
        foot = [(bc + (x - lc) * scale, y) for x, y in lpts]

    append_contour(g, foot, [f & 1 for f in l.flags])
    old_adv = hmtx[base][0]
    new_adv = max(old_adv, round(max(p[0] for p in foot) + l_rsb))
    delta = new_adv - old_adv
    hmtx[base] = (new_adv, hmtx[base][1])
    for name in font.getGlyphOrder():             # dcaron, dcroat, ... follow d
        c = glyf[name]
        if c.isComposite() and c.components[0].glyphName == base:
            hmtx[name] = (hmtx[name][0] + delta, hmtx[name][1])


# --------------------------------------------------------------- snowflake
def arc(cx, cy, r, a0, a1, segs=2):
    out, da = [], (a1 - a0) / segs
    for i in range(segs):
        am, ae = a0 + da * (i + .5), a0 + da * (i + 1)
        rc = r / math.cos(da / 2)
        out += [((cx + rc * math.cos(am), cy + rc * math.sin(am)), False),
                ((cx + r * math.cos(ae), cy + r * math.sin(ae)), True)]
    return out


def capsule(p1, p2, w):
    """Clockwise round-capped stroke from p1 to p2, fixed point count."""
    (x1, y1), (x2, y2), r = p1, p2, w / 2
    a = math.atan2(y2 - y1, x2 - x1)
    nx, ny = -math.sin(a) * r, math.cos(a) * r
    pts = [((x1 + nx, y1 + ny), True), ((x2 + nx, y2 + ny), True)]
    pts += arc(x2, y2, r, a + math.pi / 2, a - math.pi / 2)
    pts += [((x1 - nx, y1 - ny), True)]
    pts += arc(x1, y1, r, a - math.pi / 2, a - 3 * math.pi / 2)[:-1]
    return [p for p, _ in pts], [o for _, o in pts]


def add_snowflake(font, stem):
    name = "uni2744"
    w = stem * 0.8
    arm, cy = 330, 390
    half = arm * math.cos(math.radians(30)) + w / 2
    adv = round(2 * half + 120)
    cx = adv / 2
    g = Glyph()
    g.numberOfContours, g.endPtsOfContours = 0, []
    g.coordinates, g.flags = GlyphCoordinates([]), bytearray()
    g.program = ttProgram.Program()
    g.program.fromBytecode(b"")
    for k in range(6):
        a = math.radians(90 + 60 * k)
        tip = (cx + arm * math.cos(a), cy + arm * math.sin(a))
        for pts in [capsule((cx, cy), tip, w)]:
            append_contour(g, *pts)
        bx, by = cx + arm * .55 * math.cos(a), cy + arm * .55 * math.sin(a)
        for side in (-1, 1):
            b = a + side * math.radians(50)
            append_contour(g, *capsule((bx, by), (bx + arm * .33 * math.cos(b),
                                                   by + arm * .33 * math.sin(b)), w))
    order = font.getGlyphOrder()
    if name not in order:
        order.append(name)
        font.setGlyphOrder(order)
    font["glyf"].glyphOrder = order
    font["glyf"][name] = g
    font["hmtx"][name] = (adv, 0)
    for t in font["cmap"].tables:
        if t.isUnicode():
            for cp in (0x2744, 0x2745, 0x2746):
                t.cmap[cp] = name


# -------------------------------------------------------------- spacing
def add_spacing(font):
    glyf, hmtx = font["glyf"], font["hmtx"]
    space = {font.getBestCmap().get(cp) for cp in (0x20, 0xA0)}
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.numberOfContours > 0:
            g.coordinates.translate((SPACING, 0))
        adv, lsb = hmtx[name]
        if adv > 0:
            adv += 2 * SPACING + (WORD_SPACING if name in space else 0)
        hmtx[name] = (adv, lsb)


# ------------------------------------------------------------ frost dots
def find_dots(font):
    """(glyph, contour index) of every round dot, decided once on the Regular master."""
    glyf, dots = font["glyf"], []
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.numberOfContours <= 0:
            continue
        pts = list(g.coordinates)
        cs = [(s, e) for s, e in ranges(g)]
        for i, (s, e) in enumerate(cs):
            c, fl = pts[s:e + 1], g.flags[s:e + 1]
            xs, ys = [p[0] for p in c], [p[1] for p in c]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if len(c) != 12 or sum(f & 1 for f in fl) != 4:
                continue
            if not (60 <= w <= 175 and abs(w - h) <= 14 and area(c) < 0):
                continue
            inside = any(area(pts[s2:e2 + 1]) > 0 and min(xs) <= min(p[0] for p in pts[s2:e2 + 1])
                         and max(p[0] for p in pts[s2:e2 + 1]) <= max(xs)
                         for j, (s2, e2) in enumerate(cs) if j != i)
            if not inside:
                dots.append((name, i))
    return dots


def frost(font, dots):
    glyf = font["glyf"]
    for name, idx in dots:
        g = glyf[name]
        s, e = list(ranges(g))[idx]
        pts = list(g.coordinates)
        c = pts[s:e + 1]
        xs, ys = [p[0] for p in c], [p[1] for p in c]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = (max(xs) - min(xs) + max(ys) - min(ys)) / 4
        for i in range(s, e + 1):
            t = math.atan2(pts[i][1] - cy, pts[i][0] - cx)
            ca, sa = abs(math.cos(t)), abs(math.sin(t))
            rr = r * SPARKLE_K / (ca ** SPARKLE_N + sa ** SPARKLE_N) ** (1 / SPARKLE_N)
            pts[i] = (round(cx + rr * math.cos(t)), round(cy + rr * math.sin(t)))
        g.coordinates = GlyphCoordinates(pts)


# ----------------------------------------------------------------- masters
def strip_hinting(font):
    for tag in ("prep", "fpgm", "cvt "):
        if tag in font:
            del font[tag]
    for g in font["glyf"].glyphs.values():
        if hasattr(g, "program"):
            g.program = ttProgram.Program()
            g.program.fromBytecode(b"")


def source_without_featvars():
    """Comfortaa swaps one glyph (₴) at heavy weights via FeatureVariations;
    drop it so all masters share one GSUB, and re-add it on the final font."""
    font = TTFont(SRC)
    gsub = font["GSUB"].table
    swaps = []
    for rec in gsub.FeatureVariations.FeatureVariationRecord:
        box = {font["fvar"].axes[c.AxisIndex].axisTag: (c.FilterRangeMinValue, c.FilterRangeMaxValue)
               for c in rec.ConditionSet.ConditionTable}
        mapping = {}
        for s in rec.FeatureTableSubstitution.SubstitutionRecord:
            for li in s.Feature.LookupListIndex:
                for st in gsub.LookupList.Lookup[li].SubTable:
                    mapping.update(st.mapping)
        swaps.append(([box], mapping))
    gsub.FeatureVariations = None
    gsub.Version = 0x00010000
    return font, swaps


def make_master(wght, frost_on, dots):
    font = instancer.instantiateVariableFont(source_without_featvars()[0], {"wght": wght})
    strip_hinting(font)
    stem = font["glyf"]["I"].xMax - font["glyf"]["I"].xMin
    add_foot(font, "d", lambda y: y > 600, drop=False)
    add_foot(font, "q", lambda y: y < -100, drop=True)
    add_snowflake(font, stem)
    add_spacing(font)
    if frost_on:
        frost(font, dots)
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        g.recalcBounds(glyf)
        font["hmtx"][name] = (font["hmtx"][name][0], getattr(g, "xMin", 0))
    return font


def wght_map(src):
    """Carry Comfortaa's avar over as a designspace user->design map."""
    seg = src["avar"].segments["wght"]
    def user(n):
        return 400 + n * (300 if n > 0 else 100)
    return sorted((user(n), user(m)) for n, m in seg.items())


def set_names(vf):
    name = vf["name"]
    copyright_ = name.getDebugName(0) + f" Copyright 2026 {DESIGNER}."
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 25) or (
                rec.nameID in (8, 9, 10, 11, 12) and "omfortaa" in rec.toUnicode()):
            name.removeNames(nameID=rec.nameID)
    for nid, val in [(0, copyright_), (1, FAMILY), (2, "Regular"),
                     (3, f"{VERSION:.3f};{VENDOR};{PS_FAMILY}-Regular"),
                     (4, f"{FAMILY} Regular"), (5, f"Version {VERSION:.3f}"),
                     (6, f"{PS_FAMILY}-Regular"), (8, "ColdSnap"), (9, DESIGNER),
                     (11, "https://coldsnap.fr"), (25, PS_FAMILY)]:
        name.setName(val, nid, 3, 1, 0x409)
    leftovers = [r for r in name.names if r.nameID != 0 and "omfortaa" in r.toUnicode()]
    assert not leftovers, f"Reserved Font Name still present: {leftovers}"
    vf["OS/2"].achVendID = VENDOR
    vf["head"].fontRevision = VERSION


def main():
    BUILD.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    src = TTFont(SRC)
    dots = find_dots(make_master(400, False, []))

    ds = DesignSpaceDocument()
    wght = AxisDescriptor()
    wght.tag, wght.name, wght.minimum, wght.default, wght.maximum = "wght", "Weight", 300, 400, 700
    wght.map = wght_map(src)
    frst = AxisDescriptor()
    frst.tag, frst.name, frst.minimum, frst.default, frst.maximum = "FRST", "Frost", 0, 0, FROST_MAX
    ds.addAxis(wght)
    ds.addAxis(frst)
    to_design = dict(wght.map)

    for w in MASTER_WEIGHTS:
        for f in (0, FROST_MAX):
            path = BUILD / f"master-{w}-{f}.ttf"
            make_master(w, f > 0, dots).save(path)
            s = SourceDescriptor()
            s.path, s.location = str(path), {"Weight": to_design[w], "Frost": f}
            ds.addSource(s)

    def design(user_w):
        pts = sorted(to_design.items())
        for (u0, d0), (u1, d1) in zip(pts, pts[1:]):
            if u0 <= user_w <= u1:
                return d0 + (d1 - d0) * (user_w - u0) / (u1 - u0)

    for f in (0, FROST_MAX):
        for w, style in STYLES:
            style = f"{style} Frost" if f else style
            i = InstanceDescriptor()
            i.familyName, i.styleName = FAMILY, style
            i.postScriptFontName = f"{PS_FAMILY}-{style.replace(' ', '')}"
            i.location = {"Weight": design(w), "Frost": f}
            ds.addInstance(i)

    vf, _, _ = varlib_build(ds)
    addFeatureVariations(vf, source_without_featvars()[1], featureTag="rvrn")
    set_names(vf)
    buildStatTable(vf, [
        dict(tag="wght", name="Weight", values=[
            dict(value=w, name=s, flags=0x2 if w == 400 else 0) for w, s in STYLES]),
        dict(tag="FRST", name="Frost", values=[
            dict(value=0, name="Normal", flags=0x2), dict(value=FROST_MAX, name="Frost")]),
    ])
    out = OUT / f"{PS_FAMILY}[wght,FRST].ttf"
    vf.save(out)
    vf.flavor = "woff2"
    vf.save(out.with_suffix(".woff2"))
    print(f"{out.name}: {len(dots)} dots frosted, {len(vf.getGlyphOrder())} glyphs")


if __name__ == "__main__":
    main()
