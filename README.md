# Touch Audio – Raspberry Pi audiobook & music player

A touchscreen-first **Python / PyQt5 + VLC** media player with:

- Full-screen touch UI (also works with mouse), with switchable fullscreen / windowed mode.
- Dynamically discovered categories and merged entries from **group**, **direct**, and **category_folders** sources.
- Folder arrows, a full-height Browse All dialog with large cover thumbnails, and a separate global Search dialog (all albums, current category, or files only).
- Configurable metadata lines for both folders and individual audio files (file artist is hidden by default).
- Folder cover files (`cover.jpg`, `folder.png`, `front.jpeg`, `albumart.webp`, etc.).
- Progress-indicated scanning on startup (optional) or **Refresh**; the last successful library index is saved for scan-free starts. Audio tags are cached in SQLite.
- YAML configuration, **Options** modal, and YAML-based translation lookup; independent dialog-list text scaling.
- Optional **categoryless mode** for browsing and cycling through every entry across all categories.
- **Repeat file** and **repeat album** playback modes, with GREEN indicators only while enabled; tap an enabled mode to turn it off. Includes LAN remote controls.
- LAN web player with volume, playback, search by metadata/filename, entry/track selection, seeking, and a shutdown timer.
- Timer fading audio volume over **30 seconds** after the requested delay, followed by `systemctl poweroff`.
- Arrow/Enter keyboard navigation, F11 fullscreen, space play/pause, Ctrl+arrows tracks; an explicit navigation-command adapter for later GPIO.

## Upgrading an existing installation

**Keep your existing `config.yaml`.** The update ZIP intentionally does not contain a
`config.yaml`, so extracting its contents into your existing `touch_audio_player/`
folder will replace the application source without overwriting your folders, LAN
token, or other preferences. A new `config.yaml` is automatically generated at the
first launch if none exists (use `config.example.yaml` as a reference). The `ui_scale` and `text_scale` fields default to `1.5` when absent in older files.
You can configure them later via **Options → Display**.

You may have to rerun `./create_desktop_icon.sh` and `./autostart.sh enable`
if you move the folder. You do **not** need to modify any existing media files or
the SQLite library cache.

## Install on Raspberry Pi 4B

Use **Raspberry Pi OS with Desktop** (64-bit recommended). The installation is intended for the normal graphical desktop session, not a pure text console. From the extracted project folder:

```bash
chmod +x install.sh
./install.sh
python3 app.py
```

Dependencies are `python3-pyqt5`, `python3-pyqt5.qtsvg`, `vlc`, `libvlc5`, `python3-vlc`, `python3-yaml`, `python3-ruamel.yaml`, `python3-mutagen`, and `python3-flask` (installed from the distro repositories). On Bookworm and later, do not `sudo pip install` these packages into the system Python; use apt or a virtual environment. If your distro does not expose one of the listed packages, use `apt search` to find the equivalent or make a venv with `--system-site-packages` and install the missing Python-only packages using `requirements.txt`.

For a normal window on a development desktop:

```bash
python3 app.py --windowed
```

The program needs a working audio output: select HDMI/3.5 mm/USB audio in the Raspberry Pi OS sound settings. Running the UI in a desktop session is important for Qt's full-screen window and touchscreen input. Some Wayland desktops have compositor-specific full-screen behavior; F11 or Escape returns to a normal window.

## Configure media sources

Edit `config.yaml` (automatically created on first launch) or open **Options → Sources**. `~` and environment variables are expanded for all three source types. Missing directories are reported in the status line; they are not fatal.

```yaml
language: en
group_folders:
  - ~/audio
  - /media/usb1/library
direct_folders:
  audiobooks: ~/books
  music: /media/usb2/albums
category_folders:
  audiobooks:
    - /media/usb3/audio-books
    - ~/extra-books
  funny: /mnt/special/jokes
categoryless: false
scan_on_startup: true
```

