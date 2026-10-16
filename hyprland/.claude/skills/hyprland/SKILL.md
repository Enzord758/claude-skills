---
name: hyprland
description: Use when changing or debugging this user's Hyprland desktop — keybinds/shortcuts, window rules (float, size, position, workspace/monitor pinning, fullscreen games, "the bar sits on top of my game"), monitors/HDR/VRR, workspaces and layouts, animations, gaps/borders/blur, autostart and env vars, or wiring a new app/TUI into Hyprland via a .desktop launcher + icon. The config is hyprland.lua using Hyprland 0.55+'s hl.* Lua API — NOT stock hyprland.conf syntax — with DankMaterialShell (DMS) generating some sub-files. Use it even when the user doesn't say "Hyprland", e.g. "lav en genvej til…", "super+X skal åbne…", "det vindue skal floate", "flyt discord til den anden skærm", "åbn X på workspace 3", "reglen virker ikke" — because examples from the internet are hyprland.conf syntax that often loads without error yet does nothing here, and this session often runs as root, where plain `hyprctl` can't reach the desktop (Hyprland runs as the user, not root).
---

# Hyprland config (this machine)

Hyprland 0.56 on CachyOS, NVIDIA, two monitors (Dell 4K HDR main `monMain`, Samsung `monLeft` left of it — matched by `desc:`, never by port name; currently DP-2 / HDMI-A-1), DMS as bar/shell, launched via uwsm (`wayland-wm@hyprland.desktop.service`). Human user `enzord` (UID 1000, home `/home/enzord` — capital E).

## Where things live

