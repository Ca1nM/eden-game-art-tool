#!/usr/bin/env python3
"""Give a loose game dump (a folder with exefs/ and romfs/) its name and icon in Eden/Eglantine.

Eden/Eglantine read a game's name from a `control.nacp` and its icon from `icon.png` that sit next
to the ExeFS, in `base/`, or in the game folder. Dumps made from NSP/XCI files lack them, so the
game list shows a blank "Directory". This tool reads the game's title ID from `main.npdm`, looks the
game up in a public title database (blawar/titledb), downloads its official icon, and writes both
files into the game folder.

usage: game_art.py <game folder> [--name "Game name"] [--force] [--dry-run]
"""
import argparse
import io
import json
import os
import struct
import sys
import time
import urllib.parse
import urllib.request

TITLEDB_URL = "https://raw.githubusercontent.com/blawar/titledb/master/US.en.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) eden-game-art/1.0"
ICON = 256


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---- finding the game --------------------------------------------------------------------------
def find_npdm(folder):
    """Return the path of main.npdm inside the folder (depth-limited), or None."""
    best = None
    base_depth = folder.rstrip("\\/").count(os.sep)
    for dirpath, dirnames, filenames in os.walk(folder):
        depth = dirpath.rstrip("\\/").count(os.sep) - base_depth
        if "main.npdm" in filenames:
            p = os.path.join(dirpath, "main.npdm")
            if best is None or depth < best[0]:
                best = (depth, p)
        if depth >= 4:
            dirnames[:] = []
    return best[1] if best else None


def title_id_from_npdm(path):
    data = open(path, "rb").read()
    if data[:4] != b"META":
        raise ValueError("main.npdm is not a valid NPDM file")
    aci0 = struct.unpack_from("<I", data, 0x70)[0]
    if data[aci0:aci0 + 4] != b"ACI0":
        raise ValueError("main.npdm has no ACI0 section")
    return "%016X" % struct.unpack_from("<Q", data, aci0 + 0x10)[0]


def sidecar_folder(npdm_path):
    """The folder the emulator also searches for control.nacp / icon files: the ExeFS folder, then
    up through 'base' / 'update' / title-id folders to the game folder. Use the topmost one."""
    d = os.path.dirname(npdm_path)
    for _ in range(3):
        parent = os.path.dirname(d)
        if not parent or parent == d:
            break
        name = os.path.basename(d.rstrip("\\/")).lower()
        parent_name = os.path.basename(parent.rstrip("\\/")).lower()
        storage = parent_name in ("base", "update", "updates") or (
            parent_name and all(c in "0123456789abcdef" for c in parent_name))
        d = parent
        if not storage:
            break
    return d


# ---- looking the game up -----------------------------------------------------------------------
def cache_path():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(root, "eden-game-art")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "titledb-US.en.json")


