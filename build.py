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
  UNRL  0-1      unroll: tails tighten in (0) or open out and curl (1); past
                 Comfortaa the end of each loop spirals a little inside. 0.25 looks
                 like Comfortaa, default 0.4
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

FAMILY = "Cooldown"
VERSION = 1.5
DESIGNER = "Nathan de Castro (ColdSnap)"
VENDOR = "CSNP"
OUT_NAME = "Cooldown-Lab"

SPACING = 15             # extra units on each side of every glyph (UPM 1000)
WORD_SPACING = 40        # extra units on the space on top of that
SPARKLE_N = 0.65         # superellipse exponent: 1 = diamond, < 1 = concave star
SPARKLE_K = 1.45         # how far the sparkle points reach, in dot radii
WOBBLE_DEG = 10          # max tilt per letter at WOBL 1
FILLET = 35              # radius of the round where two straight edges meet
BLEND = 50               # how far up a stem a curve melts into it
CORNER_DEG = 35          # a turn sharper than this counts as a corner
UNROLL_STEPS = [0, 0.25, 0.5, 0.75, 1]   # masters so ends slide along their curves
XH = 547                 # Comfortaa's x-height
ASC = 781

# tag: (name, min, default, max)
AXES = {
    "wght": ("Weight", 300, 400, 700),
    "XHGT": ("x-height", 520, XH, 600),
    "UNRL": ("Unroll", 0, 0.4, 1),
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


# ------------------------------------------------------- stroke letters
# Comfortaa's round letters are one pen line of constant width: a circle that
# runs on along its tangent. These letters are redrawn as exactly that, and the
# Unroll axis morphs the line instead of just sliding its ends:
#   - loops never butt their two tips together: past Comfortaa the closing end
#     spirals a little inside the letter and tucks in beside its own start;
#   - tails change shape: rolled in they curl tighter and shorter, run out they
#     open up a little and turn slightly further. Everything stays subtle.
COMF = 0.25            # Unroll value that looks like Comfortaa
OVERLAP_DEG = 15       # closed loops overlap this much, so there is no seam
SPIRAL_IN = 0.7        # how far inside the end curls at Unroll 1, in stroke widths
SPIRAL_EXTRA = 50      # degrees the loop runs on past its own start at Unroll 1
STROKED = ["o", "a", "b", "d", "p", "q", "l", "uni0237"]


def smooth(t):
    t = min(max(t, 0), 1)
    return t * t * (3 - 2 * t)


class Path:
    """A pen path built from lines and arcs, sampled densely."""
    def __init__(self, start):
        self.pts, self.lens = [start], [0.0]

    def _add(self, p):
        if math.dist(self.pts[-1], p) < 1e-6:
            return
        self.lens.append(self.lens[-1] + math.dist(self.pts[-1], p))
        self.pts.append(p)

    def line(self, p, n=40):
        x0, y0 = self.pts[-1]
        for i in range(1, n + 1):
            self._add((x0 + (p[0] - x0) * i / n, y0 + (p[1] - y0) * i / n))
        return self

    def arc(self, c, rx, ry, a0, a1, inward=0.0, tuck_deg=0, tuck_at_start=False):
        """Elliptic arc from angle a0 to a1 (degrees). With `inward`, the radius
        shrinks smoothly by that much over `tuck_deg` at the end (or start)."""
        if rx < .5 or ry < .5 or abs(a1 - a0) < .01:
            return self
        n = max(8, int(abs(a1 - a0) / 2))
        sweep = abs(a1 - a0)
        for i in range(1, n + 1):
            a = a0 + (a1 - a0) * i / n
            done = sweep * i / n
            k = smooth((tuck_deg - done) / tuck_deg) if tuck_at_start else \
                smooth((done - (sweep - tuck_deg)) / tuck_deg) if tuck_deg else 0
            t = math.radians(a)
            self._add((c[0] + (rx - inward * k) * math.cos(t), c[1] + (ry - inward * k) * math.sin(t)))
        return self

    @property
    def length(self):
        return self.lens[-1]

    def at(self, s):
        s = min(max(s, 0), self.length)
        i = min(max(bisect.bisect_left(self.lens, s), 1), len(self.lens) - 1)
        a, b = self.pts[i - 1], self.pts[i]
        f = (s - self.lens[i - 1]) / ((self.lens[i] - self.lens[i - 1]) or 1)
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)

    def samples(self, n):
        """n+1 evenly spaced (point, unit tangent) samples along the whole path."""
        out, L = [], self.length
        for k in range(n + 1):
            s = L * k / n
            a, b = self.at(max(s - 1, 0)), self.at(min(s + 1, L))
            d = math.dist(a, b) or 1
            out.append((self.at(s), ((b[0] - a[0]) / d, (b[1] - a[1]) / d)))
        return out