Expected group layout:

```text
~/audio/
  audiobooks/
    Dune/
      cover.jpg
      01 Intro.mp3
      02 Chapter.mp3
    Little Prince/
      folder.png
      chapter01.ogg
  music/
    My Album/
      front.jpg
      song01.flac
  funny/
    Sketches/
      episode01.mp3
  educational/
    Language Course/
      Unit 01/01.mp3
```

A **group folder** contains category subdirectories, and each category contains entry folders. A **direct folder** maps a category name to one directory. The third form, **`category_folders`**, explicitly attaches one or more additional category directories to a category name (a single string path or a YAML list of paths). This makes it straightforward to attach `audiobooks` from USB drives and custom locations without changing the existing `direct_folders` mapping. All roots are combined under the same category; unknown categories appear automatically. Direct files in a category folder are treated as a single entry, named after that folder. Individual entry folders can contain nested audio files (e.g., CDs or units). Duplicate filesystem locations within a category are indexed once.

The folders contain *media files*, not a custom database. On startup (unless disabled) and manual refresh, the app discovers folders and reads file tags, using an on-disk SQLite cache (default `~/.cache/touch_audio_player/library.sqlite3`) to avoid rereading unchanged files. It supports MP3, FLAC, Ogg, Opus, AAC, M4A/MP4 audio, WAV, WMA, and AIFF, subject to VLC codecs. Most common metadata is read via Mutagen; missing/unsupported metadata is shown as a fallback instead of blocking playback.

If you have many files, the initial scan can take a while; scanning is done in a background thread, with a visible progress bar (folder discovery is indeterminate, then the bar counts completed entry directories). To skip the startup scan, set `scan_on_startup: false` or use Options → Display. The previously saved index (`~/.cache/touch_audio_player/library.library.json` by default) is restored, if one exists; otherwise the library remains empty until **Refresh**. Media added or removed since the last scan will not appear until Refresh. New category names are not hard-coded. Icons are built in for audiobooks, music, funny, and educational; unknown categories have a generic folder icon.

## LAN controller

On launch the app starts a web server if `web.enabled: true`. Default: `0.0.0.0:8765`, reachable from the same network at:

```
http://<raspberry-pi-ip>:8765
```

For example, from your phone open `http://raspberrypi.local:8765` if mDNS is configured. The web page asks for a token. **The first app launch generates a strong random token**, stored in `config.yaml`; see it under **Options → LAN controller → Show token** (or view the YAML). The web page keeps it only in that browser tab's session storage. All REST API routes require `Authorization: Bearer <token>`. The web server has **no TLS**, so it is intended strictly for a *trusted home LAN*, not the public Internet. Do **not** forward port 8765 to the Internet. To limit access to the Pi itself, set `host: 127.0.0.1`; for a VPN, bind to the VPN interface. The token is stored in a permissions-restricted config on first creation/save; if you copied a config file, verify its filesystem permissions.

Example API calls:

```bash
TOKEN='token_from_config'
BASE='http://raspberrypi.local:8765'
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/state"
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/search?q=dune"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"next"}' "$BASE/api/control"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"volume","value":55}' "$BASE/api/control"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"timer","seconds":1800}' "$BASE/api/control"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"timer","seconds":0}' "$BASE/api/control"
```

Search returns entry IDs and matching track indices; send `{"action":"select","entry_id":"...","file_index":0}` to play one. `seek` takes `seconds`; actions `play`, `pause`, `toggle`, `stop`, `next`, `previous`, `refresh`, and `repeat` (`{"action":"repeat","mode":"file"}` / `"album"` / `"off"`) also work. Web commands run on the main Qt thread through a signal bridge so playback control is not called from a Flask request thread.

