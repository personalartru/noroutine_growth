"""Проверка лид-магнита: содержимое архива совпадает с исходниками.

Байтовое сравнение ZIP не годится: разные версии zlib дают разные
сжатые данные. Сверяем состав архива и содержимое каждого файла.
"""
import hashlib
import json
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATERIALS = os.path.join(BASE, "materials")
ZIP_PATH = os.path.join(MATERIALS, "noroutine-n8n-pack.zip")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if not os.path.exists(ZIP_PATH):
        print("Архив не собран — запустите build_materials.py")
        return 1

    sources = {"README.md": os.path.join(MATERIALS, "README.md")}
    for folder, prefix in (("workflows", "workflows"), ("workflows-bonus", "workflows-bonus")):
        base = os.path.join(MATERIALS, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            sources[f"{prefix}/{name}"] = os.path.join(base, name)

    with zipfile.ZipFile(ZIP_PATH) as z:
        names = set(z.namelist())
        problems = []
        for arc, src in sources.items():
            if arc not in names:
                problems.append(f"нет в архиве: {arc}")
                continue
            with open(src, "rb") as f:
                if digest(z.read(arc)) != digest(f.read()):
                    problems.append(f"содержимое отличается: {arc}")
        extra = names - set(sources)
        for arc in sorted(extra):
            if arc.startswith("functions/"):
                continue
            problems.append(f"лишний файл в архиве: {arc}")

        for arc in sorted(n for n in names if n.endswith(".json")):
            try:
                data = json.loads(z.read(arc).decode("utf-8"))
            except ValueError as e:
                problems.append(f"невалидный JSON: {arc} ({e})")
                continue
            if not data.get("nodes") or not data.get("connections"):
                problems.append(f"пустой воркфлоу: {arc}")

    if problems:
        print("Материалы не прошли проверку:")
        for p in problems:
            print("  -", p)
        return 1

    print(f"Ок: {len(sources)} файлов, состав и содержимое архива совпадают с исходниками.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
