# Discord Overlay: what the program does

A reference for an AI (or a new developer) that needs to reason about this codebase
without reading all of it. It describes behaviour and responsibilities, module by module.
Names in backticks are real identifiers in the repository.

## One-paragraph summary

Discord Overlay is a Windows desktop combat parser for Monsters & Memories. It reads
only the pixels of a screen region the user draws around the game's combat chat. Every
scan it captures that region, runs OCR on it, works out which chat lines are new since
the previous scan, turns each new line into a structured combat event (who hit whom for
how much), and feeds those events into an encounter tracker that produces DPS, HPS, and
per-combatant totals shown in the main window and in an always-on-top mini meter. The
same OCR text also drives user-defined triggers that play sounds, speak text, and start
countdown timers shown in overlay windows. Nothing touches the game process: no memory
reading, no log files, no input injection. Settings live in `%LOCALAPPDATA%\DiscordOverlay`.

## Data flow

```
ScreenCapture.grab(region)            mss screenshot of the chosen rectangle
  -> CombatOCREngine.recognize(frame)  RapidOCR (ONNX Runtime, GPU if available) -> OCRLine[]
  -> ScrollingTextDeduplicator         which lines are newly appended since last scan
  -> CombatTextParser.parse(text)      repair OCR noise, apply grammar -> CombatEvent | None
  -> LineRepairer (optional)           rebuild lines the cursor damaged, from grammar templates
  -> TriggerEngine.process(text)       user triggers -> TriggerMatch (sound, speech, timer)
  -> queue -> App (Tk thread)          EncounterTracker.add(event), tables, overlays, timers
```

The scanner runs on a background thread (`ScannerWorker`) and communicates with the UI
only through a queue of `(kind, value)` tuples: `status`, `engine`, `preview`, `ocr`,
`event`, `trigger`, `pet`, `error`, `stopped`.

## Core modules (`discord_overlay/`)

### `models.py` — shared data types
- `EventKind`: `DAMAGE_OUT` (the player or their pet dealt it), `DAMAGE_IN` (the player
  or their pet took it), `DAMAGE_OTHER` (between third parties), `HEAL`, `MISS`.
- `CombatEvent`: one parsed line: timestamp, kind, actor, target, amount, absorbed, action
  (verb or ability name), critical flag, raw OCR text, OCR confidence, `is_pet`,
  `is_damage_shield`, `repaired`.
- `OCRLine`: text, confidence, vertical position. `Region`: a screen rectangle with a
  minimum size. `EncounterSnapshot`: headline numbers for the UI.

### `capture.py` — screenshots
`ScreenCapture.grab(region)` returns a BGR frame for a rectangle in physical desktop
pixels, on any monitor. Helpers list monitor rectangles and find the monitor containing a point.

### `ocr_engine.py` — text recognition
`CombatOCREngine` wraps RapidOCR. It picks a GPU provider when available (CUDA or
DirectML, otherwise CPU), preprocesses the frame, segments it into text rows, recognises
each row, drops results under the confidence floor, and returns `OCRLine`s ordered top to
bottom. `text_signature(frame)` is a cheap fingerprint the scanner uses to skip OCR when
the region has not changed. A debug option can dump every preprocessed frame.

### `dedup.py` — finding new lines
`ScrollingTextDeduplicator.new_lines(current)` compares the current viewport with the
previous one. It finds the overlap (the rows at the top of the new viewport that repeat
the bottom of the old one, tolerating OCR jitter), and returns only the rows below it.
Repeated identical lines are handled by counting: a line entering at the bottom while an
identical one scrolls off the top is still new. The first viewport after start is only a
baseline and is never counted. This is what stops the same chat line being counted on
every scan.

### `parser.py` — one line to one event
`CombatTextParser(player_name, pet_names).parse(text, confidence)`:
1. Normalises quotes and accents, then repairs OCR damage the game never produces:
   glued words (`Youcrush`, `hitsia rattlesnake`, `SliceIhits`), apostrophes read as
   `l`/`I`/`1` (`Playerls Slice VI`), misread pronouns (`Yowr`), `for-407`, misread verbs
   snapped onto the known verb list (`erushes` -> `crushes`).
2. Drops lines that carry two amounts (two chat rows fused by a mid-scroll capture) and
   environmental damage (falling, drowning).
3. Applies the grammar. Damage: `<actor> <verb> <target> for N points of [school] damage
   [(N absorbed)] [(Critical)]`, tolerant of clipped line ends, mangled `points of`,
   and mangled `damage`. Possessive abilities: `Name's Ability hits target`. Pets:
   `Your pet Name ...`, `<creature>'s pet ...`, and `<creature>'s pet's Ability`. Damage
   shields. Disease spreading (`X spreads their Plague to Y. Y takes N ...`, credited to
   the disease, not the carrier). Passive `Y takes N points`. Heals in several wordings,
   including `heals them` (self-heal) and ability names containing "Heal". Misses.