**Shutdown timer:** Start it in the UI or through the web controller; it waits your chosen delay, decreases the app volume smoothly over 30 seconds, then calls `systemctl poweroff`. The countdown includes the fade interval, so a 30-minute timer will power off about 30 minutes and 30 seconds after starting. Cancelling while fading restores the pre-fade volume. Shutdown permissions depend on the OS/login session; if they are denied, the UI shows an error. This shuts down the **entire Raspberry Pi**, not only the player. Save other work first. The timer remains available when playback is stopped.

## Translation

Complete English, Czech, and Slovak translations are bundled in `translations/en.yaml`, `translations/cs.yaml`, and `translations/sk.yaml`. Select `language: en`, `language: cs`, or `language: sk` in `config.yaml`, or choose the language under **Options → Display**. The app name **Touch Audio** stays untranslated. Day and month names in the header also come from these YAML files, so their localization does not require OS/Qt locale packages. The displayed date is `weekday | day. month. [month name] year`; for example, `neděle | 25. 10. [říjen] 2026`. The clock is `HH:MM:SS` using the Pi's local time. To create another translation, copy `en.yaml` into `translations/<language>.yaml` and translate the values without changing keys/placeholders. `translations/example.yaml` is a compact override example. Any missing keys fall back to English. Language changes made in Options take effect without restarting (the LAN web page is currently English-only).

## Keyboard and future GPIO joystick

Mouse and touch work immediately. Keyboard arrows navigate focused lists/sliders and advance focus between buttons; Enter selects; F11 toggles fullscreen; Escape exits fullscreen; Space toggles playback; Ctrl+Left / Ctrl+Right change tracks; `[` and `]` change volume.

To simulate GPIO input, send the LAN command actions `nav_up`, `nav_down`, `nav_left`, `nav_right`, and `activate`. They are routed to the currently focused Qt widget as key events. In future you can create a GPIO/SPI/I²C listener and call `MainWindow.navigation_action()` on the GUI thread, or use the authenticated LAN API from a microcontroller. You can also bind a dedicated GPIO adapter to `handle_command` for `next`, `previous`, and `toggle` media actions. The library index, controls, and player do not depend on the input device.

## Troubleshooting / limitations

- VLC requires a proper Pi audio backend/output; first verify ordinary VLC audio works. For USB mounted media, ensure disks are mounted before starting the app; use **Refresh** after mounting new media.
- On an 800×480 screen, panels scroll; 1280×600 is the main target display. Large libraries are searchable via the modal and remote web page.
- Existing metadata tags are indexed by `(file path, size, modified time)`. Tools that change tags without changing either size or modified time will require clearing the SQLite cache once.
- Folder cover images are used, but embedded audio-art extraction is not yet implemented. The UI doesn't currently provide playlists across multiple entries, bookmarks per audiobook chapter, or audio output device selection.
- Search on the touchscreen opens a separate dialog and defaults to **all albums in every category**. Use **Current category** to restrict album results or **Files only** to search individual filenames and tags across the library. The LAN search covers entries and tracks across all categories.
- Automated tests verify indexing, config, and timer logic, but end-to-end playback, fullscreen behavior and poweroff privileges must be tested on actual Raspberry Pi hardware.

## Run tests on a developer machine

```bash
python3 -m pytest -q tests
python3 -m compileall -q .
```

## Larger 7-inch touchscreen interface (1280×600)

The updated layout is designed around **1280×600**: the highlighted **Browse all** button is beside the new Search button, category/entry navigation uses anti-aliased **SVG** icons, and the cover is centered with the folder name and album metadata **below** it. The entry pane starts narrower (roughly 39% instead of 47% of the splitter). The player footer has large, touch-sized transport controls and sliders. The entry-details pane scrolls if a font-scale setting requires more space than the display offers. Small screens simplify the toolbar while keeping the right-aligned timer text visible in the single-line status bar. The Options and Browse dialogs are sized to the active display and can scroll.

The default sizes are approximately **150% of the original**. Configure them separately in `config.yaml` or in **Options → Display**:

