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
