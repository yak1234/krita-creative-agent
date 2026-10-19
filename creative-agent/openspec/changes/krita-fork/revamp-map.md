# Krita-Revamp: what to port, by area

Source: github.com/10zindraws/Krita-Revamp, branch `revamp-5.2.14`, cloned 19 October 2026. Revamp's own work starts at
`e76a4e1` ("Revamp's first changes", 11 January 2026) on top of KDE's krita/5.2 at `31056c6` (9 December 2025).
116 commits by its authors; 66 change code (the rest are README and changelog edits). Licence GPL-3.0, like ours.

Port order (design.md, decision 3) is by value to a Photoshop user; this map says where each feature lives. C++ areas need
porting to master and Qt6 by hand; Python plugins go through `krita-mcp/scripts/qt6_scoped_enums.py` first.

## libs/ui (16 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `b908ad5` 2026-01-11 Persistent brush tweaks and UI fix
- `b488c88` 2026-01-13 Custom Splash
- `26851a8` 2026-01-14 Stroke preview thumbnail implementation
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `a9698ce` 2026-01-20 Refined stroke preview implementation
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker
- `f754aab` 2026-01-28 Draft of Clipping Mask view mode
- `02fbd9b` 2026-01-28 Fix Add Paint Layer go above invisible group layer Clipping Mask
- `63c5384` 2026-01-29 Fix double-click brush preset to open Brush Editor feature
- `9f4fd35` 2026-01-29 Disable startup warning "Only your local resources are available"
- `5980796` 2026-01-30 HiDPi Correct font size refresh on startup
- `cdfda4a` 2026-02-01 Fix currently selected template's thumbnail being grey
- `5c7979c` 2026-02-04 Add hide Tabsbar option for Canvas-Only Mode
- `c085489` 2026-02-06 Merge Brush Tag Selector to Brush Presets docker
- `b2b3727` 2026-02-16 Fix docker sizes not persisting across Windows reboots

## libs/ui/widgets (14 commits)
- `b908ad5` 2026-01-11 Persistent brush tweaks and UI fix
- `26851a8` 2026-01-14 Stroke preview thumbnail implementation
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `a9698ce` 2026-01-20 Refined stroke preview implementation
- `c202fef` 2026-01-23 Fix accurate display with separate brush and eraser
- `0e34dcb` 2026-01-23 Allow palette docker to be resized smaller
- `2971f6c` 2026-01-23 Adjust brush stroke previews aspect ratio for readable long names
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker
- `4df68b9` 2026-01-24 Double-click active brush preset to open Brush Editor
- `e3cd494` 2026-01-26 Re-adjust stroke preview aspect ratio
- `d4e21ad` 2026-01-27 Brush Presets QoLs
- `ec4b087` 2026-02-06 Fix stroke preview thumbnails when using Ctrl+Scroll
- `c085489` 2026-02-06 Merge Brush Tag Selector to Brush Presets docker
- `697c81b` 2026-02-16 Improve button sizing and clean UI brush tag selector

## libs/resourcewidgets (10 commits)
- `8918b4f` 2026-01-20 Draggable Reordering Brush Presets
- `f4a43d8` 2026-01-22 Fix drag reordering mismatch caused by new brushes
- `6cd3e8a` 2026-01-22 Fix crash when dragging a non-selected brush preset
- `f43dd17` 2026-01-23 Remove "All Untagged" tag
- `9a812ee` 2026-01-23 Clean up Brush Presets docker
- `8399c1b` 2026-01-23 Fix unappearing dialog when right-clicking Brush Preset
- `66f7d2b` 2026-01-23 Remove ★ My Favorites tag from Brush Presets docker
- `4df68b9` 2026-01-24 Double-click active brush preset to open Brush Editor
- `63c5384` 2026-01-29 Fix double-click brush preset to open Brush Editor feature
- `c085489` 2026-02-06 Merge Brush Tag Selector to Brush Presets docker