- Config: `/home/enzord/.config/hypr/hyprland.lua`. `~/.config/hypr` is a **stow directory symlink** → `~/dotfiles/hypr/.config/hypr/`, so there is only one file; editing either path is the same edit.
- Because the symlink is on the *directory*, not per file, anything created under `~/.config/hypr/` — new files and new subdirectories alike — physically lands in `~/dotfiles/hypr/.config/hypr/` and works at once; no `stow` re-run. The flip side: it's a new **untracked** file in the repo, so name it when reporting what's uncommitted (a plain `git diff` won't show it).
- Helper scripts called from binds/autostart live in `~/.config/hypr/scripts/` (e.g. `scripts/volume.sh up|down`), executable, and are referenced by absolute path: `hl.dsp.exec_cmd("/home/enzord/.config/hypr/scripts/volume.sh up")`. Put new ones there rather than in `~/.local/bin`, so they travel with the dotfiles.
- `~/dotfiles` is a git repo. Committing/pushing is the user's call — mention the change is uncommitted rather than committing it.
- Desktop launchers: `/home/enzord/.local/share/applications/*.desktop`; icons: `/home/enzord/.local/share/icons/hicolor/<size|scalable>/apps/`.
- Write paths out in full (`/home/enzord/...`): when this session is root, `~` is `/root`.

## Talking to the live session

Sessions here run either as root or as enzord. `hyprctl` can only reach a Hyprland instance started by the same user, and Hyprland is almost always started by enzord (via uwsm) — so as root, plain `hyprctl` fails ("HYPRLAND_INSTANCE_SIGNATURE not set"); only in the rare case that root itself started Hyprland would it work. As root, every file you write also becomes root-owned inside the user's dotfiles. The bundled script works the same either way, so use it rather than reasoning about which case you're in:

- `bash /home/enzord/.claude/skills/hyprland/scripts/hypr-check.sh` — verify the config, show live config errors, flag files not owned by enzord
- `… hypr-check.sh clients` — open windows with class, title, and the *initial* class/title when they differ (what rules matched when the window opened) — the source of truth for match strings
- `… hypr-check.sh binds` — every active bind as `SUPER+SHIFT + key [flags]`; raw `hyprctl binds` only shows `dispatcher: __lua`, which says nothing about what a bind does
- `… hypr-check.sh -- <hyprctl args>` — any hyprctl command, e.g. `-- getoption general:gaps_in`, `-- reload config-only`

If the ownership check flags a file you created or edited, run `chown enzord:enzord <file>` (only possible, and only needed, when root).

## This is Lua, not `hyprland.conf`

Hyprland 0.55+ Lua API (`hl.bind`, `hl.window_rule`, `hl.config`, `hl.dsp.*`…), not `bind = SUPER, RETURN, exec, kitty`. Almost everything online is still `.conf` syntax — translate it, never paste it. A pasted `.conf` line is worse than a syntax error: `bind = SUPER, F12, exec, kitty` is *valid Lua* (it assigns nil to a global called `bind`), so it passes verification and silently does nothing.

Where to look, in order:

1. `reference.md` (this skill dir) — the subset this config already uses, in its house style, plus the traps found so far. Match it.
2. `/usr/share/hypr/stubs/hl.meta.lua` — auto-generated API stubs for the *installed* version: `hl.*` functions (`HL.API`), dispatchers (`HL.Dsp*Namespace`), `HL.BindOptions`, monitor/workspace/layer-rule fields, event names, and every `hl.config` key with its type. Grep it before guessing a name. It does **not** list window-rule effect fields (`HL.WindowRuleSpec` only has `match`/`name`/`enabled`) — for those, see reference.md and let verification catch typos.
3. `/usr/share/hypr/hyprland.lua` — upstream example config (gestures, `hl.device`, special workspaces, layer rules).
4. https://wiki.hypr.land/ — option semantics (same options as `.conf`, just Lua tables).

## Editing style

The user wants **small, targeted diffs**. Keep the existing section order and don't reorganize, reformat or "tidy" unrelated parts — a moved block reads as a deleted one in a diff, and that has alarmed the user before. If a restructure seems genuinely worth it, propose it and wait.

Sections (Danish comment headers) — add new lines to the matching one rather than the end of the file: PROGRAMMER (program vars) → AUTOSTART → MILJØVARIABLER → MONITORER → WORKSPACE REGLER → UDSEENDE → ANIMATIONER → KEYBINDS → VINDUESREGLER → EKSTRA SOURCES. Before adding a keybind, check `hypr-check.sh binds` for the combo so you don't silently shadow an existing one.

## Apply and verify

**Autoreload is on**: Hyprland reloads the moment `hyprland.lua` or any `require()`d file is saved. So a broken edit goes live instantly, and a Lua *runtime* error (e.g. calling a dispatcher that doesn't exist) aborts the file at that line — every bind and rule below it silently stops existing until it's fixed. Therefore:

- After every edit, run `hypr-check.sh`. It wraps `Hyprland --verify-config`, which reports, with line numbers: syntax errors, unknown window-rule fields (`unknown field 'flaot'`), wrong value types, unknown `hl.config` keys and nil dispatchers. Fix anything it reports before moving on, then tell the user it came back clean.
- Verification has blind spots, so a clean result doesn't prove the edit *works*:
  - unknown bind options (`{ repeatin = true }`) are silently ignored,
  - rule keys inside exec rules (`hl.exec_cmd(cmd, { … })`) aren't checked,
  - pasted `.conf` lines that happen to be valid Lua (above),
  - a regex that can never match (lookahead, or a partial string — see below) loads fine and just never fires.

  So also confirm the effect: a new bind shows up in `hypr-check.sh binds` with the flags you expected; a new rule is checked against the real strings in `hypr-check.sh clients`.
- If the script reports that verification **crashed**, that isn't a verdict — the config wasn't checked. A known cause is a top-level `hl.exec_cmd(cmd, rules)` (segfaults `--verify-config` on 0.56.2); fix that or inspect the change by hand.
- For a large or risky change, write the new file to a scratch path first and run `hypr-check.sh /path/to/candidate.lua` — it verifies it against the live `dms/` dir without touching the running config — then apply.
- `hyprctl reload` is normally redundant (autoreload already did it). If you need to force one, `hypr-check.sh -- reload config-only` skips re-initialising monitors (avoids an HDR/modeset flicker).
- **No reload at all** for `.desktop` files or icons — rofi and icon lookup read those live. At most `update-desktop-database /home/enzord/.local/share/applications` / `gtk-update-icon-cache -f -t /home/enzord/.local/share/icons/hicolor`.
- The `hyprland.start` autostart block only runs when Hyprland starts, and `hl.env` changes don't reach apps that are already running. For those, say it takes effect at next login (or start the program by hand) instead of claiming it's live.

## DMS auto-generation boundary

- `dms/cursor.lua` (required in MILJØVARIABLER) and `dms/windowrules.lua` (required at the top of VINDUESREGLER) are regenerated by DMS — never hand-edit their contents, only the `require()` call site.
- `dms/colors.lua` and `dms/layout.lua` exist but are deliberately **not** required: they'd override the manual border colours, border size and rounding in UDSEENDE. Wiring either in is the user's decision — ask first.
- DMS writes **Lua only** (`dms/*.lua`), never `.conf`, and never touches `hyprland.lua` itself — only files inside `dms/`. Its full Lua-mode set (`/usr/share/doc/dms-shell/Hyprland_Lua_Migration.md`) is `colors`, `outputs`, `layout`, `cursor`, `binds`, `binds-user`, `windowrules`; this machine only has the four above (`ls /home/enzord/.config/hypr/dms/` to re-check).
- So **DMS Settings pages only take effect for files that are required**: Cursor → `cursor.lua` and Window Rules → `windowrules.lua` work; Displays → `dms/outputs.lua`, Keyboard Shortcuts → `dms/binds-user.lua` and Theme Colors → `colors.lua` don't, because those aren't required here (monitors, binds and colours live in `hyprland.lua`). "I changed it in DMS settings and nothing happened" usually means this — make the change in `hyprland.lua` instead, or ask before wiring the file in.

## Window rules: gotchas that have bitten before

- Get match strings from `hypr-check.sh clients`, not from guessing the app name — Electron/Proton apps often have odd classes (`steam_app_default`, `battle.net.exe`), and terminal/launcher titles change after the window opens.
- **Every match is a whole-string RE2 match** (Hyprland only uses `RE2::FullMatch`). `title = "OpenRGB"` matches a window titled exactly `OpenRGB`, not `OpenRGB 0.9`. For "starts with" or "contains", write it: `"^Battle\\.net.*$"`, `".*Chats.*"`. Escape literal dots.
- **No lookahead** in RE2: `"^(?!Battle\\.net).*$"` loads fine but makes the whole rule never match. Exclude with the `negative:` prefix — and remember it's a whole-string match too: `"negative:Battle\\.net"` only excludes a window titled exactly `Battle.net`; `"negative:Battle\\.net.*"` excludes every Battle.net window.
- One `match` table holds one `title` (Lua keys are unique) and all keys must hit (AND). To exclude or include several titles, extend the one regex with alternation: `"negative:(Battle\\.net.*|Some Launcher)"`. For OR across *different* keys, write two rules.
- `monitor = X` without `silent` moves focus **and the cursor** to X when the window opens (`focusMonitor`). Background apps need `monitor = monLeft .. " silent"`; see "Putting an app on a workspace or monitor". Symptom: "the cursor jumps to the other screen when <app> starts / at login".
- Games under the DMS bar: Proton games often go borderless instead of requesting real fullscreen. The existing `^steam_app_.*$` rule uses `fullscreen_state = "2 2"` (internal *and* client state) — plain `2` only set the client state and the bar stayed on top. The rule also matches `float = false`, so it only hits windows Hyprland would tile: splash screens, fixed-size launchers and dialogs are auto-floated and drop out by themselves (a fullscreened splash used to steal fullscreen from the game that opened after it — Satisfactory). Tested: the `float` match prop sees Hyprland's *automatic* floating only, **not** `float = true` set by another rule — so a window floated by its own rule (the Battle.net ones) still needs the rule's `negative:` title exclusion. A new launcher that Hyprland already floats needs nothing; one that only floats because of a rule goes into the `negative:` regex. A game whose main window has fixed size hints is auto-floated too and gets no forced fullscreen — give that game its own rule.

## Putting an app on a workspace or monitor

Do it the way discord is set up: a `hl.window_rule` with `workspace`/`monitor` (+ `no_initial_focus` if it shouldn't steal focus), and for "start at login" an `hl.exec_cmd` line in the `hyprland.start` block. For a background app, both need `silent`: `workspace = "10 silent"` **and** `monitor = monLeft .. " silent"` — without the second one, Hyprland focuses that monitor and warps the cursor there when the window opens (this is what kept dragging the cursor to the left monitor at login; `no_initial_focus` doesn't stop it). That's all. It applies however the app is started, and its fields are validated.

**Don't touch the workspace rules for this.** Only workspaces 1 and 2 are pinned to a monitor; 3–10 deliberately have no monitor, so empty ones follow whichever monitor the user is on. A window rule with `monitor = …` only holds that workspace on the monitor while the app lives there, and it's free again once the app closes. A new `hl.workspace_rule` for the same workspace (or rewriting the `for i = 3, 10` loop) would pin it for good, and a second rule for the same workspace is a duplicate. The user has rejected both. If they explicitly ask to pin a workspace to a monitor, that's a different request.

Exec rules — `hl.exec_cmd("app", { workspace = "3 silent" })` — only affect that one launch and aren't validated; if you use them, put them inside the `hyprland.start` block, never at top level (a top-level exec re-runs on every autoreload and crashes `--verify-config`).

## Wiring a terminal tool in as a floating window

1. `.desktop` launcher: `Exec=kitty --class <name> -e <command>`. A unique `--class` is the stable handle — terminal titles change as programs run, so don't depend on the title.
2. Rule under VINDUESREGLER, matching that class:
   ```lua
   hl.window_rule({
   	match = { class = "<name>" },
   	float = true,
   	size = "844 634", -- optional; the size the other small TUIs use
   })
   ```
   Older rules match `class = "kitty", title = "<tool>"` — those only hit windows started with plain `kitty -e <tool>` / `kitty --title <tool>`. When adding a launcher with `--class` for such a tool, update the rule to match the class (or both launch paths), otherwise the window silently stops floating.
3. Icon: first look for one the app already ships (`/usr/share/icons`, `/usr/share/pixmaps`, the package's files) or a fitting theme icon name (`Icon=bluetooth` works). Only if nothing fits, drop an svg into `/home/enzord/.local/share/icons/hicolor/scalable/apps/<name>.svg` and set `Icon=<name>`.
4. Run `hypr-check.sh` (verifies, and flags ownership if this session is root), then launch it once and check `hypr-check.sh clients` shows it floating.
