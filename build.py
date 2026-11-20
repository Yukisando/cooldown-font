"""Build Cooldown, ColdSnap's typeface, from Comfortaa (SIL OFL 1.1).

    python build.py

Reads  src/Comfortaa-VariableFont_wght.ttf
Writes fonts/Cooldown-Lab.ttf and .woff2

Fixed changes on top of Comfortaa:
  - more letter and word spacing (easier for dyslexic readers)
  - a snowflake glyph on U+2744 / U+2745 / U+2746
  - ss02: i/j tittles and punctuation dots become little snowflakes (on/off)
  - ss03: d and q end in a rounded foot like the l (on/off, off by default)

Axes:
  wght  300-700  weight (Comfortaa's own)
  XHGT  470-600  x-height in units (Comfortaa: 547)
  WOBL  0-1      goofy: every letter tilts its own way, up to WOBBLE_DEG degrees
Rename the font by changing FAMILY below.
"""
import bisect
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

FAMILY = "Cooldown Sans"
VERSION = 1.7
DESIGNER = "Nathan de Castro (ColdSnap)"
VENDOR = "CSNP"
OUT_NAME = "Cooldown-Lab"

SPACING = 6              # extra units on each side of every glyph (UPM 1000)
WORD_SPACING = 20        # extra units on the space on top of that
FLAKE_REACH = 1.6        # snowflake arm length, in dot radii (ss02)
FLAKE_STROKE = 0.42      # snowflake stroke width, in dot radii
WOBBLE_DEG = 10          # max tilt per letter at WOBL 1
FILLET = 35              # radius of the round where two straight edges meet
BLEND = 50               # how far up a stem a curve melts into it
CORNER_DEG = 35          # a turn sharper than this counts as a corner
XH = 547                 # Comfortaa's x-height
ASC = 781

# tag: (name, min, default, max)
AXES = {
    "wght": ("Weight", 300, 400, 700),
    "XHGT": ("x-height", 470, XH, 600),
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
FOOT_SAMPLES = 16


def stroke_path(x0, y_start, yc, rx, ry):
    """Dense centreline: straight down to yc, then a quarter ellipse curling right."""
    pts = [(x0, y_start + (yc - y_start) * i / 60) for i in range(61)]
    if rx > .5 and ry > .5:
        pts += [(x0 + rx + rx * math.cos(th), yc + ry * math.sin(th))
                for th in (math.pi + math.pi / 2 * i / 120 for i in range(1, 121))]
    return pts


def round_stroke(path, w, n=FOOT_SAMPLES):
    """Round-ended stroke along `path`, always the same number of points,
    drawn with off-curve points so the sides stay smooth curves."""
    lens = [0]
    for a, b in zip(path, path[1:]):
        lens.append(lens[-1] + math.dist(a, b))
    samples = []
    for k in range(n + 1):
        s = lens[-1] * k / n
        i = min(max(bisect.bisect_left(lens, s), 1), len(lens) - 1)
        a, b = path[i - 1], path[i]
        seg = (lens[i] - lens[i - 1]) or 1
        f = (s - lens[i - 1]) / seg
        samples.append(((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f),
                        ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)))
    r = w / 2
    left = [(x - ty * r, y + tx * r) for (x, y), (tx, ty) in samples]
    right = [(x + ty * r, y - tx * r) for (x, y), (tx, ty) in samples]
    (ex, ey), (tx, ty) = samples[-1]
    a = math.atan2(tx, -ty)
    pts = [(left[0], True)] + [(p, False) for p in left[1:-1]] + [(left[-1], True)]
    pts += arc(ex, ey, r, a, a - math.pi)
    pts += [(p, False) for p in reversed(right[1:-1])] + [(right[0], True)]
    return [p for p, _ in pts], [o for _, o in pts]


