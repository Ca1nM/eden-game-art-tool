# Game Art Tool for Eden / Eglantine

Adds the **name and icon** to games kept as loose dump folders (a folder with `exefs/` and `romfs/`), so they
stop showing as a blank "Directory" in the emulator's game list. It works for **any game**, not one title.

## Use

Drag the game's folder onto `game-art.exe`, or run `game-art.exe "D:\Games\My Game"`.

It reads the game's title ID from `main.npdm`, looks the game up in the public title database
([blawar/titledb](https://github.com/blawar/titledb), downloaded once and cached for 30 days, about 85 MB),
downloads the official icon, and writes `control.nacp` (the name) and `icon.png` into the game folder.
Refresh the game list, or restart the emulator.

* If the database does not know the game, run it again with `--name "Game name"`; the cover is then taken from
  the cover image on the game's Wikipedia article.
* `--exefs` also writes the two files into the `exefs` folder, for emulators that only look there. Eglantine also
  checks the game folder.
* It never overwrites existing files unless you pass `--force`. `--dry-run` shows what it would do.
* Works with `<game>/exefs`, `<game>/base/exefs` and `<game>/updates/<id>/exefs` layouts.

Needs an internet connection. Artwork comes from Nintendo's store image server or Wikipedia and is only saved on
your PC. No game files are read other than `main.npdm`.

## Tested with

* **Mario Kart World**: a Switch 2 dump in Eglantine. The name and cover show in the game list.
* Title lookup and icon download for **Mario Kart 8 Deluxe** and **The Legend of Zelda: Breath of the Wild**, on
  both `<game>/exefs` and `<game>/base/exefs` layouts.
* The Wikipedia cover fallback with **Stardew Valley** and **Celeste**.

Only Eglantine's game list was used to check the result; other emulators were not tested.

## Build from source

`python game_art.py <folder>` (Python 3.8+, needs Pillow: `pip install pillow`).
`pyinstaller --onefile --console --name game-art game_art.py` builds the exe.

The exe is unsigned and packed with PyInstaller, which some antivirus tools flag by default; the full source is in
this repository. Not affiliated with Nintendo or any emulator project.
