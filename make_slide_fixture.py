"""Render a clearly synthetic slide test fixture; no user's photo or research data."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

root=Path(__file__).parent/'debug_artifacts'
root.mkdir(exist_ok=True)
image=Image.new('RGB',(1200,700),'white')
draw=ImageDraw.Draw(image)
font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',42)
draw.multiline_text((70,70),'SYNTHETIC TEST SLIDE\n\nIndoor positioning\nWi-Fi fingerprinting and BLE beacons\nMedian localization error: 2 meters\nRSSI: -65 dBm',fill='black',font=font,spacing=22)
image.save(root/'slide-fixture.png')
print(root/'slide-fixture.png')