## libs/resources (9 commits)
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `8918b4f` 2026-01-20 Draggable Reordering Brush Presets
- `0328adc` 2026-01-20 Fix for persistent brush reordering across startups
- `f4a43d8` 2026-01-22 Fix drag reordering mismatch caused by new brushes
- `1f0e361` 2026-01-22 Fix brush preset names not updating in Details/Strokes view
- `f43dd17` 2026-01-23 Remove "All Untagged" tag
- `66f7d2b` 2026-01-23 Remove ★ My Favorites tag from Brush Presets docker
- `a0bcc32` 2026-01-24 Auto Manage Broken Bundles
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/dockers/brushhud (8 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker
- `2c28f7a` 2026-01-23 Switch Brush Editor docker to Tool options automatically
- `607d363` 2026-01-23 Fix conflict with tool invocation from canvas input
- `9bbda0f` 2026-01-23 Add Brush Smoothing dropdown to the On-Canvas Brush Editor docker
- `a951809` 2026-01-23 Add Smoothing dropdown options
- `516120d` 2026-01-23 Fix appearance of Smoothing dropdown options
- `a8ea481` 2026-01-24 Rename On-Canvas Brush Editor docker to Tool Options
- `9eb8977` 2026-01-24 Rename On-Canvas Brush Editor docker to Sub Tool Options

## plugins/dockers/layerdocker (8 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `c94e713` 2026-01-22 Let Layers Docker be resized to a small width
- `3b598ec` 2026-01-27 Alpha Inheritance Indentation
- `f754aab` 2026-01-28 Draft of Clipping Mask view mode
- `bd64c4e` 2026-01-28 Fix proper hiding of invisible groups for Clipping Mask view mode
- `bb9cc08` 2026-01-31 Alt + Left-click isolated layer sketchbook feature
- `48ba22a` 2026-02-06 Add layer property toggle to Layers docker toolbar
- `697c81b` 2026-02-16 Improve button sizing and clean UI brush tag selector

## libs/ui/dialogs (5 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `b908ad5` 2026-01-11 Persistent brush tweaks and UI fix
- `b488c88` 2026-01-13 Custom Splash
- `f754aab` 2026-01-28 Draft of Clipping Mask view mode
- `5c7979c` 2026-02-04 Add hide Tabsbar option for Canvas-Only Mode

## libs/ui/forms (5 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `b908ad5` 2026-01-11 Persistent brush tweaks and UI fix
- `b488c88` 2026-01-13 Custom Splash
- `f754aab` 2026-01-28 Draft of Clipping Mask view mode
- `5c7979c` 2026-02-04 Add hide Tabsbar option for Canvas-Only Mode

## plugins/python/layer_kit (5 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `56bba6d` 2026-01-22 Add option to hide minimal shade selector in wide gamut docker
- `d37ca47` 2026-01-22 Add option to hide minimal shade selector in wide gamut docker
- `48ba22a` 2026-02-06 Add layer property toggle to Layers docker toolbar
- `697c81b` 2026-02-16 Improve button sizing and clean UI brush tag selector

## .github (4 commits)
- `7b8d848` 2026-01-11 Kofi
- `7aff1f0` 2026-01-11 FUNDING.yml
- `c9d6a63` 2026-01-11 Update FUNDING.yml
- `be528ee` 2026-01-14 Update FUNDING.yml

## plugins/python/CMakeLists.txt (4 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `31f6a81` 2026-01-25 Improve startup speed
- `772f137` 2026-01-25 Remove more dockers for faster startup
- `4cfed7c` 2026-02-08 Remove unused plugins

## plugins/python/label_box (4 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `b908ad5` 2026-01-11 Persistent brush tweaks and UI fix
- `aa83c54` 2026-02-16 Remove label_box plugin
- `c8909f1` 2026-05-13 Revert "Remove label_box plugin"

## libs/widgetutils (3 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `63c5384` 2026-01-29 Fix double-click brush preset to open Brush Editor feature

## plugins/dockers/presetdocker (3 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker
- `4df68b9` 2026-01-24 Double-click active brush preset to open Brush Editor
- `63c5384` 2026-01-29 Fix double-click brush preset to open Brush Editor feature

## plugins/dockers/widegamutcolorselector (3 commits)
- `ea8080c` 2026-01-22 Fix delayed Wide-Gamut popup color selector
- `56bba6d` 2026-01-22 Add option to hide minimal shade selector in wide gamut docker
- `d37ca47` 2026-01-22 Add option to hide minimal shade selector in wide gamut docker

## plugins/python/krita_ui_tweaks (3 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `5c7979c` 2026-02-04 Add hide Tabsbar option for Canvas-Only Mode

## plugins/python/preset_groups (3 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/python/separatebrusheraser (3 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `d4e21ad` 2026-01-27 Brush Presets QoLs
- `db7ebf2` 2026-01-27 Fix tag switching for Eraser and Brush mode

## FUNDING.yml (2 commits)
- `5e02a26` 2026-01-11 Create FUNDING.yml
- `7b8d848` 2026-01-11 Kofi

## libs/image (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `4a1167c` 2026-01-23 Add Smoothing Slider to the On-Canvas Brush Editor docker

## libs/ui/input (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `607d363` 2026-01-23 Fix conflict with tool invocation from canvas input

## libs/ui/tool (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `c202fef` 2026-01-23 Fix accurate display with separate brush and eraser

## plugins/python/dockerundercursor (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/python/krita_redesign (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes

## plugins/python/super_docker_lock (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `ef8a615` 2026-02-11 Fix hidden buttons for Animation dockers

## plugins/python/vision_tools (2 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
- `0fb837b` 2026-01-11 Delete vision_tools extension.py

## po (2 commits)
- `a8ea481` 2026-01-24 Rename On-Canvas Brush Editor docker to Tool Options
- `9eb8977` 2026-01-24 Rename On-Canvas Brush Editor docker to Sub Tool Options

## CHANGELOG.md (1 commits)
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes

## cmake (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## krita (1 commits)
- `681ef9f` 2026-01-14 v1.1.0 and Bug Fixes

## libs/brush (1 commits)
- `f142e6d` 2026-01-21 Fix ARGB32 format bug

## libs/flake (1 commits)
- `607d363` 2026-01-23 Fix conflict with tool invocation from canvas input

## libs/global (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## libs/pigment (1 commits)
- `c54b79a` 2026-01-21 Add Marker blend mode

## libs/ui/canvas (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## libs/ui/tests (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## libs/widgets (1 commits)
- `0e34dcb` 2026-01-23 Allow palette docker to be resized smaller

## pics (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## plugins/dockers/CMakeLists.txt (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/arrangedocker (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/channeldocker (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/digitalmixer (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/griddocker (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/histogram (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/overview (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/palettedocker (1 commits)
- `0e34dcb` 2026-01-23 Allow palette docker to be resized smaller

## plugins/dockers/patterndocker (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/dockers/recorder (1 commits)
- `870ff51` 2026-01-23 Add On-Canvas Brush Editor HUD docker

## plugins/paintops/colorsmudge (1 commits)
- `26851a8` 2026-01-14 Stroke preview thumbnail implementation

## plugins/paintops/libpaintop (1 commits)
- `4a1167c` 2026-01-23 Add Smoothing Slider to the On-Canvas Brush Editor docker

## plugins/python/krita_work_timer (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## plugins/python/lastdocumentsdocker (1 commits)
- `772f137` 2026-01-25 Remove more dockers for faster startup

## plugins/python/mixer_slider_docker (1 commits)
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/python/photobash_images (1 commits)
- `772f137` 2026-01-25 Remove more dockers for faster startup

## plugins/python/quick_brush_size (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## plugins/python/quick_settings_docker (1 commits)
- `f7fe08e` 2026-02-09 remove unnecessary plugins

## plugins/python/quickexportdocker (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## plugins/python/selectionsbagdocker (1 commits)
- `f7fe08e` 2026-02-09 remove unnecessary plugins

## plugins/python/tenbrushes (1 commits)
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/python/tenscripts (1 commits)
- `31f6a81` 2026-01-25 Improve startup speed

## plugins/python/timer_watch (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes

## plugins/tools/basictools (1 commits)
- `e76a4e1` 2026-01-11 Revamp's first changes