4. Decides ownership: `You`/`Your`/the configured character name and its pets are the
   player; `YOU`/`your pet` as target means incoming; anything else is third party.
   Unknown verbs before a clear target still parse. `(Crippling Blow)` counts as critical.
5. Names that cannot be read (empty, article only, a single letter, fragments of
   `offhand`) become `Unknown` rather than a combatant. Pet names are learned from
   `Your pet <Name>` lines and announced so earlier lines can be re-attributed.

`closest_combat_verb`, `split_possessive`, `repair_ocr_spacing`, `is_fused_line` are the
reusable pieces.

### `repair.py` — cursor-occlusion repair
`LineRepairer` learns templates from lines that parsed cleanly (numbers masked with `#`,
names with `@`) and aligns a damaged line against them token by token. It restores
hidden words but never invents numbers, never changes a clean known word, allows at most
two token edits, and rejects ambiguous matches. A seed dictionary ships in
`assets/grammar-templates.txt`; learned templates persist per character.

### `names.py` — are two spellings the same combatant?
- `ocr_confusable(a, b)`: true only when every difference is a known OCR character swap
  (`c/e`, `l/i/1`, `rn/m`, dropped apostrophe, doubled letter read once, ...). A real
  one-letter difference such as `Konaner`/`Lonaner` is not confusable.
- `clipped_head`, `glued_article`: a name missing its first letters, or with `a` glued on.
- `merge_similar_names(names, protected)`: maps each spelling seen in a fight onto the
  most common spelling it is a misread of. Only rare spellings merge (a misread is
  occasional, a second player is not); the player's own name and configured pets are
  protected; a two-letter name that merges into nothing is `Unknown`.
- `known_npcs()` loads `assets/npc-names.txt` (community wiki + mnmdrops.com, ~1,700
  names). `snap_to_known_npc` lets a rare misread take the shipped spelling even if the
  correct spelling was never read that fight. The list is a hint for spelling only; it
  never decides whether something is a player or a mob.

### `encounter.py` — totals
`EncounterTracker.add(event)` groups events into encounters separated by a timeout of
silence (default 8 s). `snapshot()` gives duration, total damage out/in, healing, DPS,
10-second rolling DPS, HPS, hits, crits, misses. `actor_totals(target=None)` gives one
row per combatant (`ActorRow`): damage, share, DPS, rolling DPS, hits, crits, healing,
HPS. Rows are keyed by merged name; a creature that hit you and your group is one row.
Row type is derived per fight: `PLAYER`, `PET`, `DAMAGE SHIELD`, `ENEMY` (dealt damage to
you this fight), else `OTHER`. Shares are measured within the enemy side or the friendly
side. Pet damage merges into the player's row when configured; damage shields are one
row or credited to the wearer. `mark_pet(name)` re-attributes earlier lines once a pet
is learned. "Running totals" keep events across fights while excluding idle time.
`export_csv(path, "combatants"|"log")` writes UTF-8 CSV; every row carries the app version.

### `actor_filter.py` — group filter
`actor_event_allowed(event, ...)`: with the filter on, an event counts only if one side
is the player, their pet, or a listed name, so strangers fighting nearby are excluded.

### `triggers.py`, `timers.py`, `trigger_packs.py` — alerts
- `Trigger`: name, folder, profile, conditions (Contains / Exact / Regex, with NOT and
  ALL/ANY logic, a multi-line window), sound, volume, cooldown, speech texts, overlay and
  timer settings, retrigger behaviour (restart / replace / ignore / create another),
  early-end patterns. GINA-style regex (`(?<target>...)`, `{S1}`, `{N}`) is normalised.
- `TriggerEngine.process(text, source)` evaluates every enabled trigger against each new
  OCR line and yields `TriggerMatch`es with captured variables. It can also produce a
  `TriggerDiagnostic` explaining why a trigger did or did not fire (used by the replay tester).
- `TimerManager` runs countdowns (`TimerInstance`) keyed per trigger or per captured key,
  emits `TimerNotification`s for start, ending soon, expiry, and early end.
  `render_template` fills `{target}`-style variables.
- Trigger packs are JSON exports/imports of triggers for sharing.

### `audio.py`, `speech.py`
`SoundPlayer` plays bundled or user WAV/OGG/MP3 through pygame with per-trigger volume;
`ensure_default_sounds` writes the five bundled tones. `SpeechPlayer` speaks through
Windows text-to-speech (PowerShell System.Speech) with voice, rate, volume, and a queue
or interrupt mode.

### `scanner.py` — the loop
`ScannerWorker.run()`: load the OCR engine, build one capture source for the combat
region plus one per trigger with its own region, then loop at `scan_interval`. For each
source: grab, skip OCR if the signature is unchanged (but never for longer than a
second), recognise, dedupe, parse, repair, evaluate triggers, post results. It also
learns pet names from every visible line and posts them. Templates are saved
periodically. Errors are posted to the UI rather than crashing the thread.

