"""Génère icon.ico : le logo « AA » (losange néon + M/A) pour l'icône du bureau. À lancer une fois."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 512
K = S / 100  # le logo est dessiné dans un carré 100x100
VOID, GLOW, LINE = (5, 5, 8, 255), (108, 99, 255, 255), (154, 146, 255, 255)


def P(x, y):
    return (x * K, y * K)


diamond = [P(50, 6), P(94, 50), P(50, 94), P(6, 50)]
strokes = [  # (points, épaisseur)
    ([P(39, 26.7), P(27.9, 77.6)], 5.2),
    ([P(60.4, 26.7), P(70.8, 77.6)], 5.2),
    ([P(39, 26.7), P(49.7, 43), P(60.4, 26.7)], 5.2),
    ([P(32.6, 59), P(46.4, 59)], 5.2),
    ([P(53.6, 59), P(67.4, 59)], 5.2),
]


def draw_logo(d, color, extra=0):
    d.line(diamond + [diamond[0]], fill=color, width=int(4.4 * K) // 2 + extra, joint="curve")
    for pts, w in strokes:
        width = int(w * K / 2) + extra
        d.line(pts, fill=color, width=width, joint="curve")
        for p in (pts[0], pts[-1]):  # bouts arrondis
            r = width / 2
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=color)


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(img).rounded_rectangle((8, 8, S - 8, S - 8), radius=110, fill=VOID)

# halo néon : le tracé flou, deux fois
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw_logo(ImageDraw.Draw(glow), GLOW, extra=8)
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(20)))
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(8)))

draw_logo(ImageDraw.Draw(img), LINE)

img.save(Path(__file__).with_name("icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon.ico créé")