def round_stroke(samples, w):
    """Constant-width stroke with a round cap at both ends; the point count only
    depends on the number of samples, so every master stays compatible."""
    r = w / 2
    left = [(x - ty * r, y + tx * r) for (x, y), (tx, ty) in samples]
    right = [(x + ty * r, y - tx * r) for (x, y), (tx, ty) in samples]
    (ex, ey), (tx, ty) = samples[-1]
    (sx, sy), (ux, uy) = samples[0]
    a_end, a_start = math.atan2(tx, -ty), math.atan2(-ux, uy)
    pts = [(left[0], True)] + [(p, False) for p in left[1:-1]] + [(left[-1], True)]
    pts += arc(ex, ey, r, a_end, a_end - math.pi)
    pts += [(p, False) for p in reversed(right[1:-1])] + [(right[0], True)]
    pts += arc(sx, sy, r, a_start, a_start - math.pi)[:-1]
    return [p for p, _ in pts], [o for _, o in pts]


def stroke_letters(font, u):
    """Redraw STROKED letters as pen strokes for Unroll value u (0-1)."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    for n in STROKED + ["I"]:
        glyf[n].recalcBounds(glyf)
    # s: -1 (rolled in) .. 0 (Comfortaa) .. 1 (run out)
    s = (u - COMF) / COMF if u < COMF else (u - COMF) / (1 - COMF)
    out, inn = max(s, 0), max(-s, 0)
    w = glyf["I"].xMax - glyf["I"].xMin
    o = glyf["o"]
    R = (o.xMax - o.xMin) / 2 - w / 2
    cy = (o.yMin + o.yMax) / 2
    # The pen closes the circle, covers its own start, and only then curls inward:
    # a little spiral, with no step and no tips butting into each other.
    tuck = SPIRAL_IN * w * smooth(out)
    sweep = 360 + OVERLAP_DEG + SPIRAL_EXTRA * smooth(out)
    tuck_deg = sweep - 360 + 10
    shapes = {}

    def loop(c, a0, direction):
        """A circle from a0 (direction -1 = clockwise) whose end tucks inside."""
        return Path((c[0] + R * math.cos(math.radians(a0)), c[1] + R * math.sin(math.radians(a0)))) \
            .arc(c, R, R, a0, a0 + direction * sweep, inward=tuck, tuck_deg=tuck_deg)

    # o
    cx = (o.xMin + o.xMax) / 2
    shapes["o"] = [(loop((cx, cy), 60, -1), 56)]

    # a: the loop runs on down its right tangent; here the loop's *start* tucks in,
    # so the tail that makes it an a always stays
    a = glyf["a"]
    sx = a.xMax - w / 2
    acx = sx - R
    a0 = sweep - 360                                  # the loop starts inside, past the join
    ra = R - tuck
    p = Path((acx + ra * math.cos(math.radians(a0)), cy + ra * math.sin(math.radians(a0))))
    p.arc((acx, cy), R, R, a0, -360, inward=tuck, tuck_deg=tuck_deg, tuck_at_start=True)
    rc = 35 * out                                     # little curl that grows at the foot
    p.line((sx, w / 2 + rc + 18 * inn))
    p.arc((sx + rc, w / 2 + rc), rc, rc, 180, 270 + 25 * out)
    shapes["a"] = [(p, 72)]

    # d / q and b / p: stem + loop. The stem's free end morphs, the loop tucks in.
    for name, right, down in (("d", True, False), ("q", True, True),
                              ("b", False, False), ("p", False, True)):
        g = glyf[name]
        sx = g.xMax - w / 2 if right else g.xMin + w / 2
        c = (sx - R if right else sx + R, cy)
        side = 1 if right else -1
        if not down:          # ascender letters: stem from the top down to the join
            stem = Path((sx, g.yMax - w / 2)).line((sx, cy))
            extra = 60 * out                       # runs on a little below the join
            if extra > .5:
                if right:     # d: curves gently right as it runs out
                    rc = 30 * out
                    stem.line((sx, cy - extra))
                    stem.arc((sx + rc, cy - extra), rc, rc, 180, 180 + 55 * out)
                else:         # b: just a short straight run
                    stem.line((sx, cy - extra))
            lp = loop(c, 0 if right else 180, -1 if right else 1)
        else:                 # descender letters: stem from the join down
            top = cy + (60 * out if not right else 0)   # p's stem peeks above the join
            bottom = g.yMin + w / 2
            stem = Path((sx, top)).line((sx, cy)) if top > cy + .5 else Path((sx, cy))
            if right:         # q: the descender's end curls right a little
                rc = 35 * out
                stem.line((sx, bottom + rc + 22 * inn))
                stem.arc((sx + rc, bottom + rc), rc, rc, 180, 270 + 25 * out)
            else:
                stem.line((sx, bottom + 22 * inn))
            lp = loop(c, 0 if right else 180, 1 if right else -1)
        shapes[name] = [(stem, 28), (lp, 56)]

    # l: Comfortaa's stem and foot; the foot tightens when rolled in, opens when run out
    l = glyf["l"]
    lpts = list(l.coordinates)
    stem_pts = [q for q in lpts if q[1] > 300]
    lx0, lx1 = min(q[0] for q in stem_pts), max(q[0] for q in stem_pts)
    sx = (lx0 + lx1) / 2
    curve_y = min(q[1] for q in lpts if q[0] == lx0)
    rx, ry = (l.xMax - w / 2) - sx, curve_y - (l.yMin + w / 2)
    f = 1 + .12 * out - .3 * inn
    rx, ry = rx * f, ry * f
    base = l.yMin + w / 2
    p = Path((sx, l.yMax - w / 2)).line((sx, base + ry))
    p.arc((sx + rx, base + ry), rx, ry, 180, 270 + 20 * out - 25 * inn)
    shapes["l"] = [(p, 36)]

    # dotless j: stem and hook to the left, same idea mirrored
    j = glyf["uni0237"]
    jpts = list(j.coordinates)
    jstem = [q for q in jpts if q[1] > 100]
    jx0, jx1 = min(q[0] for q in jstem), max(q[0] for q in jstem)
    sx = (jx0 + jx1) / 2
    hook_y = min(q[1] for q in jpts if q[0] == jx1)
    ex_, ey_ = j.xMin + w / 2, j.yMin + w / 2
    rx, ry = (sx - ex_) * (1 + .12 * out - .3 * inn), (hook_y - ey_) * (1 + .12 * out - .3 * inn)
    p = Path((sx, j.yMax - w / 2)).line((sx, ey_ + ry))
    p.arc((sx - rx, ey_ + ry), rx, ry, 0, -90 - 20 * out + 25 * inn)
    shapes["uni0237"] = [(p, 36)]

    for name, strokes in shapes.items():
        old = glyf[name]
        old_rsb = hmtx[name][0] - old.xMax
        g = empty_glyph()
        for path, n in strokes:
            append_contour(g, *round_stroke(path.samples(n), w))
        glyf[name] = g
        g.recalcBounds(glyf)
        new_adv = max(hmtx[name][0], round(g.xMax + old_rsb))
        delta = new_adv - hmtx[name][0]
        hmtx[name] = (new_adv, hmtx[name][1])
        for other in font.getGlyphOrder():
            c = glyf[other]
            if delta and c.isComposite() and c.components[0].glyphName == name:
                hmtx[other] = (hmtx[other][0] + delta, hmtx[other][1])


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


# ---------------------------------------------------------------- fillets
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
            if idxs[i]:                # outward corner (a tip): small round, never a cut
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


def prepared(wght, unroll=0.4):
    font = instancer.instantiateVariableFont(source_without_featvars()[0], {"wght": wght})
    for tag in ("prep", "fpgm", "cvt "):
        if tag in font:
            del font[tag]
    for g in font["glyf"].glyphs.values():
        if hasattr(g, "program"):
            g.program = ttProgram.Program()
            g.program.fromBytecode(b"")
    stroke_letters(font, unroll)
    add_snowflake(font)
    return font


def make_master(loc, dots, corners=None):
    v = {t: a[2] for t, a in AXES.items()} | loc
    font = prepared(v["wght"], v["UNRL"])
    if v["XHGT"] != XH:
        raise_xheight(font, v["XHGT"] - XH)
    add_sparkle_feature(font, dots)
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
        for ext in (UNROLL_STEPS if tag == "UNRL" else (lo, hi)):
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
