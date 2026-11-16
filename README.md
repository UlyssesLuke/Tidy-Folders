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

1. **Sort page:** add folders (Downloads, Desktop, Documents or any other), click
   **Preview** to see exactly what would move, then **Tidy up!**.
2. **Exclude a group:** in the Preview, click **Exclude** on any group (a course, a
   code word, or a type like Other) and its files are left where they are, by
   Tidy up! and auto-sort alike. Click **Include again** there, or **Include** on the
   Categories page, to sort them again. All courses share one **Courses** row and
   all code words one **Code words** row: **Show courses ▾** / **Show code words ▾**
   lists each one (each with its own Exclude), and **Exclude all** / **Include all**
   act on every course (or code word) at once, including ones added later.
3. **Categories page:** change which file types go into which folder, or click
   the **Add file type** box (last in the grid) to make your own. Each file type gets a logo: pick one of 8
   symbols and one of 9 colours, or upload your own picture (24×21 pixel art looks
   best; bigger pictures are shrunk to fit). Click any file type to change it or its logo.
4. **History page:** every tidy-up is listed and can be undone.
5. **Automatic sorting:** switch it on, then click **Tidy up!** once. Nothing moves
   until you do, so the first tidy-up is always yours to check. After that, new
   files are sorted by themselves. Files are left alone until they're a minute old,
   so downloads can finish.

A category folder like `Installers` or `Music` doesn't need to exist beforehand:
it's created the first time a file needs it, and never created if no file does.
It goes inside the folder being tidied, so Code files in Downloads go to
`Downloads\Code`. In the Preview, a small folder-with-a-plus symbol next to a group
means that folder doesn't exist yet and Tidy up! will create it (hover it to see
where). Hover the blue **→ Folder\\** label to see the full path files go to.

**Choosing where a new folder goes:** click that symbol to pick a different place.
For a file type, e.g. 3D Printing, its folder is then made there (say
`Documents\3D Printing`) for every folder you tidy, and the file type's card on the
Categories page shows it; **Reset location** in the Preview puts it back. Picking a
folder that's already called 3D Printing uses it as is. For a code word, its folder
moves to the place you pick. On the Code words row, the symbol opens the list so you
can choose for each one.
Undo removes any folder a tidy-up created, as long as it's empty again.

## Course folders and code words

On the **Categories** page, under **Send files by name**:

- **Course folders:** pick a folder that holds your course folders. Course folders
  are found anywhere inside it, including inside year and semester folders (up to 5
  folders deep). A course folder's name starts with a course code: letters, then
  3 or 4 digits, like `ELECTENG 101` or `ELECTENG 101 - Circuits`. Any file whose
  name contains that code goes into it: `ELECTENG101_Lab1.pdf`,
  `electeng 101 notes.docx` and `ElectEng_101.zip` all go to `ELECTENG 101`.
  Capitals, spaces, dashes and underscores don't matter, and a new course folder
  works straight away. If the same course is in more than one place, the newest
  year or semester is used.
- **Code words:** a word plus a folder, e.g. `invoice` → `Documents\Finance`.

These are checked before file types: course folders first, then code words.
Preview shows where each file will go, and Undo works the same as always.
The Courses and Code words rows use `assets/categories/Course.png` and
`Code word.png` (24×21); each course or code word inside them uses the plain folder.

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
| `faces/` | The folder buddy: happy, happy_tongue, sad, dead, smug, surprised, front (24×21). `front` is the plain face, also used for file types without a logo |
| `categories/` | One icon per category, named after it, e.g. `Images.png` (24×21) |
| `nav/` | Sidebar icons (16×16) |
| `button/` | The Tidy up! button: normal, hover, pressed (48×16) |
| `switch/` | The auto-sort switch: on, off (20×10) |
| `sparkle/` | Celebration sparkle frames 1-3 (8×8) |
| `glyphs/` | Symbols for file-type logos, `1.png`-`8.png` (16×14, white on transparent; the app puts them on a coloured tile), plus `upload.png` for the "upload your own" tile and `add.png` for the Add file type box. Uploaded logos are kept in `%APPDATA%\TidyFolders\icons` |
| `badges/` | `new_folder.png`: shown in the Preview next to a folder that will be created (16×14) |
| `sorting/` | The sorting animation: `Sorting_1.png`, `Sorting_2.png`... (24×21, any number of frames) plus `timings.txt` (milliseconds per frame). Plays while files move, when auto-sort tidies something, and when you click the buddy |
| `logo/` | The app logo, `24.png`; `build.bat` makes the other sizes and `icon.ico` from it |
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
