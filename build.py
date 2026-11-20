"""Build Cooldown, ColdSnap's typeface, from Comfortaa (SIL OFL 1.1).

    python build.py

Reads  src/Comfortaa-VariableFont_wght.ttf
Writes fonts/Cooldown-Lab.ttf and .woff2

Fixed changes on top of Comfortaa:
  - more letter and word spacing (easier for dyslexic readers)
  - a snowflake glyph on U+2744 / U+2745 / U+2746
  - ss02: i/j tittles and punctuation dots become ice sparkles (on/off)

Axes:
  wght  300-700  weight (Comfortaa's own)
  XHGT  520-600  x-height in units (Comfortaa: 547)
  TAIL  0-1      d and q foot: 0 = Comfortaa (mirror of b/p), 1 = full foot like l
  WOBL  0-1      goofy: every letter tilts its own way, up to WOBBLE_DEG degrees
Rename the font by changing FAMILY below.
"""
import copy
import math
import unicodedata
import zlib
from pathlib import Path

from fontTools.designspaceLib import (AxisDescriptor, DesignSpaceDocument,
                                      InstanceDescriptor, SourceDescriptor)
from fontTools.otlLib.builder import buildStatTable
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import (Glyph, GlyphCoordinates,
                                             flagOverlapSimple)
from fontTools.varLib import build as varlib_build
from fontTools.varLib import instancer
from fontTools.varLib.featureVars import addFeatureVariations

FAMILY = "Cooldown"
VERSION = 1.2
DESIGNER = "Nathan de Castro (ColdSnap)"
VENDOR = "CSNP"
OUT_NAME = "Cooldown-Lab"

SPACING = 15             # extra units on each side of every glyph (UPM 1000)
WORD_SPACING = 40        # extra units on the space on top of that
SPARKLE_N = 0.65         # superellipse exponent: 1 = diamond, < 1 = concave star
SPARKLE_K = 1.45         # how far the sparkle points reach, in dot radii
WOBBLE_DEG = 10          # max tilt per letter at WOBL 1
XH = 547                 # Comfortaa's x-height
ASC = 781

# tag: (name, min, default, max)
AXES = {
    "wght": ("Weight", 300, 400, 700),
    "XHGT": ("x-height", 520, XH, 600),
    "TAIL": ("Tail", 0, 1, 1),
    "WOBL": ("Wobble", 0, 0, 1),
}
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


def map_points(g, fn):
    g.coordinates = GlyphCoordinates([fn(x, y) for x, y in g.coordinates])


def empty_glyph():
    g = Glyph()
    g.numberOfContours, g.endPtsOfContours = 0, []
    g.coordinates, g.flags = GlyphCoordinates([]), bytearray()
    g.program = ttProgram.Program()
    g.program.fromBytecode(b"")
    return g


def add_glyph(font, name, glyph, metrics):
    order = font.getGlyphOrder()
    if name not in order:
        order.append(name)
        font.setGlyphOrder(order)
    font["glyf"].glyphOrder = order
    font["glyf"][name] = glyph
    font["hmtx"][name] = metrics


