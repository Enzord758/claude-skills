# hl.* Lua API surface in use (hyprland.lua)

The subset of the Hyprland 0.55+ Lua API this config actually uses, in its house style — so new lines look like the old ones. The file is indented with **tabs**. For anything not here, grep `/usr/share/hypr/stubs/hl.meta.lua` (authoritative names/types for the installed version), then the upstream example `/usr/share/hypr/hyprland.lua`, then https://wiki.hypr.land/. When in doubt, read the current `hyprland.lua` — it wins over this file.

## Program variables (PROGRAMMER)

```lua
local terminal = "kitty"
local fileManager = "nautilus -w"
local menu = "rofi -show drun"
local browser = "zen-browser"
local screenshotRegion = "hyprshot -m region"
local screenshotWindow = "hyprshot -m window"
local screenshotMonitor = "hyprshot -m output"
local mainMod = "SUPER"
```
Reuse these in binds rather than hardcoding the program again; a command used by more than one bind earns its own `local` here.

## Autostart (AUTOSTART)

```lua
hl.on("hyprland.start", function()
	hl.exec_cmd("dms run")
	hl.exec_cmd("discord")
end)

hl.on("monitor.added", function(mon)
	local main = hl.get_monitor(monMain)
	if main and main.id == mon.id then
		hl.timer(function() hl.exec_cmd("xrandr --output " .. mon.name .. " --primary") end,
			{ timeout = 1000, type = "oneshot" })
	end
end)
```
`hyprland.start` runs once per Hyprland start, not on reload. Other events for `hl.on` (e.g. `window.open`, `monitor.added`, `config.reloaded`) are the `HL.EventName` list at the top of the stubs file; `monitor.added` passes the monitor and also fires for the monitors that come up at login.

Cursor at login: `cursor.default_monitor = monMain` (UDSEENDE) is all it takes — Hyprland warps to it when that monitor is added. There is deliberately no cursor timer here: an earlier one "didn't work" because the Discord rule warped the cursor away again (see the `silent` note under window rules). If the cursor ends up on the wrong monitor, look for a window rule with a non-silent `monitor` before adding timers.

`hl.exec_cmd(cmd, rules)` takes an optional second table of exec rules (e.g. `{ workspace = "3 silent" }`) that apply to that one launch. Keep it inside this block: at top level it re-runs on every autoreload, and a top-level call *with* rules segfaults `Hyprland --verify-config` on 0.56.2. Rule keys here are not validated — for permanent placement a window rule is the better tool.

## Env vars (MILJØVARIABLER)

```lua
require("dms.cursor") -- DMS-generated cursor theme/size env vars; don't set XCURSOR_* by hand
hl.env("QT_QPA_PLATFORM", "wayland")
```

## Monitors (MONITORER)

Monitors are never referenced by port name (`DP-2`, `HDMI-A-1` — they change when cables move or after driver updates). Two locals in PROGRAMMER hold `desc:` selectors, and every `output`/`monitor`/`default_monitor`/`hl.get_monitor` uses them:

```lua
local monMain = "desc:Dell Inc. DELL G3223Q 3Y6S2P3" -- 4K HDR hovedskærm
local monLeft = "desc:Samsung Electric Company LF27T850 H4LNB00913" -- venstre skærm
```
`desc:` is a prefix match on `hyprctl monitors` → `description`. Something that only knows port names (e.g. `xrandr --output`) gets it at runtime: `hl.get_monitor(monMain).name`.

```lua
hl.monitor({
	output = monMain,
	mode = "3840x2160@143,96",
	position = "0x0",
	scale = "1",
	bitdepth = 10,
	vrr = 1,
	cm = "auto",
	min_luminance = 0.0,
	max_luminance = 600,
	max_avg_luminance = 250,
})
```
`monLeft` sits at `-2560x400` (left of `monMain`). All valid fields: `HL.MonitorSpec` in the stubs.

