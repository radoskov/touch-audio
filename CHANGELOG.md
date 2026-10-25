# Changelog

## v1.4.2 — translated dates and clearer repeat controls

- Date header now shows literal square brackets around the localized month name.
- Bundled complete Czech (`cs`) and Slovak (`sk`) UI translations, including all weekday and month names; retained "Touch Audio" as the app name.
- Repeat-file and repeat-album controls use an unmistakable green active state, neutral inactive state and synced pressed-state tooltips for UI and LAN actions; tapping the active mode turns it off.
- Added validation for translation completeness, placeholders, date formatting and repeat control styling.


## v1.4.1 — modal-dialog backdrop

- All player modal dialogs and message boxes now subtly shade the inactive main window (approximately 33% black).
- The new modal shade does not change actual screen brightness, works with hardware and software dimming, and adds no polling or animation.
- Centralized modal execution keeps the backdrop visible for nested confirmations and reliably clears it when a dialog closes.
- Nested confirmations use the currently active modal as their parent for correct stacking.
- Added regression tests for dialog routing, overlay independence, and an optional offscreen Qt smoke test.

## v1.4 — System stability, touchscreen settings, clock and YAML comments

- Fixed a fatal Qt method-name collision in the system dialog (`window()` vs `window` attribute); hardened global activity filter against destroyed widgets.
- Increased Options dialog size and text; added large icon-based minus/plus controls to every numeric setting.
- Added a separate large-font date/time header row, localized with the UI language.
- Implemented round-trip YAML configuration saving using ruamel.yaml, preserving comments and quoting; refuses comment-destructive fallback.
- Installed an Applications menu launcher as well as the desktop shortcut, with best-effort desktop trust handling.
- Extended regression tests for configuration comments, UI structure, desktop shortcuts and numeric steppers.

# Changelog

## v1.2 — collection and touchscreen refinements

- Third YAML source form `category_folders`, supporting single/multiple custom paths per category.
- Narrower entry pane, centered cover with folder/album/artist labels underneath.
- Browse All 30% wider, nearly full-height, thumb images and fonts enlarged; separate
  browse_text_scale; larger scrollbar, arrow buttons, unified touch drag-scrolling.
- New large category picker with category icons and detailed counts.
- Standalone global search (all albums by default; category-only or files-only modes).
- Repeat-file/repeat-album playback modes, saved state, and LAN remote controls.
- Metadata visibility preferences (file artist hidden by default).
- Categoryless browse and entry navigation.
- Scan progress, optional skip-on-startup with persisted last-successful library index,
  and incremental Browse/Search loading with visible busy indicator.
- Backwards-compatible v1.1 config, login/autostart scripts unchanged.

## v1.1 — 7-inch touchscreen update

- Default 150% independent UI/text scaling (`ui_scale` and `text_scale`),
  adjustable in Options → Display, applied without interrupting playback.
- Responsive main-window layout designed for 1280×600, with the album cover
  next to its metadata, touch-sized buttons and a prominent Browse all button.
- Sharp SVG navigation and playback icons instead of font-dependent arrows.
- Scaled browse/options dialogs with scrollable content, adjustable list-row
  heights, larger seek/volume slider handles and narrow-screen toolbar/transport.
- Desktop launcher (`create_desktop_icon.sh`) and graphical-session login
  autostart manager (`autostart.sh enable|disable|status`).
- Launcher logs in the user's XDG state directory.
- The update archive does not overwrite existing `config.yaml`.

## v1.0 — initial release

Touchscreen library browser, tag scanning and cache, VLC playback, LAN web
controller, translation files and 30-second shutdown fade timer.

## 1.3 (Raspberry Pi OS / Trixie)

- Reworked bottom status into a single non-wrapping row with left library status, centered scan progress and right timer.
- Added system dialog with app exit, brightness slider and separated, confirmed full-computer shutdown.
- Added first-position dim-sun toolbar toggle (40% ↔ previous normal brightness, when previous is above 40%).
- Added idle auto-dim (60-second inactivity, 40% target by default) with smooth easing and input wake-up; backend auto-detects writable Linux sysfs backlight with visual-only fallback.
- Added remote brightness, dim toggle and explicitly confirmed poweroff; added backlight diagnostic script.
- Reduced unnecessary active/idle GUI polling and web requests, cached artwork/category summaries, debounced brightness slider changes, avoided unnecessary state file rewrites and scans on display-only Options changes.
- Made poweroff asynchronous to keep Qt responsive and corrected late sleep-timer wakeups to maintain the intended fade deadline.
