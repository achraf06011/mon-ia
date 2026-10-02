"""Génère icon.ico : le logo « AA » (losange lumineux + A) pour l'icône du bureau. À lancer une fois."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 512
VOID, ACCENT, LIGHT = (5, 5, 8, 255), (108, 99, 255, 255), (228, 224, 255, 255)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(img).rounded_rectangle((8, 8, S - 8, S - 8), radius=110, fill=VOID)

# halo violet derrière le losange
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
c = S / 2
diamond = [(c, 52), (S - 52, c), (c, S - 52), (52, c)]
ImageDraw.Draw(glow).polygon(diamond, outline=ACCENT, width=26)
glow = glow.filter(ImageFilter.GaussianBlur(22))
img = Image.alpha_composite(img, glow)

d = ImageDraw.Draw(img)
d.polygon(diamond, fill=(22, 20, 50, 255))  # intérieur sombre teinté de violet (opaque)
d.line(diamond + [diamond[0]], fill=ACCENT, width=18, joint="curve")

# lettre A (même tracé que le logo web)
def pt(x, y):  # coordonnées du SVG 40x40 -> 512
    return (x / 40 * S, y / 40 * S)

w = 22
d.line([pt(12.5, 27.5), pt(20, 11), pt(27.5, 27.5)], fill=LIGHT, width=w, joint="curve")
d.line([pt(15.6, 22.2), pt(24.4, 22.2)], fill=LIGHT, width=w)
for p in (pt(12.5, 27.5), pt(20, 11), pt(27.5, 27.5), pt(15.6, 22.2), pt(24.4, 22.2)):  # bouts arrondis
    d.ellipse((p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2), fill=LIGHT)

img.save(Path(__file__).with_name("icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon.ico créé")
