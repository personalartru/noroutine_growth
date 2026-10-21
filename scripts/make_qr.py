"""Генератор QR-кодов для сайта и материалов.

Примеры:
    python scripts/make_qr.py https://t.me/mybot?start=site ../noroutine/lead-qr.png
    python scripts/make_qr.py https://t.me/noroutine2026 ../noroutine/tg-channel-qr.png
"""
import os
import sys

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def make(url, path, box_size=12, border=2):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f1115", back_color="white").convert("RGB")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, "PNG")
    print("Сохранено:", path, img.size)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    make(sys.argv[1], sys.argv[2])