# ------------------------------------------------------------- d / q feet
def add_foot(font, base, stem_zone, drop, tail):
    """Union Comfortaa's l onto the stem of `base` so it ends in the same foot.
    tail 0 keeps the same points but folds the foot away inside the stem."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    l = glyf["l"]
    lpts = list(l.coordinates)
    lstem = [p for p in lpts if p[1] > 300]
    lx0, lx1 = min(p[0] for p in lstem), max(p[0] for p in lstem)
    l_curve_y = min(p[1] for p in lpts if p[0] == lx0)
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
        cap_lift = ((l_curve_y + dy) - b_bottom) * tail
        cap_y = b_bottom + (bx1 - bx0) / 2 + 1
        g.coordinates = GlyphCoordinates(
            [(x, y + cap_lift) if y <= cap_y else (x, y) for x, y in bpts])
        hide_top = 200
        foot = [(bc + (x - lc) * scale, y + dy - ((l_top + dy) - hide_top if y >= 700 else 0))
                for x, y in lpts]
        anchor = (bc, b_bottom + (bx1 - bx0) / 2)   # centre of the stem cap
    else:
        foot = [(bc + (x - lc) * scale, y) for x, y in lpts]
        anchor = (bc, 175)   # low on the stem, still inside the bowl
    if not tail:
        # The curve and foot collapse onto one point inside the stem, so in
        # between they shrink smoothly towards it (a smaller, thinner foot).
        foot = [anchor if lp[1] <= l_curve_y else (fp[0], max(fp[1], anchor[1]))
                for lp, fp in zip(lpts, foot)]

    append_contour(g, foot, [f & 1 for f in l.flags])
    old_adv = hmtx[base][0]
    new_adv = max(old_adv, round(max(p[0] for p in foot) + l_rsb)) if tail else old_adv
    delta = new_adv - old_adv
    hmtx[base] = (new_adv, hmtx[base][1])
    for name in font.getGlyphOrder():
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
    (x1, y1), (x2, y2), r = p1, p2, w / 2
    a = math.atan2(y2 - y1, x2 - x1)
    nx, ny = -math.sin(a) * r, math.cos(a) * r
    pts = [((x1 + nx, y1 + ny), True), ((x2 + nx, y2 + ny), True)]
    pts += arc(x2, y2, r, a + math.pi / 2, a - math.pi / 2)
    pts += [((x1 - nx, y1 - ny), True)]
    pts += arc(x1, y1, r, a - math.pi / 2, a - 3 * math.pi / 2)[:-1]
    return [p for p, _ in pts], [o for _, o in pts]


def add_snowflake(font):
    stem = font["glyf"]["I"].xMax - font["glyf"]["I"].xMin
    w = stem * 0.8
    arm, cy = 330, 390
    adv = round(2 * (arm * math.cos(math.radians(30)) + w / 2) + 120)
    cx = adv / 2
    g = empty_glyph()
    for k in range(6):
        a = math.radians(90 + 60 * k)
        append_contour(g, *capsule((cx, cy), (cx + arm * math.cos(a), cy + arm * math.sin(a)), w))
        bx, by = cx + arm * .55 * math.cos(a), cy + arm * .55 * math.sin(a)
        for side in (-1, 1):
            b = a + side * math.radians(50)
            append_contour(g, *capsule((bx, by), (bx + arm * .33 * math.cos(b),
                                                   by + arm * .33 * math.sin(b)), w))
    add_glyph(font, "uni2744", g, (adv, 0))
    for t in font["cmap"].tables:
        if t.isUnicode():
            for cp in (0x2744, 0x2745, 0x2746):
                t.cmap[cp] = "uni2744"


# --------------------------------------------------------------- x-height
def lowercase_set(font):
    glyf, simple, comps = font["glyf"], set(), set()
    def base_of(n):
        while glyf[n].isComposite():
            n = glyf[n].components[0].glyphName
        return n
    for cp, n in font.getBestCmap().items():
        if unicodedata.category(chr(cp)) == "Ll":
            if glyf[n].isComposite():
                comps.add(n)
            simple.add(base_of(n))
    return simple, comps


def raise_xheight(font, d):
    simple, comps = lowercase_set(font)
    glyf = font["glyf"]
    def t(y):
        if y <= XH * .25:
            return 0
        if y <= XH * .75:
            return (y - XH * .25) / (XH * .5)
        if y <= XH + 30:
            return 1
        return max(0, (ASC - y) / (ASC - XH - 30))
    for n in simple:
        if glyf[n].numberOfContours > 0:
            map_points(glyf[n], lambda x, y: (x, round(y + d * t(y))))
    for n in comps:     # accents and tittles above a lowercase base move up with it
        for c in glyf[n].components[1:]:
            cg = glyf[c.glyphName]
            cg.recalcBounds(glyf)
            if getattr(cg, "yMin", 0) + c.y > XH * .5:
                c.y += d


# --------------------------------------------------------- sparkles (ss02)
def find_dots(font):
    glyf, dots = font["glyf"], []
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.numberOfContours <= 0:
            continue
        pts = list(g.coordinates)
        cs = list(ranges(g))
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


def sparkle(g, idx):
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


def add_sparkle_feature(font, dots):
    glyf, hmtx = font["glyf"], font["hmtx"]
    by_glyph = {}
    for n, i in dots:
        by_glyph.setdefault(n, []).append(i)
    targets = set(by_glyph)
    changed = True
    while changed:
        changed = False
        for n in font.getGlyphOrder():
            g = glyf[n]
            if n not in targets and g.isComposite() and any(c.glyphName in targets for c in g.components):
                targets.add(n)
                changed = True
    mapping = {}
    gdef = font["GDEF"].table.GlyphClassDef.classDefs if "GDEF" in font else {}
    for n in [n for n in font.getGlyphOrder() if n in targets]:
        new = copy.deepcopy(glyf[n])
        if new.isComposite():
            for c in new.components:
                if c.glyphName in targets:
                    c.glyphName += ".ss02"
        else:
            for i in by_glyph[n]:
                sparkle(new, i)
        add_glyph(font, n + ".ss02", new, hmtx[n])
        if n in gdef:
            gdef[n + ".ss02"] = gdef[n]
        mapping[n] = n + ".ss02"

    gsub = font["GSUB"].table
    lookup = ot.Lookup()
    lookup.LookupType, lookup.LookupFlag = 1, 0
    sub = ot.SingleSubst()
    sub.mapping = mapping
    lookup.SubTable, lookup.SubTableCount = [sub], 1
    gsub.LookupList.Lookup.append(lookup)
    gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
    rec = ot.FeatureRecord()
    rec.FeatureTag = "ss02"
    rec.Feature = ot.Feature()
    rec.Feature.FeatureParams = None
    rec.Feature.LookupListIndex = [gsub.LookupList.LookupCount - 1]
    rec.Feature.LookupCount = 1
    gsub.FeatureList.FeatureRecord.append(rec)
    gsub.FeatureList.FeatureCount = len(gsub.FeatureList.FeatureRecord)
    fi = gsub.FeatureList.FeatureCount - 1
    for sr in gsub.ScriptList.ScriptRecord:
        for ls in [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]:
            if ls is not None:
                ls.FeatureIndex.append(fi)
                ls.FeatureCount = len(ls.FeatureIndex)


# ------------------------------------------------- decompose, air, wobble
def decompose_all(font):
    """Flatten composites so accented letters can tilt as one piece."""
    glyf = font["glyf"]
    flat = {}
    for n in font.getGlyphOrder():
        g = glyf[n]
        if g.isComposite():
            coords, ends, flags = g.getCoordinates(glyf)
            flat[n] = (list(coords), list(ends), [f & 1 for f in flags])
    for n, (coords, ends, flags) in flat.items():
        g = empty_glyph()
        g.coordinates = GlyphCoordinates([(round(x), round(y)) for x, y in coords])
        g.flags = bytearray(flags)
        g.endPtsOfContours = ends
        g.numberOfContours = len(ends)
        if ends:
            g.flags[0] |= flagOverlapSimple
        glyf[n] = g


def add_air(font):
    glyf, hmtx = font["glyf"], font["hmtx"]
    space = {font.getBestCmap().get(cp) for cp in (0x20, 0xA0)}
    for n in font.getGlyphOrder():
        g = glyf[n]
        if g.numberOfContours > 0:
            g.coordinates.translate((SPACING, 0))
        adv, lsb = hmtx[n]
        if adv > 0:
            adv += 2 * SPACING + (WORD_SPACING if n in space else 0)
        hmtx[n] = (adv, lsb)


def wobble(font):
    """Tilt every glyph around its own centre by a fixed pseudo-random angle."""
    glyf = font["glyf"]
    for n in font.getGlyphOrder():
        g = glyf[n]
        if g.numberOfContours <= 0:
            continue
        h = zlib.crc32(n.removesuffix(".ss02").encode())
        mag = 0.35 + 0.65 * ((h & 0xFFFF) / 0xFFFF)
        deg = WOBBLE_DEG * mag * (1 if h & 0x10000 else -1)
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        g.recalcBounds(glyf)
        cx, cy = (g.xMin + g.xMax) / 2, (g.yMin + g.yMax) / 2
        map_points(g, lambda x, y: (round(cx + (x - cx) * ca - (y - cy) * sa),
                                    round(cy + (x - cx) * sa + (y - cy) * ca)))


# ----------------------------------------------------------------- masters
def source_without_featvars():
    """Comfortaa swaps one glyph at heavy weights via FeatureVariations; drop it
    so all masters share one GSUB, and re-add it on the final font."""
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


def prepared(wght, tail=1):
    font = instancer.instantiateVariableFont(source_without_featvars()[0], {"wght": wght})
    for tag in ("prep", "fpgm", "cvt "):
        if tag in font:
            del font[tag]
    for g in font["glyf"].glyphs.values():
        if hasattr(g, "program"):
            g.program = ttProgram.Program()
            g.program.fromBytecode(b"")
    add_foot(font, "d", lambda y: y > 600, drop=False, tail=tail)
    add_foot(font, "q", lambda y: y < -100, drop=True, tail=tail)
    add_snowflake(font)
    return font


def make_master(loc, dots):
    v = {t: a[2] for t, a in AXES.items()} | loc
    font = prepared(v["wght"], v["TAIL"])
    if v["XHGT"] != XH:
        raise_xheight(font, v["XHGT"] - XH)
    add_sparkle_feature(font, dots)
    decompose_all(font)
    add_air(font)
    if v["WOBL"]:
        wobble(font)
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        g.recalcBounds(glyf)
        font["hmtx"][name] = (font["hmtx"][name][0], getattr(g, "xMin", 0))
    return font


def wght_map(src):
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
    dots = find_dots(prepared(400))

    ds = DesignSpaceDocument()
    to_design = dict(wght_map(src))
    for tag, (nm, lo, df, hi) in AXES.items():
        a = AxisDescriptor()
        a.tag, a.name, a.minimum, a.default, a.maximum = tag, nm, lo, df, hi
        if tag == "wght":
            a.map = sorted(to_design.items())
        ds.addAxis(a)

    # weight masters, plus each other axis' extremes at every master weight
    locs = [{"wght": w} for w in MASTER_WEIGHTS]
    for tag, (_, lo, df, hi) in AXES.items():
        if tag == "wght":
            continue
        for ext in (lo, hi):
            if ext != df:
                locs += [{"wght": w, tag: ext} for w in MASTER_WEIGHTS]
    for i, loc in enumerate(locs):
        path = BUILD / f"master-{i:02d}.ttf"
        make_master(loc, dots).save(path)
        s = SourceDescriptor()
        s.path = str(path)
        s.location = {AXES[t][0]: (to_design[val] if t == "wght" else val) for t, val in loc.items()}
        ds.addSource(s)
        print(f"master {i + 1}/{len(locs)} {loc}")

    def design(user_w):
        pts = sorted(to_design.items())
        for (u0, d0), (u1, d1) in zip(pts, pts[1:]):
            if u0 <= user_w <= u1:
                return d0 + (d1 - d0) * (user_w - u0) / (u1 - u0)

    for w, style in STYLES:
        i = InstanceDescriptor()
        i.familyName, i.styleName = FAMILY, style
        i.postScriptFontName = f"{PS_FAMILY}-{style}"
        i.location = {"Weight": design(w)}
        ds.addInstance(i)

    vf, _, _ = varlib_build(ds)
    addFeatureVariations(vf, source_without_featvars()[1], featureTag="rvrn")
    set_names(vf)
    buildStatTable(vf, [
        dict(tag="wght", name="Weight", values=[
            dict(value=w, name=s, flags=0x2 if w == 400 else 0) for w, s in STYLES]),
    ] + [dict(tag=t, name=a[0], values=[dict(value=a[2], name="Normal", flags=0x2)])
         for t, a in AXES.items() if t != "wght"])
    out = OUT / f"{OUT_NAME}.ttf"
    vf.save(out)
    vf.flavor = "woff2"
    vf.save(out.with_suffix(".woff2"))
    print(f"{out.name}: axes {', '.join(AXES)}, {len(dots)} dotted glyphs, {len(vf.getGlyphOrder())} glyphs")


if __name__ == "__main__":
    main()
