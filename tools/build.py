#!/usr/bin/env python3
"""Baut die Grafiken für das GitHub-Profil (README.md) im Stil von hjorven.github.io.

Aufruf aus dem Profil-Repo:
    python3 tools/build.py <pfad-zum-portfolio-repo> [--accent cobalt]

Gelesen werden aus dem Portfolio-Repo: fonts/*.woff2, img/*.png (Gravuren der Karten),
favicon.svg und tools/render.py (Raymarcher für die Titelfigur).
Geschrieben wird nach assets/: Titelbild (animiert), vier Karten, zwei Überschriften und
die Fußzeile, alles je einmal für das dunkle und das helle GitHub-Thema.

Maßstab: entworfen wird in CSS-Pixeln, gespeichert in doppelter Auflösung.
Ein Rasterpunkt ist 1 CSS-Pixel groß (2 x 2 Bildpixel), so wie bei den Karten der Seite.
"""
import argparse
import colorsys
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
S = 2             # Bildpixel pro CSS-Pixel
DW = 800          # Entwurfsbreite in CSS-Pixeln. Das README ist auf dem Profil höchstens 846 breit, in der
                  # Repo-Ansicht 830; 800 lässt Luft, damit zwei Karten auch in schmaleren Fenstern nebeneinander passen
PAD = 3           # durchsichtiger Rand links und rechts: ergibt 6 px Abstand zwischen zwei Karten
FRAMES = 24       # Bilder für eine halbe Umdrehung (nahtlos, wie auf der Seite)
FRAME_MS = 120

# Akzentfarben der Seite: Farbton, Akzent, Schrift auf Akzent (None = dunkle Tinte)
ACCENTS = {
    "cobalt": (238, "#2424ff", "#ffffff"), "violet": (262, "#7a2cff", "#ffffff"),
    "purple": (283, "#b02be3", "#ffffff"), "magenta": (331, "#ff2e93", None),
    "crimson": (348, "#d6143c", "#ffffff"), "vermilion": (10, "#ee3a17", None),
    "orange": (28, "#ff7a00", None), "gold": (44, "#f2b200", None),
    "lime": (78, "#9bd400", None), "green": (135, "#1fb043", None),
    "patina": (166, "#10b08b", None), "turquoise": (195, "#00a8dc", None),
}

# Die vier Hauptwerke, Texte wie auf der Seite (Abschnitt "Featured")
OPERA = [
    dict(slug="poly-battle", art="hex", kicker="Opus I · Strategy · JavaScript", title="Poly Battle",
         text="Turn-based conquest on a world of hexagons, in low-poly 3D, against AI opponents with their own personality.",
         status="Live", action="Play"),
    dict(slug="wallpapers", art="frames", kicker="Opus VII · Collection · Python", title="Wallpapers",
         text="A growing collection of engraved and generated iPad wallpapers, in landscape and portrait.",
         status="Live", action="Open"),
    dict(slug="dither-workshop", art="pixels", kicker="Opus VI · Tool · JavaScript", title="Dither Workshop",
         text="1-bit dither and ASCII art editor in the browser: turn any image into dots, blocks, Braille or characters.",
         status="Live", action="Open"),
    dict(slug="satisfactory", art="rack", kicker="Opus IV · iPhone · Swift", title="Satisfactory Server App",
         text="Native SwiftUI iPhone app for your own Satisfactory server: overview, power monitoring and controls.",
         status="Repository", action="Code"),
]

HEADS = [
    dict(slug="featured", kicker="Opera maiora", title="Featured", mark="IV", button="All repositories"),
    dict(slug="index", kicker="Index operum", title="Index", mark="VII", button="Install commands"),
]


# ---------- Farben ----------
def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (round(r * 255), round(g * 255), round(b * 255))