## Workspace rules (WORKSPACE REGLER)

```lua
hl.workspace_rule({ workspace = "1", monitor = monMain, default = true, layout = "scrolling" })
for i = 3, 10 do
	hl.workspace_rule({ workspace = tostring(i), layout = "dwindle" })
end
```
Workspaces 1–2 use `scrolling` (1 on `monMain`, 2 on `monLeft`), 3–10 `dwindle`. Fields: `HL.WorkspaceRuleSpec`.

3–10 have **no monitor on purpose**: empty ones follow the user between monitors. To put an app on one of them, use a window rule like discord's (it only holds the workspace on that monitor while the app is there). Don't add a second rule for a workspace or edit the loop for that; it pins the workspace permanently.

## General options (UDSEENDE)

`hl.config({ ... })` takes the `hyprland.conf` sections as nested tables: `general` (with `col.active_border` as `{ colors = {...}, angle = 45 }` gradient), `render`, `decoration` (`shadow`, `blur`), `master`, `misc`, `debug`, `input`, `cursor`, `scrolling`. Multiple `hl.config` calls merge (the file has a separate `hl.config({ animations = { enabled = true } })`). To change a value, edit it in the existing table rather than adding a second call that overrides it further down. Every key and its type: `HL.ConfigOpt.*` classes in the stubs; the live value: `hypr-check.sh -- getoption general:gaps_in`.

## Animations (ANIMATIONER)

```lua
hl.curve("easeOutQuint", { type = "bezier", points = { { 0.23, 1 }, { 0.32, 1 } } })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 4.1, bezier = "easeOutQuint", style = "popin 87%" })
```
Curves defined: `easeOutQuint`, `easeInOutCubic`, `linear`, `almostLinear`, `quick` (plus built-in `default`). Leaves in use: global, border, windows, windowsIn/Out, fadeIn/Out, fade, layers, layersIn/Out, fadeLayersIn/Out, workspaces, workspacesIn/Out, zoomFactor.

## Keybinds (KEYBINDS)

```lua
hl.bind(mainMod .. " + RETURN", hl.dsp.exec_cmd(terminal))
hl.bind(mainMod .. " + Q", hl.dsp.window.close())
hl.bind(mainMod .. " + SHIFT + M", hl.dsp.exit())
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + F", hl.dsp.window.fullscreen())
hl.bind(mainMod .. " + left", hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + SHIFT + left", hl.dsp.window.move({ direction = "l" }))
hl.bind(mainMod .. " + h", hl.dsp.window.resize({ x = -25, y = 0, relative = true }), { repeating = true })
hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind("Print", hl.dsp.exec_cmd(screenshotMonitor))
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })

for i = 1, 9 do
	hl.bind(mainMod .. " + " .. i, hl.dsp.focus({ workspace = tostring(i) }))
	hl.bind(mainMod .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = tostring(i) }))
end
```
- Keys are one string: `"SUPER + SHIFT + X"`. Key names follow xkb (`period`, `Print`, `XF86AudioMute`, `mouse:272`).
- Third arg = options, from `HL.BindOptions` in the stubs: `repeating` (held-key repeat), `locked` (works on lock screen), `release`, `long_press`, `non_consuming`, `click`, `drag`, `description`… **Unknown option names are silently ignored** — verification won't catch `repeatin`, so copy names from the stubs and check the flags in `hypr-check.sh binds` afterwards.
- `{ mouse = true }` on the two mouse:272/273 binds is copied from the upstream example but isn't in `HL.BindOptions` and has no effect on 0.56.2 (`hyprctl binds` shows `mouse: false`); `window.drag()`/`window.resize()` handle the mouse themselves. Leave the existing lines alone; don't add it to new binds expecting it to do something.
- Dispatchers live in `hl.dsp.*`, `hl.dsp.window.*`, `hl.dsp.workspace.*`, `hl.dsp.group.*`, `hl.dsp.cursor.*` — the complete list is the `HL.Dsp*Namespace` classes in the stubs. A misspelt dispatcher is a runtime error that stops the rest of the file loading, so check the stubs rather than guessing.
- Currently taken with SUPER: RETURN Q E V SPACE B F period Print h j k l 0–9 arrows mouse_up/down mouse:272/273; SUPER+SHIFT: M Print 0–9 arrows. Re-check with `hypr-check.sh binds` before trusting this list.

