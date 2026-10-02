"""Génère icon.ico (à lancer une fois)."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# fond : carré arrondi avec dégradé bleu -> violet
grad = Image.new("RGBA", (S, S))
px = grad.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S)
        px[x, y] = (int(40 + 90 * t), int(90 - 20 * t), int(220 - 20 * t), 255)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((16, 16, S - 16, S - 16), radius=110, fill=255)
img.paste(grad, (0, 0), mask)

# grande étincelle blanche (étoile à 4 branches) + une petite
d = ImageDraw.Draw(img)


def sparkle(cx, cy, r, inner=0.28):
    pts = []
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=(255, 255, 255, 255))


sparkle(S * 0.46, S * 0.54, S * 0.30)
sparkle(S * 0.74, S * 0.27, S * 0.12)

img.save(Path(__file__).with_name("icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon.ico créé")
