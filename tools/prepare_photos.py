"""Makes website photos from your originals.

Put originals in photos/<home id>/ (e.g. photos/home-1/, git-ignored), then:  python tools/prepare_photos.py

For each photo: turned upright, resized (long side 1600 px and 800 px, JPEG), and stripped of all metadata. Phone
photos carry GPS coordinates, which would publish each home's exact location. Output goes to site/img/<home id>/
and site/img/photos.json, which the website reads. Order and captions come from the file names:
  01-living-room.jpg  ->  first photo, caption "Living room"
  02 kitchen.HEIC     ->  second photo, caption "Kitchen"   (HEIC needs: pip install pillow-heif)
Or pick and order them without renaming anything: an order.txt in the home's folder, one photo per line,
  living-room.jpg | Living room with big-screen TV
Then only the listed photos are used, in that order, with those captions.
Home ids must match PROPERTIES in site/index.html. Re-run after adding, removing or renaming originals.
"""
import json
import pathlib
import re
import sys

from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "photos"
OUT = ROOT / "site" / "img"
SIZES = {"": 1600, "-800": 800}
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_PER_HOME = 20

try:  # iPhone photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    register_heif_opener = None


def caption(stem):
    words = re.sub(r"^\d+[\s._-]*", "", stem).replace("_", " ").replace("-", " ").strip()
    if not words or re.fullmatch(r"(img|dsc|pxl|photo|image)?[\s\d]*", words, re.I):  # IMG_1234 says nothing
        return ""
    return words[0].upper() + words[1:]


def slug(stem):
    stem = re.sub(r"^\d+[\s._-]*", "", stem)  # our own number goes in front
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "photo"


def main():
    if not SRC.is_dir():
        SRC.mkdir()
        print(f"Created {SRC}. Add a folder per home (home-1, home-2, home-3) with your photos, then run again.")
        return 1
    manifest, total = {}, 0
    for home in sorted(p for p in SRC.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        files = sorted((f for f in home.iterdir() if f.suffix.lower() in EXTS), key=lambda f: f.name.lower())
        captions = {}
        order = home / "order.txt"
        if order.exists():  # hand-picked selection and captions
            picked = []
            for line in order.read_text(encoding="utf-8").splitlines():
                name, _, text = (x.strip() for x in line.partition("|"))
                if not name or name.startswith("#"):
                    continue
                if not (home / name).is_file():
                    print(f"  {home.name}: order.txt lists {name!r}, which isn't in the folder; skipped")
                    continue
                picked.append(home / name)
                captions[name] = text
            files = picked
        skipped = [f.name for f in files if f.suffix.lower() in (".heic", ".heif") and not register_heif_opener]
        files = [f for f in files if f.name not in skipped]
        if skipped:
            print(f"  {home.name}: skipped {len(skipped)} HEIC file(s); run  pip install pillow-heif  and try again")
        if len(files) > MAX_PER_HOME:
            print(f"  {home.name}: using the first {MAX_PER_HOME} of {len(files)} photos (by file name)")
            files = files[:MAX_PER_HOME]
        dest = OUT / home.name
        dest.mkdir(parents=True, exist_ok=True)
        made, entries = set(), []
        for n, f in enumerate(files, 1):
            with Image.open(f) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")  # upright, then drop all metadata
                name = f"{n:02d}-{slug(f.stem)}"
                entry = {"alt": captions.get(f.name) or caption(f.stem)}
                for suffix, size in SIZES.items():
                    out = im.copy()
                    out.thumbnail((size, size), Image.LANCZOS)  # long side at most `size`, never enlarged
                    target = dest / f"{name}{suffix}.jpg"
                    out.save(target, "JPEG", quality=82, optimize=True, progressive=True)  # no exif= -> none kept
                    made.add(target.name)
                    key = "src" if not suffix else "small"
                    entry[key], entry[key + "_w"] = f"img/{home.name}/{target.name}", out.width
            entries.append(entry)
        for old in dest.glob("*.jpg"):  # photos you removed or renamed
            if old.name not in made:
                old.unlink()
        if entries:
            manifest[home.name] = entries
            total += len(entries)
            kb = sum((dest / x).stat().st_size for x in made) // 1024
            print(f"  {home.name}: {len(entries)} photos, {kb} KB")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "photos.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{total} photos ready in site/img/. Preview the site, then commit and push to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