def add_foot(font, base, stem_zone, drop, tail):
    """Grow a rounded foot out of the stem of `base`, shaped like Comfortaa's l.
    The stroke really grows: at 0 it hides inside the letter, then it gets longer
    and curls to the right, ending on a round cap at every value."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    l = glyf["l"]
    lpts = list(l.coordinates)
    lstem = [p for p in lpts if p[1] > 300]
    lx0, lx1 = min(p[0] for p in lstem), max(p[0] for p in lstem)
    lc, lr = (lx0 + lx1) / 2, (lx1 - lx0) / 2
    l_curve_y = min(p[1] for p in lpts if p[0] == lx0)
    l_xmax, l_ymin = max(p[0] for p in lpts), min(p[1] for p in lpts)
    l_rsb = hmtx["l"][0] - l_xmax
    rx, ry = (l_xmax - lr) - lc, l_curve_y - (l_ymin + lr)    # l's foot, centreline radii

    g = glyf[base]
    bpts = list(g.coordinates)
    bstem = [p for p in bpts if stem_zone(p[1])]
    bx0, bx1 = min(p[0] for p in bstem), max(p[0] for p in bstem)
    w, bc = bx1 - bx0, (bx0 + bx1) / 2

    if drop:   # q: the descender bends right at its bottom
        b_bottom = min(p[1] for p in bpts)
        yb = b_bottom + w / 2
        lift = ry * tail                       # q's own round end hides inside the curl
        cap_y = b_bottom + w / 2 + 1
        g.coordinates = GlyphCoordinates(
            [(x, y + lift) if y <= cap_y else (x, y) for x, y in bpts])
        y_start = 150
    else:      # d: a stem grows down out of the bowl and curls right on the baseline
        yb = 250 + ((l_ymin + lr) - 250) * tail
        y_start = 600
    path = stroke_path(bc, y_start, yb + ry * tail, rx * tail, ry * tail)
    foot, oncurve = round_stroke(path, w)
    append_contour(g, foot, oncurve)

    old_adv = hmtx[base][0]
    new_adv = max(old_adv, round(bc + rx * tail + w / 2 + l_rsb)) if tail else old_adv
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


# ----------------------------------------------------- snowflake dots (ss02)
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


def flake(g, idxs):
    """Swap the round dot contours `idxs` of glyph g for little six-armed snowflakes,
    the same size as the dot (arms and branches are round-capped strokes)."""
    pts, flags = list(g.coordinates), list(g.flags)
    spans = list(ranges(g))
    centres = []
    for idx in idxs:
        s, e = spans[idx]
        xs, ys = [p[0] for p in pts[s:e + 1]], [p[1] for p in pts[s:e + 1]]
        centres.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                        (max(xs) - min(xs) + max(ys) - min(ys)) / 4))
    keep = [k for k in range(len(spans)) if k not in idxs]
    g.coordinates = GlyphCoordinates([pts[i] for k in keep for i in range(spans[k][0], spans[k][1] + 1)])
    g.flags = bytearray(flags[i] for k in keep for i in range(spans[k][0], spans[k][1] + 1))
    ends, n = [], 0
    for k in keep:
        n += spans[k][1] - spans[k][0] + 1
        ends.append(n - 1)
    g.endPtsOfContours = ends
    g.numberOfContours = len(ends)
    for cx, cy, r in centres:
        arm, w = r * FLAKE_REACH, max(14, r * FLAKE_STROKE)
        for k in range(6):
            a = math.radians(90 + 60 * k)
            append_contour(g, *capsule((cx, cy), (cx + arm * math.cos(a), cy + arm * math.sin(a)), w))
            bx, by = cx + arm * .55 * math.cos(a), cy + arm * .55 * math.sin(a)
            for side in (-1, 1):
                t = a + side * math.radians(50)
                append_contour(g, *capsule((bx, by), (bx + arm * .38 * math.cos(t), by + arm * .38 * math.sin(t)), w))


def add_flake_feature(font, dots):
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
            flake(new, by_glyph[n])
        add_glyph(font, n + ".ss02", new, hmtx[n])
        if n in gdef:
            gdef[n + ".ss02"] = gdef[n]
        mapping[n] = n + ".ss02"

    add_feature(font, "ss02", mapping)


def add_feature(font, tag, mapping):
    """Add a single-substitution feature (e.g. a stylistic set) to every script."""
    gsub = font["GSUB"].table
    lookup = ot.Lookup()
    lookup.LookupType, lookup.LookupFlag = 1, 0
    sub = ot.SingleSubst()
    sub.mapping = mapping
    lookup.SubTable, lookup.SubTableCount = [sub], 1
    gsub.LookupList.Lookup.append(lookup)
    gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
    rec = ot.FeatureRecord()
    rec.FeatureTag = tag
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


# ---------------------------------------------------------------- fillets
def inside(pt, poly, tol=4):
    """True if pt is inside a contour (its points as a polygon) or on its edge."""
    x, y, hit = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / ((dx * dx + dy * dy) or 1)))
        if math.dist(pt, (x1 + t * dx, y1 + t * dy)) <= tol:
            return True
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def find_corners(font):
    """(glyph, point index) of every on-curve point where the outline turns sharply."""
    glyf, out = font["glyf"], []
    for n in font.getGlyphOrder():
        g = glyf[n]
        if g.numberOfContours <= 0:
            continue
        pts = list(g.coordinates)
        for s, e in ranges(g):
            for i in range(s, e + 1):
                if not g.flags[i] & 1:
                    continue
                p = pts[i - 1] if i > s else pts[e]
                q = pts[i + 1] if i < e else pts[s]
                v = pts[i]
                a1 = math.atan2(v[1] - p[1], v[0] - p[0])
                a2 = math.atan2(q[1] - v[1], q[0] - v[0])
                turn = abs((math.degrees(a2 - a1) + 180) % 360 - 180)
                if turn > CORNER_DEG and math.dist(p, v) > 2 and math.dist(q, v) > 2:
                    hidden = any(inside(v, pts[s2:e2 + 1]) for s2, e2 in ranges(g) if s2 != s)
                    if not hidden:   # a corner under another piece of the letter stays as is
                        cross = (v[0] - p[0]) * (q[1] - v[1]) - (v[1] - p[1]) * (q[0] - v[0])
                        out.append((n, i, cross < 0))
    return out


def round_corners(font, corners):
    """Swap each corner point for a small curve (on, off, on): no spikes, no sharp notches."""
    glyf, by = font["glyf"], {}
    for n, i, tip in corners:
        by.setdefault(n, {})[i] = tip
    for n, idxs in by.items():
        g = glyf[n]
        pts, flags, ends = list(g.coordinates), list(g.flags), list(g.endPtsOfContours)
        for i in sorted(idxs, reverse=True):
            c = next(k for k, e in enumerate(ends) if i <= e)
            s, e = (ends[c - 1] + 1 if c else 0), ends[c]
            pi, qi = (i - 1 if i > s else e), (i + 1 if i < e else s)
            p, q, v = pts[pi], pts[qi], pts[i]
            p_curve, q_curve = not flags[pi] & 1, not flags[qi] & 1

            def toward(t, r):
                d = math.dist(t, v) or 1
                return (round(v[0] + (t[0] - v[0]) * r / d), round(v[1] + (t[1] - v[1]) * r / d))
            if idxs[i]:                  # outward tip: small round, never cut into the stroke
                r = min(FILLET, .45 * math.dist(p, v), .45 * math.dist(q, v))
                new, fl = [toward(p, r), v, toward(q, r)], [1, 0, 1]
            elif p_curve and q_curve:    # two curves meet in a notch: let them flow together
                flags[i] = 0
                continue
            elif p_curve or q_curve:     # a curve meets a straight stem: blend it in wide
                line = q if p_curve else p
                b = toward(line, min(BLEND, .5 * math.dist(line, v)))
                new, fl = ([v, b], [0, 1]) if p_curve else ([b, v], [1, 0])
            else:                        # two straight lines in a notch: small round
                r = min(FILLET, .45 * math.dist(p, v), .45 * math.dist(q, v))
                new, fl = [toward(p, r), v, toward(q, r)], [1, 0, 1]
            pts[i:i + 1] = new
            flags[i:i + 1] = fl
            ends = ends[:c] + [x + len(new) - 1 for x in ends[c:]]
        g.coordinates = GlyphCoordinates(pts)
        g.flags = bytearray(flags)
        g.flags[0] |= flagOverlapSimple
        g.endPtsOfContours = ends


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
        h = zlib.crc32(n.removesuffix(".ss02").removesuffix(".ss03").encode())
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


def add_tail_alternates(font):
    """d.ss03 / q.ss03 (and dcaron, dcroat...) with the rounded foot; plain d / q stay Comfortaa."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    mapping = {}
    for base, zone, drop in (("d", lambda y: y > 600, False), ("q", lambda y: y < -100, True)):
        alt = base + ".ss03"
        add_glyph(font, alt, copy.deepcopy(glyf[base]), hmtx[base])
        add_foot(font, alt, zone, drop=drop, tail=1)
        mapping[base] = alt
        for n in list(font.getGlyphOrder()):
            g = glyf[n]
            if g.isComposite() and g.components[0].glyphName == base and not n.endswith(".ss03"):
                new = copy.deepcopy(g)
                new.components[0].glyphName = alt
                delta = hmtx[alt][0] - hmtx[base][0]
                add_glyph(font, n + ".ss03", new, (hmtx[n][0] + delta, hmtx[n][1]))
                mapping[n] = n + ".ss03"
    gdef = font["GDEF"].table.GlyphClassDef.classDefs if "GDEF" in font else {}
    for n, alt in mapping.items():
        if n in gdef:
            gdef[alt] = gdef[n]
    add_feature(font, "ss03", mapping)