## Window rules (VINDUESREGLER)

```lua
require("dms.windowrules") -- first line of the section; DMS-generated rules

hl.window_rule({
	match = { class = "kitty", title = "btop" },
	float = true,
	size = "1250 1000",
})

hl.window_rule({
	match = { class = "battle.net.exe" },
	float = true,
	size = "1845 1000",
	monitor = monMain,
	workspace = "3",
})

hl.window_rule({
	match = { class = "battle.net.exe" },
	suppress_event = "maximize",
})

hl.window_rule({
	match = { class = "^steam_app_.*$", float = false, title = "negative:Battle\\.net.*" }, -- float = false: auto-floated splash/launchers drop out; .* needed: whole-string match
	fullscreen_state = "2 2", -- internal + client; plain 2 left the DMS bar on top
})

hl.window_rule({
	match = { title = "HyprEmoji" },
	float = true,
	size = "450 385",
	move = {
		"min(cursor_x-(window_w*0.50),(monitor_w-window_w))",
		"min(cursor_y-(window_h*0.05),(monitor_h-window_h))",
	},
})

hl.window_rule({
	match = { class = "discord" },
	workspace = "10 silent",
	monitor = monLeft .. " silent",
	no_initial_focus = true,
})
```
- `match` values are RE2 regexes matched against the **whole** string (a plain `"btop"` means exactly `btop`); no lookahead — exclude with a `negative:` prefix, which is whole-string too. All keys in one `match` must hit (AND). Match keys seen here: `class`, `title`; also valid: `initial_class`, `initial_title`, `xwayland`, `tag` (snake_case versions of the wiki's windowrule props). An unknown match key is reported as `unknown match property '…'`.
- **`monitor` needs its own `silent`.** A rule with `monitor = X` (no `silent`) makes Hyprland call `focusMonitor` when the window opens on another monitor than the focused one, which **warps the cursor** there (monitor middle, or the window's middle if one is focusable). `workspace = "N silent"` and `no_initial_focus` do not prevent it. For apps that should open in the background (Discord at login), write `monitor = monLeft .. " silent"` — Hyprland takes `silent` from the last space-separated word, so it works with `desc:` strings containing spaces. Leave it non-silent only when following the window is wanted (the games on `monMain`).
- Effect fields used: `float`, `size` ("w h"), `move` (expression strings), `fullscreen_state`, `monitor`, `workspace`, `no_initial_focus`, `suppress_event`. The stubs don't list effect fields; they're snake_case versions of the wiki's windowrule effect names, and an unknown one is reported by `hypr-check.sh` as `unknown field '…'`.

## Layer rules

Not in the main file yet; DMS's `dms/layout.lua` shows the shape:
```lua
hl.layer_rule({
	match = { namespace = "^dms:bar$" },
	xray = true,
})
```
Fields: `HL.LayerRuleSpec` in the stubs. Namespaces of open layers: `hypr-check.sh -- layers`.

## Sub-files

Split files with Lua `require()` — dot = subdirectory, so `require("dms.cursor")` loads `dms/cursor.lua`. Not `dofile()` or `hl.source()`. Required files are watched by autoreload too. The existing requires sit in the section they belong to (`dms.cursor` in MILJØVARIABLER, `dms.windowrules` in VINDUESREGLER); the EKSTRA SOURCES section at the end is only a comment block explaining this and why `dms.colors`/`dms.layout` are left out.