def hexrgb(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    """Wie color-mix(in srgb, a t%, b)."""
    return tuple(round(a[i] * t + b[i] * (1 - t)) for i in range(3))


class Palette:
    """Dieselben Werte wie die CSS-Variablen der Seite."""

    def __init__(self, theme, accent):
        h, acc, on = ACCENTS[accent]
        self.theme = theme
        self.accent = hexrgb(acc)
        if theme == "dark":
            self.ink, self.ink2, self.line = hsl(h, 48, 11), hsl(h, 48, 15), hsl(h, 38, 27)
            self.paper, self.muted = hsl(h, 45, 94), hsl(h, 30, 72)
            self.soft = mix(self.accent, (255, 255, 255), 0.55)
            self.acctext = mix(self.accent, self.paper, 0.60)
        else:
            self.ink, self.ink2, self.line = hsl(h, 62, 89), hsl(h, 55, 83), hsl(h, 35, 68)
            self.paper, self.muted = hsl(h, 55, 12), hsl(h, 25, 31)
            self.soft = mix(self.accent, self.paper, 0.60)
            self.acctext = mix(self.accent, self.paper, 0.40)
        self.on_accent = hexrgb(on) if on else hsl(h, 60, 9)


# ---------- Zeichenfläche in CSS-Pixeln ----------
class Canvas:
    def __init__(self, w, h, bg=None):
        self.w, self.h = w, h
        self.im = Image.new("RGBA", (w * S, h * S), (*bg, 255) if bg else (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def rect(self, x0, y0, x1, y1, fill=None, outline=None):
        """Rechteck von (x0, y0) bis ausschließlich (x1, y1); der Rahmen ist 1 CSS-Pixel stark und liegt innen."""
        box = (x0 * S, y0 * S, x1 * S - 1, y1 * S - 1)
        self.d.rectangle(box, fill=fill and (*fill, 255), outline=outline and (*outline, 255), width=S)

    def mask(self, m, x, y, color):
        """Setzt eine 1-Bit-Maske (ein Wert pro CSS-Pixel) in einer Farbe auf die Fläche."""
        a = Image.fromarray(np.kron(m, np.ones((S, S), bool)).astype(np.uint8) * 255, "L")
        self.im.paste(Image.new("RGBA", a.size, (*color, 255)), (x * S, y * S), a)

    def text(self, x, y, s, font, fill, track=0.0, anchor="ls"):
        """Text an der Grundlinie; track ist die Laufweite in em. Gibt die Breite in CSS-Pixeln zurück."""
        if not track:
            self.d.text((x * S, y * S), s, font=font, fill=(*fill, 255), anchor=anchor)
            return font.getlength(s) / S
        step = track * font.size
        for i, ch in enumerate(s):
            self.d.text((x * S + font.getlength(s[:i]) + i * step, y * S), ch, font=font, fill=(*fill, 255), anchor="ls")
        return (font.getlength(s) + len(s) * step) / S

    def paste(self, im, x, y):
        self.im.alpha_composite(im, (round(x * S), round(y * S)))


def text_width(s, font, track=0.0):
    return (font.getlength(s) + len(s) * track * font.size) / S


class Fonts:
    def __init__(self, portfolio):
        self.dir = portfolio / "fonts"

    def _load(self, name, px, weight=None):
        path = self.dir / name
        try:
            f = ImageFont.truetype(str(path), round(px * S))
        except OSError as e:
            sys.exit(f"Schrift {path} lässt sich nicht laden ({e}). Pillow braucht FreeType mit WOFF2-Unterstützung: pip install --upgrade pillow")
        if weight:
            f.set_variation_by_axes([weight])
        return f

    def serif(self, px): return self._load("instrument-serif-latin-400-normal.woff2", px)
    def italic(self, px): return self._load("instrument-serif-latin-400-italic.woff2", px)
    def mono(self, px): return self._load("ibm-plex-mono-latin-400-normal.woff2", px)
    def sans(self, px, weight=400): return self._load("inter-tight-latin-wght-normal.woff2", px, weight)


def wrap(s, font, width):
    """Bricht Text auf eine Breite in CSS-Pixeln um."""
    lines, cur = [], ""
    for word in s.split():
        t = (cur + " " + word).strip()
        if cur and font.getlength(t) / S > width:
            lines.append(cur)
            cur = word
        else:
            cur = t
    return lines + [cur]


def button(c, x_right, y_top, label, fonts, pal, ghost):
    """Schaltfläche wie .btn auf der Seite, rechtsbündig. Gibt die linke Kante zurück."""
    f = fonts.mono(11)
    s = label.upper()
    w = round(text_width(s, f, 0.14) - 0.14 * 11) + 28
    x0 = x_right - w
    if ghost:
        c.rect(x0, y_top, x_right, y_top + 35, outline=pal.line)
        c.text(x0 + 14, y_top + 22, s, f, pal.paper, 0.14)
    else:
        c.rect(x0, y_top, x_right, y_top + 35, fill=pal.accent)
        c.text(x0 + 14, y_top + 22, s, f, pal.on_accent, 0.14)
    return x0


def report(path):
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print("  ", shown, f"{path.stat().st_size / 1024:.0f} kB", flush=True)


def save_png(c, path):
    c.im.save(path, optimize=True)
    report(path)


# ---------- Logo aus favicon.svg ----------
def logo(px, pal, svg_path):
    """Zeichnet das Ikosaeder-Signet der Seite (favicon.svg) ohne den Hintergrund."""
    ss = 4
    n = px * S * ss
    k = n / 64
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    svg = svg_path.read_text(encoding="utf-8")
    pts = lambda s: [tuple(float(v) * k for v in p.split(",")) for p in s.split()]
    for p, pat in re.findall(r'<polygon points="([^"]+)" fill="url\(#(d2?)\)"', svg):
        d.polygon(pts(p), fill=(*pal.accent, 255 if pat == "d2" else 150))
    m = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"[^>]*stroke-width="([\d.]+)"', svg)
    cx, cy, r, sw = (float(v) * k for v in m.groups())
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*pal.accent, 255), width=round(sw))
    g = re.search(r'<g [^>]*stroke-width="([\d.]+)"[^>]*>(.*?)</g>', svg, re.S)
    w = round(float(g.group(1)) * k)
    ink = (*pal.paper, 255)
    segs = [pts(p) + pts(p)[:1] for p in re.findall(r'<polygon points="([^"]+)"/>', g.group(2))]
    segs += [[(float(a) * k, float(b) * k), (float(c_) * k, float(e) * k)]
             for a, b, c_, e in re.findall(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"/>', g.group(2))]
    for seg in segs:
        d.line(seg, fill=ink, width=w, joint="curve")
        for x, y in seg:
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=ink)
    return im.resize((px * S, px * S), Image.LANCZOS)


# ---------- Titelfigur: Säule, Strahlen, drehendes Ikosaeder ----------
CAM = dict(cam=(0.9, 0.3, 7.2), target=(0, -0.35, 0), fov=0.95, light=(-0.7, 0.9, 0.7))
FIG_H = 356       # Höhe der Figur in CSS-Pixeln (auf der Seite: 725)


def scene_column(R):
    def f(p):
        col = R.sd_fluted(R.T(p, 0, -0.95, 0), 0.34, 0.95, n=18, depth=0.04)
        cap = R.sd_box(R.T(p, 0, 0.06, 0), np.array([0.48, 0.06, 0.48]))
        echinus = R.sd_cyl(R.T(p, 0, -0.02, 0), 0.42, 0.04)
        base = R.sd_box(R.T(p, 0, -1.95, 0), np.array([0.55, 0.07, 0.55]))
        base2 = R.sd_box(R.T(p, 0, -2.07, 0), np.array([0.7, 0.06, 0.7]))
        return np.minimum.reduce([col, cap, echinus, base, base2])
    return f


def scene_ico(R, angle):
    def f(p):
        q = R.rot_y(R.rot_x(R.rot_y(R.T(p, 0, 1.05, 0), 0.5), 0.35), angle)
        ico = R.sd_poly(q, 0.62, R.ICO_N)
        ring = R.sd_torus(R.rot_x(R.rot_z(R.T(p, 0, 1.05, 0), 0.35), 1.25), 1.05, 0.018)
        ring2 = R.sd_torus(R.rot_x(R.rot_z(R.T(p, 0, 1.05, 0), -0.5), 1.0), 1.25, 0.012)
        return np.minimum.reduce([ico, ring, ring2])
    return f


def engrave(R, v, k, off=(0, 0), period=4.0):
    """Kupferstich-Linienraster wie engrave_layer() der Seite, aber im Entwurfsmaßstab:
    k ist das Verhältnis zur Originalgröße, damit die Wellen zur Figur passen."""
    obj = ~np.isnan(v)
    vv = np.nan_to_num(v)
    h, w = v.shape
    ys, xs = np.mgrid[off[1]:off[1] + h, off[0]:off[0] + w]
    X, Y = xs * k, ys * k
    phase = (Y + 6 * np.sin(X / 37.0) + 3 * np.sin(X / 11.0 + Y / 23.0)) / (period * k)
    m = (np.abs(phase - np.round(phase)) < vv ** 0.9 * 0.5) & obj
    m |= (np.clip((vv - 0.75) * 3, 0, 1) > R.BAYER[ys % 8, xs % 8]) & obj      # Glanzlichter
    edge = R.binary_dilation(obj, iterations=1) & ~obj                          # Kontur
    return m | edge, obj


def rays(w, h, cx, cy, lmax, n=96, seed=1, r0=14):
    """Strahlenkranz wie rays() in render.py, aber mit frei wählbarer Länge
    (dort hängt die Länge an der Bildgröße, und die längsten Strahlen enden am Bildrand)."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:h, 0:w]
    ang = np.arctan2(ys - cy, xs - cx)
    rad = np.hypot(xs - cx, ys - cy)
    m = np.zeros((h, w), bool)
    for a in np.linspace(-np.pi, np.pi, n, endpoint=False) + rng.normal(0, 0.01, n):
        width = 0.0025 + 0.004 * rng.random()
        length = rng.uniform(0.45, 1.0) * lmax
        m |= (np.abs(np.angle(np.exp(1j * (ang - a)))) < width * 120 / np.maximum(rad, 1)) & (rad < length) & (rad > r0)
    return m


def render_figure(R):
    """Rendert die Figur einmal; die Farben kommen später dazu."""
    k = 725 / FIG_H
    W, H = round(760 / k), round(900 / k)
    print("Titelfigur: Säule", flush=True)
    col_m, col_obj = engrave(R, R.render(scene_column(R), W, H, **CAM), k)
    v0 = R.render(scene_ico(R, 0.0), W, H, **CAM)
    ys, xs = np.where(~np.isnan(v0))
    x0, x1, y0, y1 = max(0, xs.min() - 4), min(W, xs.max() + 5), max(0, ys.min() - 4), min(FIG_H, ys.max() + 5)
    win = (x0, y0, x1 - x0, y1 - y0)
    frames = []
    for i in range(FRAMES):
        ang = np.pi * i / FRAMES    # halbe Umdrehung: die Achse ist zweizählig, die Schleife schließt nahtlos
        m, obj = engrave(R, R.render(scene_ico(R, ang), W, H, crop=win, **CAM), k, off=(x0, y0))
        frames.append((m, R.binary_dilation(obj, iterations=2)))
        print(f"Titelfigur: Bild {i + 1} von {FRAMES}", flush=True)
    return dict(W=W, col=col_m[:FIG_H], col_obj=col_obj[:FIG_H], win=win, frames=frames, center=(W * 0.5, H * 0.3))


def build_hero(R, fig, fonts, pal, portfolio, out):
    W, H = DW - 2 * PAD, 400      # ohne Rand (ein GIF kennt keine weichen Kanten), im README mit width="794"
    c = Canvas(W, H, pal.ink)

    # Rasterverlauf am unteren Rand
    ys, xs = np.mgrid[0:H, 0:W]
    t = np.clip((ys - 0.55 * H) / (0.45 * H), 0, 1)
    c.mask((t ** 1.6 * 0.3) > R.BAYER[ys % 8, xs % 8], 0, 0, pal.accent)

    # Figur rechts: Strahlen (um die Säule ausgespart), dann die Säule
    fx, fy = W - 392, 28
    glory = rays(W, H, fx + fig["center"][0], fy + fig["center"][1], lmax=250)
    keep = np.zeros((H, W), bool)
    keep[fy:fy + FIG_H, fx:fx + fig["W"]] = R.binary_dilation(fig["col_obj"], iterations=3)
    c.mask(glory & ~keep, 0, 0, pal.accent)
    c.mask(fig["col"], fx, fy, pal.paper)

    # feiner Rahmen
    c.rect(9, 9, W - 9, H - 9, outline=pal.line)

    # Schrift links
    c.text(37, 64, "OFFICINA HJORVEN · BERLIN", fonts.mono(11), pal.muted, 0.18)
    c.text(34, 148, "Games,", fonts.serif(84), pal.paper)
    c.text(34, 222, "apps and", fonts.serif(84), pal.paper)
    c.text(34, 296, "clocks", fonts.italic(84), pal.soft)
    c.paste(logo(28, pal, portfolio / "favicon.svg"), 37, 335)
    c.text(77, 354, "HJORVEN.GITHUB.IO", fonts.mono(12), pal.paper, 0.16)

    # Einzelbilder: Unterlage in Hintergrundfarbe (verdeckt die Strahlen), darauf die Striche
    base = np.array(c.im.convert("RGB"))
    wx, wy, ww, wh = fig["win"]
    box = np.s_[(fy + wy) * S:(fy + wy + wh) * S, (fx + wx) * S:(fx + wx + ww) * S]
    big = lambda m: np.kron(m, np.ones((S, S), bool))
    frames = []
    for m, knock in fig["frames"]:
        a = base.copy()
        a[box][big(knock)] = pal.ink
        a[box][big(m)] = pal.paper
        frames.append(Image.fromarray(a, "RGB"))

    # Gemeinsame Farbtabelle: 64 Töne reichen für die geglättete Schrift; die Flächenfarben bleiben exakt
    table = np.array(frames[0].quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
                     .getpalette()[:64 * 3], int).reshape(-1, 3)
    used = set()
    for key in (pal.ink, pal.paper, pal.accent, pal.soft, pal.muted, pal.line):
        d = np.abs(table - np.array(key)).sum(1)
        d[list(used)] = 10 ** 6
        table[d.argmin()] = key
        used.add(int(d.argmin()))
    pal_im = Image.new("P", (1, 1))
    pal_im.putpalette(table.flatten().tolist())
    q = [im.quantize(palette=pal_im, dither=Image.Dither.NONE) for im in frames]
    path = out / f"hero-{pal.theme}.gif"
    q[0].save(path, save_all=True, append_images=q[1:], duration=FRAME_MS, loop=0, disposal=1, optimize=False)
    report(path)


# ---------- Karten ----------
def card_art(R, mask_path, w, h, top, seed):
    """Nimmt die Gravur der Seite (240 x 240 Punkte) und setzt das Hintergrundkorn seitlich fort."""
    a = np.array(Image.open(mask_path).getchannel("A"))[::2, ::2] > 127
    ox = (w - a.shape[1]) // 2
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[top:top + h, -ox:w - ox]
    level = 0.2 + 0.12 * (ys / (a.shape[0] - 1) - 0.5) + rng.normal(0, 0.03, (h, w))
    m = level > R.BAYER[ys % 8, xs % 8]
    m[:, ox:ox + a.shape[1]] = a[top:top + h]
    return m


def build_card(R, o, i, fonts, pal, portfolio, out):
    W, H, AH = DW // 2, 356, 180
    c = Canvas(W, H)
    c.rect(PAD, 0, W - PAD, H, fill=pal.ink2, outline=pal.line)
    c.mask(card_art(R, portfolio / "img" / f"{o['art']}.png", W - 2 * PAD - 2, AH, 30, 20 + i), PAD + 1, 1, pal.accent)
    x, xr = PAD + 19, W - PAD - 19
    c.text(x, AH + 27, o["kicker"].upper(), fonts.mono(10.5), pal.muted, 0.18)
    c.text(x, AH + 63, o["title"], fonts.serif(30), pal.paper)
    f = fonts.sans(14)
    for n, line in enumerate(wrap(o["text"], f, xr - x)[:2]):
        c.text(x, AH + 89 + n * 21, line, f, pal.muted)
    yb = AH + 122
    live = o["status"] == "Live"
    fs = fonts.mono(10)
    s = o["status"].upper()
    sw = round(text_width(s, fs, 0.16) - 0.16 * 10) + 14
    c.rect(x, yb + 7, x + sw, yb + 28, fill=pal.accent if live else None, outline=None if live else pal.line)
    c.text(x + 7, yb + 21, s, fs, pal.on_accent if live else pal.paper, 0.16)
    button(c, xr, yb, o["action"], fonts, pal, ghost=not live)
    save_png(c, out / f"opus-{o['slug']}-{pal.theme}.png")


# ---------- Überschriften ----------
def build_head(hd, fonts, pal, out):
    W, H = DW, 84
    c = Canvas(W, H)
    c.text(PAD, 12, hd["kicker"].upper(), fonts.mono(11), pal.muted, 0.18)
    w = c.text(PAD - 2, 70, hd["title"], fonts.serif(56), pal.paper)
    c.text(PAD + w + 4, 43, hd["mark"], fonts.mono(12), pal.acctext)
    button(c, W - PAD, 41, hd["button"], fonts, pal, ghost=True)
    save_png(c, out / f"head-{hd['slug']}-{pal.theme}.png")


# ---------- Fußzeile ----------
def build_foot(fonts, pal, out):
    W, H = DW, 180
    c = Canvas(W, H)
    c.rect(PAD, 0, W - PAD, 1, fill=pal.line)
    f = fonts.serif(160)
    c.d.text((W * S / 2, 138 * S), "HJORVEN", font=f, anchor="ms", fill=(0, 0, 0, 0), stroke_width=S, stroke_fill=(*pal.line, 255))
    fm = fonts.mono(10)
    c.text(PAD, 172, "OFFICINA HJORVEN · MMXXVI", fm, pal.muted, 0.16)
    s = "HJORVEN.GITHUB.IO"
    c.text(W - PAD - text_width(s, fm, 0.16) + 0.16 * 10, 172, s, fm, pal.muted, 0.16)
    save_png(c, out / f"foot-{pal.theme}.png")


def main():
    ap = argparse.ArgumentParser(description="Baut die Grafiken für das GitHub-Profil.")
    ap.add_argument("portfolio", type=Path, help="Pfad zum geklonten Repo hjorven.github.io")
    ap.add_argument("--accent", default="cobalt", choices=sorted(ACCENTS), help="Akzentfarbe wie auf der Seite")
    ap.add_argument("--out", type=Path, default=ROOT / "assets")
    ap.add_argument("--skip-hero", action="store_true", help="Titelbild auslassen (das Rendern dauert etwa eine Minute)")
    args = ap.parse_args()
    portfolio = args.portfolio.resolve()
    if not (portfolio / "tools" / "render.py").is_file():
        sys.exit(f"{portfolio} sieht nicht nach dem Portfolio-Repo aus (tools/render.py fehlt).")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # render.py liest beim Import seinen Ausgabeordner aus sys.argv (so macht es auch hero_layers.py)
    sys.argv = [sys.argv[0], str(out)]
    sys.path.insert(0, str(portfolio / "tools"))
    import render as R

    fonts = Fonts(portfolio)
    fig = None if args.skip_hero else render_figure(R)
    for theme in ("dark", "light"):
        pal = Palette(theme, args.accent)
        print(f"Thema {theme}", flush=True)
        if fig:
            build_hero(R, fig, fonts, pal, portfolio, out)
        for i, o in enumerate(OPERA):
            build_card(R, o, i, fonts, pal, portfolio, out)
        for hd in HEADS:
            build_head(hd, fonts, pal, out)
        build_foot(fonts, pal, out)
    print("Fertig.")


if __name__ == "__main__":
    main()