```yaml
ui_scale: 1.5        # Buttons, cover, icons, padding, touch targets
text_scale: 1.5      # Font size independently of button/icon scale
browse_text_scale: 1.25 # Multiplier for folder/category/search list text
```

The supported range is `0.75` to `2.0` (75–200%) for each field. Browse/category/search list fonts are multiplied by the normal text size and `browse_text_scale`; row heights scale too. Browse All is approximately 30% wider than before, is nearly full screen-height and has larger scrollbars, scroll-arrow controls and cover thumbnails. Touch dragging scrolls in the same direction as the audio file list, with no inline search list to push the main player down. New versions automatically apply the 150% defaults to older config files that do not have these keys; your music sources, language, and LAN token remain unchanged. New settings apply after pressing **Save**, without restarting playback. If very large scales exceed the available screen, scroll content in the entry details, Browse, or Options panels. For a physical 1280×600 screen it is recommended to use the OS's **100% display scaling**, since Pi OS display-scale settings can also shrink the available logical resolution independently of the app's own settings.

### Desktop shortcut and automatic start at login

The following scripts should be run **as the desktop user, without sudo**, from the project folder:

```bash
chmod +x launch.sh create_desktop_icon.sh autostart.sh scripts/write_desktop_entry.sh
./create_desktop_icon.sh   # Install an app-menu entry plus a shortcut in ~/Desktop
./autostart.sh enable      # Launch Touch Audio after desktop login
./autostart.sh status      # Report whether autostart is enabled
./autostart.sh disable     # Stop launching Touch Audio at future logins
```

`./launch.sh` is the entry point used by both shortcut files. It runs the system Python and writes launcher errors to `~/.local/state/touch_audio_player/launch.log` (or `$XDG_STATE_HOME/touch_audio_player/launch.log`). Shortcuts contain absolute paths, so you can open them from anywhere. If you move the project folder, rerun the icon and `autostart.sh enable` scripts to update those paths.

The startup switch controls **launch after the graphical user's desktop login**, not boot before login. Enable desktop auto-login in Raspberry Pi OS settings if you want the app to appear when you power on the Pi. When the toggle is disabled, the running player is **not** stopped; it only affects subsequent logins. To stop a currently running player, close the window or press Escape to leave full-screen and then close it. Do not run two copies simultaneously (both would attempt to listen on the same LAN port).

In some Raspberry Pi OS desktops a new desktop icon must be marked trusted by right-clicking and choosing **Allow Launching** (the script also tries the `gio` trust flag). These scripts intentionally don't set up a root system service, because Qt requires an active graphical desktop session.

## Browse, repeat, scan and metadata preferences

**Folder sources:** Use `category_folders` (see example above) as a third source form. The Sources tab has a new table where you can add several `category → path` rows, including repeated category names. Existing `group_folders` and `direct_folders` remain compatible.

**Categoryless:** With `categoryless: true`, the category picker disappears. Previous/next album and Browse All traverse the entire library, sorted by folder name, regardless of category. Search always starts in global album mode whether categoryless is on or off.

**Repeat:** Use the separated 🔂 Repeat file and 🔁 Repeat album buttons; tap an active button again to return to normal playback. Repeat file restarts the same track after its natural end. Repeat album advances tracks and starts again from track 1 after the last track. Modes are mutually exclusive and saved between sessions. The LAN interface provides the same controls.

**Metadata:** In **Options → Metadata**, select which lines to display:

```yaml
metadata:
  folder_name: true
  folder_album: true
  folder_artist: true    # author/artist shown below the cover
  file_name: true
  file_title: true
  file_artist: false     # author/artist hidden in individual file rows by default
```

**Scan progress:** A visible progress bar appears at startup and whenever Refresh is clicked. To avoid reading folders at startup, set `scan_on_startup: false`; the last scan's index is loaded from disk, and pressing Refresh updates it. The first manual scan is still needed to create that snapshot. The UI remains available during scans.

