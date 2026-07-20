# -*- coding: utf-8 -*-
"""ZWCAD 리본용 rail 명령 아이콘 생성 (16x16 / 32x32, PNG+BMP).
   각 크기를 따로 그려 작은 크기에서도 선이 뭉개지지 않게 함."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\icons'
os.makedirs(OUT, exist_ok=True)

INK = (32, 38, 48, 255)      # 레일 본체 (진회색)
ACC = (0, 122, 204, 255)     # 강조 (파랑) — 숫자/화살표
ACC2 = (198, 63, 33, 255)    # 강조2 (주황빨강) — 폭
BG = (255, 255, 255, 0)      # 투명

def font(px, bold=True):
    f = 'arialbd.ttf' if bold else 'arial.ttf'
    return ImageFont.truetype(os.path.join(r'C:\Windows\Fonts', f), px)

def rails(d, S, x0, x1, y0, y1, w, ties=3, ink=INK):
    """세로 레일 2줄 + 가로 타이(조인트) — 단순화 글리프"""
    d.rectangle([x0, y0, x0 + w - 1, y1], fill=ink)
    d.rectangle([x1 - w + 1, y0, x1, y1], fill=ink)
    if ties:
        for k in range(ties):
            y = y0 + int((y1 - y0) * (k + 1) / (ties + 1))
            d.rectangle([x0, y, x1, y + w - 1], fill=ink)

def arrow_v(d, x, y0, y1, w, col, head):
    """세로 양방향 화살표"""
    d.rectangle([x - w // 2, y0, x - w // 2 + w - 1, y1], fill=col)
    d.polygon([(x, y0 - head), (x - head, y0 + 1), (x + head, y0 + 1)], fill=col)
    d.polygon([(x, y1 + head), (x - head, y1 - 1), (x + head, y1 - 1)], fill=col)

def arrow_h(d, y, x0, x1, w, col, head):
    d.rectangle([x0, y - w // 2, x1, y - w // 2 + w - 1], fill=col)
    d.polygon([(x0 - head, y), (x0 + 1, y - head), (x0 + 1, y + head)], fill=col)
    d.polygon([(x1 + head, y), (x1 - 1, y - head), (x1 - 1, y + head)], fill=col)

def badge(d, S, text, col):
    """우하단 숫자/기호 배지 (캔버스 안으로 클램프)"""
    fp = font(int(S * (0.52 if S >= 32 else 0.60)))
    tb = d.textbbox((0, 0), text, font=fp)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    x = min(S - tw - 1, S - tw - max(1, S // 16))
    y = min(S - th - 1, S - th - max(1, S // 16))
    x, y = max(0, x), max(0, y)
    # 흰 테두리로 가독성 확보
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                d.text((x + dx - tb[0], y + dy - tb[1]), text, font=fp, fill=(255, 255, 255, 255))
    d.text((x - tb[0], y - tb[1]), text, font=fp, fill=col)

def draw(name, S):
    img = Image.new('RGBA', (S, S), BG)
    d = ImageDraw.Draw(img)
    w = max(1, S // 11)                 # 선 두께
    m = max(1, S // 12)                 # 여백
    if name in ('DRAWRAIL', 'DRAWRAIL2', 'DRAWRAIL3', 'DRAWRAIL4'):
        # 레일 + (번호 배지 | + 기호)
        x0, x1 = m + S // 8, S - m - S // 8
        rails(d, S, x0, x1, m, S - m - (S // 3 if S >= 32 else S // 3), w, ties=2)
        lbl = {'DRAWRAIL': '+', 'DRAWRAIL2': '2', 'DRAWRAIL3': '3', 'DRAWRAIL4': '4'}[name]
        badge(d, S, lbl, ACC)
    elif name == 'RAILLEN':
        x0, x1 = m, S // 2 + (0 if S < 32 else 1)
        rails(d, S, x0, x1, m, S - m - 1, w, ties=2)
        arrow_v(d, S - m - max(2, S // 8), m + max(2, S // 8), S - m - max(3, S // 8),
                max(1, w - (0 if S >= 32 else 1)), ACC, max(2, S // 8))
    elif name == 'RAILWID':
        y0, y1 = m, S - m - max(3, S // 5)
        rails(d, S, m, S - m - 1, y0, y1, w, ties=1)
        arrow_h(d, S - m - max(2, S // 9), m + max(2, S // 8), S - m - max(3, S // 8),
                max(1, w - (0 if S >= 32 else 1)), ACC2, max(2, S // 8))
    elif name == 'RAILLIST':
        rows = 4 if S >= 32 else 3
        bw = max(1, S // 8)
        for k in range(rows):
            y = m + k * (S - 2 * m) // rows
            d.rectangle([m, y, m + bw, y + max(1, w - 1)], fill=ACC)
            d.rectangle([m + bw + max(2, S // 12), y, S - m - 1, y + max(1, w - 1)], fill=INK)
    elif name == 'RAILPROPS':
        x0, x1 = m, S - m - max(4, S // 3)
        rails(d, S, x0, x1, m, S - m - 1, w, ties=2)
        # 돋보기 (손잡이 포함 전체가 캔버스 안에 들어오도록)
        lw = max(1, S // 16)
        tail = max(2, S // 8)
        r = max(3, S // 4)
        cx = S - 1 - tail - r - lw
        cy = S - 1 - tail - r - lw
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACC, width=lw)
        hx, hy = cx + int(r * 0.72), cy + int(r * 0.72)
        d.line([hx, hy, hx + tail, hy + tail], fill=ACC, width=max(1, lw + (1 if S >= 32 else 0)))
    return img

CMDS = ['DRAWRAIL', 'DRAWRAIL2', 'DRAWRAIL3', 'DRAWRAIL4',
        'RAILLEN', 'RAILWID', 'RAILLIST', 'RAILPROPS']
made = []
for c in CMDS:
    for S, tag in ((16, '16'), (32, '32')):
        img = draw(c, S)
        png = os.path.join(OUT, '%s_%s.png' % (c, tag))
        img.save(png)
        # BMP: 흰 배경 합성 (구버전 CUI 호환)
        bmp = Image.new('RGB', (S, S), (255, 255, 255))
        bmp.paste(img, (0, 0), img)
        bmp.save(os.path.join(OUT, '%s_%s.bmp' % (c, tag)))
        made.append(os.path.basename(png))
print('생성 %d개 → %s' % (len(made) * 2, OUT))

# 미리보기 시트 (확대해서 눈으로 확인)
Z = 6
sheet = Image.new('RGB', (len(CMDS) * (32 * Z + 12) + 12, 32 * Z + 16 * Z + 40), (245, 246, 248))
sd = ImageDraw.Draw(sheet)
fp = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 13)
for i, c in enumerate(CMDS):
    x = 12 + i * (32 * Z + 12)
    b32 = Image.open(os.path.join(OUT, '%s_32.png' % c)).convert('RGBA')
    b16 = Image.open(os.path.join(OUT, '%s_16.png' % c)).convert('RGBA')
    p32 = Image.new('RGB', (32, 32), (255, 255, 255)); p32.paste(b32, (0, 0), b32)
    p16 = Image.new('RGB', (16, 16), (255, 255, 255)); p16.paste(b16, (0, 0), b16)
    sheet.paste(p32.resize((32 * Z, 32 * Z), Image.NEAREST), (x, 8))
    sheet.paste(p16.resize((16 * Z, 16 * Z), Image.NEAREST), (x + (32 * Z - 16 * Z) // 2, 8 + 32 * Z + 8))
    sd.text((x, 8 + 32 * Z + 16 * Z + 14), c, font=fp, fill=(30, 30, 30))
prev = os.path.join(OUT, '_미리보기.png')
sheet.save(prev)
print('미리보기:', prev)