def prepared(wght):
    font = instancer.instantiateVariableFont(source_without_featvars()[0], {"wght": wght})
    for tag in ("prep", "fpgm", "cvt "):
        if tag in font:
            del font[tag]
    for g in font["glyf"].glyphs.values():
        if hasattr(g, "program"):
            g.program = ttProgram.Program()
            g.program.fromBytecode(b"")
    add_tail_alternates(font)
    add_snowflake(font)
    return font


def make_master(loc, dots, corners=None):
    v = {t: a[2] for t, a in AXES.items()} | loc
    font = prepared(v["wght"])
    if v["XHGT"] != XH:
        raise_xheight(font, v["XHGT"] - XH)
    add_flake_feature(font, dots)
    decompose_all(font)
    add_air(font)
    if corners is None:          # first pass: only used to find the corners
        return font
    round_corners(font, corners)
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
    copyright_ = name.getDebugName(0) + f' Copyright 2026 {DESIGNER}, with Reserved Font Name "{FAMILY}".'
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
    corners = find_corners(make_master({}, dots))

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
        make_master(loc, dots, corners).save(path)
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
    print(f"{out.name}: axes {', '.join(AXES)}, {len(corners)} corners rounded, {len(vf.getGlyphOrder())} glyphs")


if __name__ == "__main__":
    main()
