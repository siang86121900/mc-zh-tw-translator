"""Render the deterministic project icon into the Windows ICO sizes."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets' / 'mc-translator.ico'

def font(size):
    for path in (r'C:\Windows\Fonts\msjhbd.ttc', r'C:\Windows\Fonts\msjh.ttc'):
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=0)
    return ImageFont.load_default()

def render(size):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 256
    def rect(x1, y1, x2, y2, color):
        draw.rectangle(tuple(round(v * scale) for v in (x1, y1, x2, y2)), fill=color)
    rect(0, 0, 256, 256, '#18212A')
    rect(24, 24, 232, 232, '#6B3F24')
    rect(24, 24, 232, 80, '#4C9A2A')
    rect(24, 24, 232, 40, '#86C440')
    rect(24, 80, 232, 96, '#3B7825')
    for coords in ((40,112,64,136),(88,96,112,120),(152,128,176,152),(192,104,216,128),(56,184,80,208),(128,176,152,200),(184,200,208,216)):
        rect(*coords, '#85502B')
    rect(24, 24, 40, 232, '#10202A'); rect(216, 24, 232, 232, '#10202A'); rect(24, 216, 232, 232, '#10202A')
    # A translation speech bubble; small sizes use three high-contrast pixels.
    rect(80,104,240,232,'#FFFFFF');rect(176,224,216,248,'#FFFFFF')
    if size>=48:
        f=font(round(108*scale))
        left,top,right,bottom=draw.textbbox((0,0),'譯',font=f)
        draw.text((160*scale-(right-left)/2-left,166*scale-(bottom-top)/2-top),'譯',font=f,fill='#235125')
    else:
        for x in (104,152,200):rect(x,152,x+16,176,'#235125')
    return image

OUT.parent.mkdir(parents=True, exist_ok=True)
images = [render(n) for n in (16, 24, 32, 48, 64, 128, 256)]
images[-1].save(OUT, format='ICO', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)], append_images=images[:-1])
images[-1].save(OUT.with_suffix('.png'))
print(OUT)