### `problem_frames.py` — diagnostics for unreadable lines
When the Settings toggle is on and a fight is in progress, a frame whose OCR produced a
numbered line that did not parse, a fused line, or an unreadable actor/target is saved
as PNG plus a text report of every line read from it, under `diagnostics\problem-frames`.
Rate-limited to one per half second and capped at 300 per session. This is how to tell
a capture problem (overlap, ghosting from driver frame generation, moved window) from a
parser gap.

### `config.py`, `paths.py`
`Settings` is the persisted state (`config\settings.json`): scan interval, fight timeout,
rolling window, OCR confidence floor, GPU preference, pet handling, damage-shield
handling, running totals, group filter, mini meter layout, overlay close gesture,
speech settings, triggers, timer boards, and per-character profiles (`CharacterProfile`
keeps region, timer boards, active trigger profile, which triggers are on, group
filter, pet names, mini meter geometry). Values are clamped and validated on load.
`paths.py` resolves the app data folders and creates them.

### `performance.py`, `backend.py`
The hardware setup wizard benchmarks capture and OCR on a representative frame,
picks a profile (scan interval and GPU/CPU), and records provider details.
`backend.py` detects the GPU vendor to choose the ONNX Runtime package.

### `shortcuts.py`, `diagnostics.py`, `app.py`
Start Menu / desktop shortcut creation and self-repair after the folder moves (frozen
builds only). A rotating crash log with process and thread exception hooks. `app.main()`
wires it up and starts the Tk application.

## User interface (`discord_overlay/ui/`)

- `main_window.py` `App`: header status pill; sidebar with character menu, Start/Stop
  monitoring, Select region, mini meter toggle, Move/Lock overlays, running totals,
  Reset, CSV export, metric cards, and a DPS sparkline. Tabs: Combatants (bars or table,
  damage or healing, scoped to one target), Alerts & Timers, Log (raw OCR text and
  confidence), Settings, OCR Tips. Polls the scanner queue, feeds the tracker, refreshes
  views, shows the hardware wizard on first run and the accuracy tips popup on every
  launch, offers a Start Menu shortcut once.
- `settings_tab.py`: scan settings, options (pets, damage shields, GPU, cursor repair,
  problem frames), timer boards, hardware setup, About, diagnostics folder, shortcuts.
- `alerts_tab.py`, `trigger_editor.py`: trigger library with folders and profiles,
  per-character on/off, editor for every trigger field, replay tester, pack import/export.
- `region_selector.py`: darkens every monitor; drag to select; the last region is offered
  as a gold rectangle to reuse.
- `overlay.py`, `overlays.py`, `mini_overlay.py`: always-on-top windows for timers
  (docked boards or one window per timer) and the mini meter (four configurable header
  stats plus top actor bars); click-through when locked; a modifier-click dismisses a timer.
- `dialogs.py`: accuracy reminder, About, group filter editor, speech settings, regex
  help, trigger replay. `tips.py`: the tip list shared by the popup and the tab.
- `widgets.py`, `theme.py`: metric cards, status pill, sparkline, meter bars, sortable
  tree with draggable columns; dark theme, fonts, icon.

## Developer tooling

- `tests/`: unit tests per module plus `tests/corpus/` — about 13,500 distinct real OCR
  lines from contributed logs with the parse each must produce. `scripts/build_corpus.py`
  adds logs, regenerates expectations after an intentional parser change, and diffs.
- `scripts/compare_logs.py`: compares two exported logs of the same recording.
- `scripts/build_npc_names.py`: refreshes the NPC list (also run before every release build).
- `scripts/build_grammar_seed.py`: regenerates the shipped repair templates.
- `scripts/ui_smoke.py`: drives the real window through its features.
- `scripts/build_windows.ps1`, `packaging/DiscordOverlay.spec`: PyInstaller folder build.
- `.github/workflows/`: `ci.yml` runs the tests; `release.yml` on a `v*` tag compiles a
  fresh PyInstaller bootloader, refreshes NPC names, builds the DirectML variant, scans it
  with Defender, zips it, and publishes a GitHub Release. Releases are zip only.

## Invariants worth knowing

- Numbers are never guessed: a repaired line keeps its OCR amounts; a fused line is dropped.
- The parser is deliberately loose: a line with an amount but an unknown verb still counts.
- Roles are per fight, never remembered: a friendly player who attacks you is red for
  that fight only. PvP needs no special handling.
- Player names are 3 to 15 letters; nothing in the game is one or two letters long.
- Every change to the parser must leave the corpus test green or be accompanied by a
  reviewed regeneration of `tests/corpus/expected.tsv`.
