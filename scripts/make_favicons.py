from PIL import Image
import os

os.chdir('/app/frontend/public')
src = Image.open('sac_src.png').convert('RGBA')

# 1) Knock out the near-white/cream background -> transparent
px = src.load()
w, h = src.size
for y in range(h):
    for x in range(w):
        r, g, b, a = px[x, y]
        # light/cream pixels become transparent; keep the blue mark
        if r > 225 and g > 225 and b > 220:
            px[x, y] = (r, g, b, 0)

# 2) Crop to content bounding box
bbox = src.getbbox()
mark = src.crop(bbox)

# 3) Square it with transparent padding (12% margin)
mw, mh = mark.size
side = max(mw, mh)
pad = int(side * 0.12)
canvas = side + pad * 2
squared = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
squared.paste(mark, ((canvas - mw) // 2, (canvas - mh) // 2), mark)

def save_png(size, name):
    squared.resize((size, size), Image.LANCZOS).save(name)

save_png(16, 'favicon-16x16.png')
save_png(32, 'favicon-32x32.png')
save_png(180, 'apple-touch-icon.png')
save_png(192, 'android-chrome-192x192.png')
save_png(512, 'android-chrome-512x512.png')

# 4) Multi-resolution favicon.ico (transparent)
squared.save('favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

# 5) Open Graph / Twitter card image (1200x630) on brand-dark background
og = Image.new('RGBA', (1200, 630), (3, 4, 8, 255))
# subtle sapphire glow block
glow = Image.new('RGBA', (1200, 630), (0, 0, 0, 0))
gpx = glow.load()
import math
cx, cy = 300, 315
for y in range(630):
    for x in range(1200):
        d = math.hypot(x - cx, y - cy)
        a = max(0, 1 - d / 520)
        if a > 0:
            gpx[x, y] = (31, 95, 208, int(70 * a))
og = Image.alpha_composite(og, glow)
mark_og = squared.resize((360, 360), Image.LANCZOS)
og.paste(mark_og, (150, 135), mark_og)
og.convert('RGB').save('og-image.png', quality=90)

print('done', os.listdir('.'))
