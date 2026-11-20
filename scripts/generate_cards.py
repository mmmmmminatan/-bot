from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("cards")
OUT.mkdir(exist_ok=True)
for old in OUT.glob("IMG_[0-9][0-9][0-9].png"):
    old.unlink()
W, H = 512, 768
SUITS = [
    ("spade", "♠", (18, 18, 18)),
    ("club", "♣", (18, 18, 18)),
    ("diamond", "♦", (239, 57, 38)),
    ("heart", "♥", (239, 57, 38)),
]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def font(size):
    return ImageFont.truetype(FONT, size)

def centered(draw, text, y, f, fill):
    box = draw.textbbox((0, 0), text, font=f)
    x = (W - (box[2] - box[0])) / 2 - box[0]
    draw.text((x, y), text, font=f, fill=fill)

def base():
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, 504, 760), radius=38, fill=(255,255,255,255),
                        outline=(232,232,232,255), width=3)
    d.rounded_rectangle((30, 30, 482, 738), radius=27, outline=(225,225,225,255), width=2)
    return im, ImageDraw.Draw(im)

ranks = [str(n) for n in range(1, 14)]
rank_labels = {"1":"A", "11":"J", "12":"Q", "13":"K"}
idx = 625
for suit_name, symbol, color in SUITS:
    for value in range(1, 14):
        label = rank_labels.get(str(value), str(value))
        im, d = base()
        size = 232 if len(label) == 1 else 210
        centered(d, label, 150, font(size), color)
        centered(d, symbol, 445, font(205), color)
        im.save(OUT / f"IMG_{idx:04d}.png", optimize=True)
        idx += 1

im, d = base()
centered(d, "JOKER", 240, font(92), (35,35,35))
centered(d, "★", 425, font(190), (239,57,38))
im.save(OUT / f"IMG_{idx:04d}.png", optimize=True)
idx += 1

im, d = base()
d.rounded_rectangle((75, 75, 437, 693), radius=20, fill=(250,250,250,255),
                    outline=(220,220,220,255), width=4)
for y in range(105, 680, 48):
    d.line((95, y, 417, y+160), fill=(225,225,225,255), width=5)
centered(d, "✦", 300, font(150), (65,65,65))
im.save(OUT / f"IMG_{idx:04d}.png", optimize=True)
print(f"Generated {idx-624} card PNGs in {OUT}")

# Regenerate canonical RGBA card assets with transparent outer backgrounds.
