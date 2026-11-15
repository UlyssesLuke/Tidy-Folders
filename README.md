# Tidy Folders

Tidy Folders is just a personal application for me to sort out my computer folders.

It's a Windows desktop app that sorts the loose files in your folders (Downloads,
Desktop, Documents...) into category folders like `Images`, `Documents` and `Music`.

## Open it

**The app:** `dist\Tidy Folders.exe`. It's a single file and needs nothing else
installed. Copy it anywhere (Desktop, `C:\Apps`...) and right-click it to
**Pin to Start** or **Pin to taskbar**. Opening it a second time just brings the
open window to the front.

**From source:** double-click `Tidy Folders.pyw`, or run `python -m tidy_folders`.

## Rebuild the .exe after changing the code

Double-click **`build.bat`**. The first run sets up the build tools in `.venv`
(PyInstaller, Pillow); later runs take about a minute. Output: `dist\Tidy Folders.exe`.

The icon is drawn by `packaging/make_icon.py` (delete `tidy_folders/assets/icon.ico`
to regenerate it), and the Properties > Details info comes from
`packaging/version_info.txt`.

If you give the .exe to someone else, Windows may say "Windows protected your PC"
the first time, because the file isn't code-signed. They can click
**More info > Run anyway**.

## How it works

1. **Sort tab:** add folders (or use the Downloads / Desktop / Documents buttons),
   click **Preview** to see exactly what would move, then **Sort now**.
2. **Categories tab:** change which file types go into which folder, or add your own.
3. **History & undo tab:** every sort is listed and can be undone.
4. **Automatic sorting:** tick the box and new files get sorted every few seconds.
   Files are left alone until they're a minute old, so downloads can finish.

## Course folders and code words

On the **Categories** page, under **Send files by name**:

- **Course folders:** pick a folder that holds your course folders, like
  `UoA\2026\Sem 2`. Any file whose name contains a course code goes into that
  course's folder: `ELECTENG292_Lab1.pdf`, `electeng 292 notes.docx` and
  `ElectEng_292.zip` all go to `Sem 2\ELECTENG 292`. Capitals, spaces, dashes and
  underscores don't matter. Only folders whose names mix letters and numbers count
  as codes, and a new course folder works straight away.
- **Code words:** a word plus a folder, e.g. `invoice` → `Documents\Finance`.

These are checked before file types: course folders first, then code words.
Preview shows where each file will go, and Undo works the same as always.
Optional art: `assets/categories/Course.png` and `Code word.png` (24×21) replace
the neutral folder on those rows.

## Tray and start with Windows

- **Closing the window** hides it to the tray (the icons next to the clock; on
  Windows 11 new icons start under the **^** arrow, and you can drag it out next to
  the clock). Sorting keeps running.
- **Click the tray icon** to open the window. **Right-click** it for *Sort now*,
  *Automatic sorting* on/off and *Quit*.
- **"Start Tidy Folders when I sign in to Windows"** (bottom of the Sort tab) opens
  it quietly in the tray each time you log in. You can also switch this off in
  Windows Settings > Apps > Startup. Turn it off before deleting the .exe.
- If you move the .exe, open it once from its new place and start-up follows it.
- Opening the app while it's already running just brings the window back.

The tray and start-up options are part of the .exe. When running from source they
need `pip install -r requirements.txt` (tray) or aren't available (start-up).

## Art and font

All the pixel art lives in `tidy_folders/assets/`:

| Folder | What it is |
| --- | --- |
| `faces/` | The folder buddy: happy, happy_tongue, sad, dead, smug, surprised, front, normal (24×21) |
| `categories/` | One icon per category, named after it, e.g. `Images.png` (24×21) |
| `nav/` | Sidebar icons (16×16) |
| `button/` | The Tidy up! button: normal, hover, pressed (48×16) |
| `switch/` | The auto-sort switch: on, off (20×10) |
| `sparkle/` | Celebration sparkle frames 1-3 (8×8) |
| `tray/` | Tray icons, 16.png and 32.png; `icon.ico` is made from these by `build.bat` |
| `fonts/` | Pixelify Sans Bold, used for headings (SIL Open Font License, see `OFL.txt`) |

To change a piece of art, replace its PNG with one the same size and rebuild. The app
scales everything up by whole numbers, so pixels stay crisp. A new category without
its own icon uses the neutral folder.

## Safety rules

- Only files sitting directly in a chosen folder move. Existing subfolders and
  their contents are never touched.
- Nothing is deleted or overwritten. Name clashes become `photo (2).jpg`.
- Skipped: hidden/system files, shortcuts (optional), Office lock files (`~$...`),
  unfinished downloads (`.crdownload`, `.part`), and, for auto-sort, files
  less than a minute old.
- Drive roots, your whole user folder, Windows, Program Files and AppData
  can't be added.

Settings and undo history are stored in `%APPDATA%\TidyFolders`.

## Tests

```
python -m unittest discover tests -v
```