**Browse loading:** The modal opens before thumbnails are populated; a busy indicator shows while rows are added in small batches. This helps retain a responsive UI on a Pi 4B with large collections. File, Browse, Search and Category lists use touch-style pixel scrolling and large scrollbars.

## Status line, system controls, brightness and auto-dim

The **bottom status row** now remains on *one line*: library size / scanning information is aligned left, and the sleep-timer countdown is aligned right. The refresh progress bar sits between the two. Longer scanning messages are clipped in the limited space instead of wrapping the footer and moving the player controls.

A **dim-sun icon** at the left of the top bar toggles between **40%** and the previously selected brightness, but only if the previous level was above 40%. A **power/system icon** at the right opens a touchscreen-friendly dialog containing a brightness slider, **Close application**, and a distinctly separated **Shut down computer** action. Local shutdown asks for explicit confirmation. The close action exits only Touch Audio; shutdown powers down the entire Pi. A separate web shutdown button also asks for confirmation, and the API requires `"confirm": true`.

**Options → Display** exposes automatic dimming after idle time (enabled by default; **60 seconds**, **40%** target), with smooth ~1.5-second dim and quick wake-up when interacting with the touchscreen or mouse or keyboard. It restores the selected normal brightness, and it never *increases* brightness to reach a dimming target. The manual toggle dims to 40%, independently of the configurable *automatic* target. An inactivity timer only tracks actions inside the app, not activity in other programs. Any physical touch/mouse/keyboard input inside Touch Audio resets it. Web commands can also change the requested normal brightness or toggle dimming. Closing the app restores the normal hardware brightness.

Configuration defaults (missing keys automatically get these values; no need to overwrite existing config):

```yaml
display:
  auto_dim: true
  idle_seconds: 60
  dim_percent: 40
  backend: auto       # auto | hardware | software
  device: ''          # Empty = auto-detect; optional name in /sys/class/backlight
```

### Raspberry Pi OS / Debian 13 (Trixie) hardware brightness

The application checks Linux **`/sys/class/backlight`** and uses a *writable* backlight device if present. This works across Linux distributions and does not depend on X11 or Wayland. Official Raspberry Pi DSI touchscreens have a controllable backlight. Third-party **HDMI** touchscreen panels often **do not** expose a kernel backlight; for these the app automatically falls back to a **software dimmer inside the Touch Audio window**. That fallback is input-transparent and restores immediately when the window receives activity, but **does not physically dim the backlight or save its power**, and it cannot dim other apps or desktop dialogs. The system dialog identifies the active backend. `backend: software` forces the non-hardware method even when hardware is available; `backend: hardware` requests hardware but safely falls back if it is not accessible. The application **does not use sudo**, and does not run hardware shell commands on each animation step.

To diagnose the screen, run **without sudo**:

```bash
./check_brightness.sh
ls /sys/class/backlight/
```

On Trixie, if a backlight exists but is not writable, install Debian's permission-management package, confirm the desktop user belongs to the `video` group, then log out/reboot to apply group/udev changes:

```bash
sudo apt update
sudo apt install brightnessctl brightness-udev
id -nG
sudo usermod -aG video "$USER"    # only if 'video' is missing in id -nG
sudo reboot
```

After reboot, check `./check_brightness.sh` again. Some hardware drivers need special vendor support; not all 1280×600 HDMI panels provide generic backlight control. For HDMI DDC/CI monitors, `ddcutil` may work, but this release intentionally **does not** call it on every fade step because the protocol can be very slow, and not all displays support DDC/CI. This avoids interface stalls and excess subprocess activity. Use your display vendor's documented driver if hardware brightness is needed on a custom touch panel.

### Remote API examples

```bash
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"dim"}' "$BASE/api/control"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"brightness","value":75}' "$BASE/api/control"
# This powers down the WHOLE computer immediately:
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"shutdown","confirm":true}' "$BASE/api/control"
```