def load_titledb(max_age_days=30):
    path = cache_path()
    if not os.path.isfile(path) or time.time() - os.path.getmtime(path) > max_age_days * 86400:
        print("Downloading the title database (about 85 MB, once a month)...")
        tmp = path + ".part"
        with urllib.request.urlopen(urllib.request.Request(TITLEDB_URL, headers={"User-Agent": UA}),
                                    timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lookup(db, title_id):
    tid = title_id.upper()
    for entry in db.values():
        if (entry.get("id") or "").upper() == tid:
            return entry
    # DLC / update ids differ in the last 3 hex digits from the base title id
    base = tid[:13] + "000"
    for entry in db.values():
        if (entry.get("id") or "").upper() == base:
            return entry
    return None


def clean_name(name):
    for ch in ("™", "®", "©", "�"):
        name = name.replace(ch, "")
    return " ".join(name.split())


def wikipedia_image(name):
    """Fallback: the cover image named in the infobox of the game's Wikipedia article. (The
    "page image" API hides non-free files such as game covers, so read the wikitext instead.)"""
    import re
    api = "https://en.wikipedia.org/w/api.php?format=json&redirects=1&"
    for query in (name, name + " (video game)"):
        try:
            data = json.loads(http_get(api + "action=query&prop=revisions&rvprop=content&rvslots=main"
                                       "&titles=" + urllib.parse.quote(query)))
            page = next(iter(data["query"]["pages"].values()))
            text = page["revisions"][0]["slots"]["main"]["*"]
        except Exception:
            continue
        m = re.search(r"\|\s*(?:image|cover)\s*=\s*(?:\[\[)?(?:File:|Image:)?([^\n|\]]+?\.(?:png|jpe?g|webp))",
                      text, re.I)
        if not m:
            continue
        title = "File:" + m.group(1).strip()
        try:
            info = json.loads(http_get(api + "action=query&prop=imageinfo&iiprop=url&iiurlwidth=600"
                                       "&titles=" + urllib.parse.quote(title)))
            img = next(iter(info["query"]["pages"].values()))["imageinfo"][0]
            return img.get("thumburl") or img.get("url")
        except Exception:
            continue
    return None


# ---- writing the files -------------------------------------------------------------------------
def make_nacp(name, publisher, title_id):
    nacp = bytearray(0x4000)
    n = name.encode("utf-8")[:0x1FF]
    p = (publisher or "").encode("utf-8")[:0xFF]
    for i in range(16):
        base = i * 0x300
        nacp[base:base + len(n)] = n
        nacp[base + 0x200:base + 0x200 + len(p)] = p
    struct.pack_into("<I", nacp, 0x302C, 0xFFFF)                  # supported languages
    struct.pack_into("<Q", nacp, 0x3078, int(title_id, 16))       # save data owner id = title id
    return bytes(nacp)


def make_icon(image_bytes):
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = 0 if h > w else (h - side) // 2       # tall box art: keep the top (logo) part
    img = img.crop((left, top, left + side, top + side)).resize((ICON, ICON), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="the game's folder (contains exefs/ or base/exefs/)")
    ap.add_argument("--name", help="game name to use if the title database does not know it")
    ap.add_argument("--exefs", action="store_true",
                    help="also write the files into the exefs folder, for emulators that only look "
                         "there (stock yuzu-style loaders); Eglantine also checks the game folder")
    ap.add_argument("--force", action="store_true", help="overwrite an existing control.nacp/icon.png")
    ap.add_argument("--dry-run", action="store_true", help="show what would be written, write nothing")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print("Not a folder:", folder)
        return 1
    npdm = find_npdm(folder)
    if not npdm:
        print("No main.npdm found under %s. Pass the game's folder (the one containing exefs/)." % folder)
        return 1
    try:
        title_id = title_id_from_npdm(npdm)
    except (ValueError, struct.error) as e:
        print("Could not read the title ID:", e)
        return 1
    target = sidecar_folder(npdm)
    print("Game folder:", target)
    print("Title ID:   ", title_id)

    nacp_path, icon_path = os.path.join(target, "control.nacp"), os.path.join(target, "icon.png")
    if not args.force and (os.path.exists(nacp_path) or os.path.exists(icon_path)):
        print("control.nacp or icon.png already exists there (use --force to replace them).")
        return 0

    name, publisher, icon_url = args.name, "", None
    try:
        entry = lookup(load_titledb(), title_id)
    except Exception as e:
        print("Could not use the title database (%s)." % e)
        entry = None
    if entry:
        name = name or clean_name(entry.get("name") or "")
        publisher = clean_name(entry.get("publisher") or "")
        icon_url = entry.get("iconUrl")
        print("Found in the title database:", name, "|", publisher)
    if not name:
        print("The title database does not know this game. Run again with --name \"Game name\".")
        return 1
    if not icon_url:
        icon_url = wikipedia_image(name)
        print("No official icon in the database; Wikipedia cover:", "found" if icon_url else "not found")
    if not icon_url:
        print("No artwork found. The name will still be added.")
    image = None
    if icon_url:
        try:
            image = make_icon(http_get(icon_url))
        except Exception as e:
            print("Could not download or convert the icon (%s)." % e)

    print("Will write: control.nacp (%s)%s" % (name, " and icon.png" if image else ""))
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0
    targets = [target]
    if args.exefs and os.path.dirname(npdm) != target:
        targets.append(os.path.dirname(npdm))
    nacp_bytes = make_nacp(name, publisher, title_id)
    for folder_out in targets:
        open(os.path.join(folder_out, "control.nacp"), "wb").write(nacp_bytes)
        if image:
            open(os.path.join(folder_out, "icon.png"), "wb").write(image)
        print("Wrote files to:", folder_out)
    print("Done. Refresh the game list (or restart the emulator) to see it.")
    return 0


if __name__ == "__main__":
    code = main()
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty() and len(sys.argv) > 1:
        # started by dragging a folder onto the exe: keep the window open to read the result
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass
    sys.exit(code)
