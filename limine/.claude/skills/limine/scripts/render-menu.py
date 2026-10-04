#!/usr/bin/env python3
"""Render an approximate preview of the Limine boot menu from a limine.conf. Read-only.

Usage:
  render-menu.py [-c CONF] [-o OUT.png] [--esp /boot] [--resolution 3840x2160]
                 [--wallpaper IMG] [--expand NAME ...] [--interrupted]

-c defaults to /boot/limine.conf; point it at a *proposed* copy to preview a change
before it touches /boot. --wallpaper overrides the configured one (e.g. an image not
yet copied to the ESP).

Accuracy: colours, margins, font scaling, branding/help/countdown text and the entry
list follow Limine 12.x's documented behaviour and the strings in its binary; layout
(centred menu, tree glyphs, header rows) was calibrated against a photo of the real
screen. Glyph shapes (TTF instead of Limine's VGA bitmap font) and the exact row of the
countdown line are approximations — a preview of look and content, not a screenshot.
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf",
]
DEFAULT_PALETTE = ["000000", "aa0000", "00aa00", "aa5500", "0000aa", "aa00aa", "00aaaa", "aaaaaa"]


def hexrgb(h, default="000000"):
    h = (h or default).strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def parse(conf_text):
    """Return (globals dict with list values for repeatable keys, top-level entry tree)."""
    g, root, stack = {}, [], []
    in_entries = False
    for raw in conf_text.splitlines():
        line = raw.strip()
        m = re.match(r"^(/+)(\+?)(.*)$", line)
        if m:
            in_entries = True
            depth, expanded, name = len(m.group(1)), bool(m.group(2)), m.group(3).strip()
            node = {"name": name, "expanded": expanded, "children": [], "depth": depth, "opts": {}}
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            (stack[-1]["children"] if stack else root).append(node)
            stack.append(node)
            continue
        kv = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, val = kv.group(1).lower(), kv.group(2)
        if in_entries and stack:
            stack[-1]["opts"].setdefault(key, val)
        elif not in_entries:
            g.setdefault(key, []).append(val)
    return g, root


def visible_rows(nodes, expand, level=0, path=(), lasts=()):
    """Flatten the tree the way the menu shows it: children only under expanded dirs.
    `lasts` records, per ancestor level, whether that ancestor was the last sibling
    (decides whether a vertical tree line continues past it)."""
    rows = []
    for i, n in enumerate(nodes):
        is_dir = bool(n["children"])
        open_ = is_dir and (n["expanded"] or n["name"] in expand)
        last = i == len(nodes) - 1
        rows.append({"level": level, "name": n["name"], "dir": is_dir, "open": open_,
                     "path": path + (n["name"],), "last": last, "lasts": lasts,
                     "comment": n["opts"].get("comment", "")})
        if open_:
            rows += visible_rows(n["children"], expand, level + 1, path + (n["name"],), lasts + (last,))
    return rows


def tree_prefix(r):
    """Text before the entry name, matching Limine 12's tree drawing:
       [-] Arch Linux          level 0 dir      (name at col 4)
        ├──→ linux-cachyos     level 1 leaf     (name at col 6)
        └[+] Snapshots         level 1 dir, last child
           EFI fallback        level 0 leaf"""
    L = r["level"]
    seg = ("[-]" if r["open"] else "[+]") if r["dir"] else ("──→" if L else "   ")
    if L == 0:
        return seg + " "
    pre = [" "] * (2 * L - 1)
    for k in range(1, L):  # continuation lines for ancestors that still have siblings below
        if not r["lasts"][k]:
            pre[2 * k - 1] = "│"
    return "".join(pre) + ("└" if r["last"] else "├") + seg + " "


def limine_version(esp):
    try:
        m = re.search(rb"Limine (\d+\.\d+\.\d+) \(x86-64, UEFI\)", (Path(esp) / "EFI/limine/limine_x64.efi").read_bytes())
        return m.group(1).decode() if m else "12.x"
    except OSError:
        return "12.x"


def secure_boot_active():
    try:
        return Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").read_bytes()[-1] == 1
    except OSError:
        return False


def pick_default(rows, spec):
    spec = (spec or "1").strip()
    if spec.isdigit():
        i = int(spec) - 1
        return i if 0 <= i < len(rows) else 0
    want = tuple(p for p in re.split(r"(?<!\\)/", spec) if p)
    for i, r in enumerate(rows):
        if r["path"] == want:
            return i
    return 0


def resolve_path(p, esp):
    p = p.split("#", 1)[0].lstrip("$")
    p = re.sub(r"^[a-z_]*\([^)]*\):", "", p)
    return Path(esp) / p.lstrip("/")


def strict_mode(esp):
    """Secure Boot active + config hash enrolled -> Limine disables the editor."""
    try:
        sb = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").read_bytes()[-1] == 1
        blob = (Path(esp) / "EFI/limine/limine_x64.efi").read_bytes()
        i = blob.find(b"CONFIG_B2SUM_SIGNATURE++")
        return sb and i >= 0 and blob[i + 24:i + 40] != b"0" * 16
    except OSError:
        return False


CP437 = {"─": 0xC4, "│": 0xB3, "├": 0xC3, "└": 0xC0, "→": 0x1A}
DEFAULT_BITMAP_FONT = Path(__file__).resolve().parent.parent / "assets" / "VGA8.F16"


class BitmapFont:
    """Limine-style CP437 bitmap font: 256 glyphs, 8 px wide, `height` bytes each."""

    def __init__(self, path, height, sx, sy, spacing):
        self.data = Path(path).read_bytes()
        if len(self.data) != 256 * height:
            raise ValueError(f"{path}: {len(self.data)} bytes, expected {256 * height} for 8x{height}")
        self.h, self.sx, self.sy, self.spacing = height, sx, sy, spacing
        self.cache = {}

    def mask(self, ch):
        code = CP437.get(ch, ord(ch) if ord(ch) < 256 else ord("?"))
        if code not in self.cache:
            w = 8 + self.spacing
            img = Image.new("L", (w, self.h))
            px = img.load()
            for y in range(self.h):
                row = self.data[code * self.h + y]
                for x in range(8):
                    if row & (0x80 >> x):
                        px[x, y] = 255
                # line-drawing glyphs extend into the spacing column so borders join (VGA 9th-column rule)
                if 0xC0 <= code <= 0xDF and row & 0x01:
                    for x in range(8, w):
                        px[x, y] = 255
            self.cache[code] = img.resize((w * self.sx, self.h * self.sy), Image.NEAREST)
        return self.cache[code]


def load_font(px):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--conf", default="/boot/limine.conf")
    ap.add_argument("-o", "--out", default="limine-preview.png")
    ap.add_argument("--esp", default="/boot")
    # The firmware hands Limine the 4K monitor's mode on this machine (verified from a photo)
    ap.add_argument("--resolution", default="3840x2160")
    ap.add_argument("--interrupted", action="store_true",
                    help="render as after a keypress: countdown gone, selected entry's comment shown")
    ap.add_argument("--wallpaper")
    ap.add_argument("--font", help="CP437 .F16-style font file (overrides term_font; e.g. one not yet on the ESP)")
    ap.add_argument("--expand", nargs="*", default=[], help="directory names to show expanded")
    a = ap.parse_args()

    g, tree = parse(Path(a.conf).read_text(errors="replace"))
    get = lambda k, d=None: (g.get(k) or [d])[0]
    W, H = (int(x) for x in (get("interface_resolution") or a.resolution).lower().split("x"))

    # --- background: wallpaper or black -------------------------------------------------
    wp_path = Path(a.wallpaper) if a.wallpaper else (resolve_path(g["wallpaper"][0], a.esp) if g.get("wallpaper") else None)
    has_wp = bool(wp_path) and get("graphics", "yes") != "no"
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    notes = []
    if has_wp:
        try:
            wp = Image.open(wp_path).convert("RGB")
            style = get("wallpaper_style", "stretched")
            if style == "centered":
                canvas = Image.new("RGB", (W, H), hexrgb(get("backdrop"), "000000"))
                canvas.paste(wp, ((W - wp.width) // 2, (H - wp.height) // 2))
            elif style == "tiled":
                for x in range(0, W, wp.width):
                    for y in range(0, H, wp.height):
                        canvas.paste(wp, (x, y))
            else:
                canvas = wp.resize((W, H), Image.BILINEAR)
            notes.append(f"wallpaper {wp_path.name} {wp.width}x{wp.height} ({style})")
        except Exception as e:
            has_wp = False
            notes.append(f"wallpaper not loaded: {e}")

    # --- terminal box -------------------------------------------------------------------
    margin = int(get("term_margin", "64" if has_wp else "0"))
    grad = min(int(get("term_margin_gradient", "4" if has_wp else "0")), margin)
    bg = get("term_background", "80000000" if has_wp else "00000000")
    bg = bg.zfill(8) if len(bg) > 6 else "00" + bg
    alpha = 255 - int(bg[:2], 16)  # TT = transparency
    bg_rgb = hexrgb(bg[2:])
    box = (margin, margin, W - margin, H - margin)
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for i in range(grad, 0, -1):  # soft edge around the box
        od.rectangle((box[0] - i, box[1] - i, box[2] + i, box[3] + i),
                     fill=bg_rgb + (int(alpha * (1 - i / (grad + 1))),))
    od.rectangle(box, fill=bg_rgb + (alpha,))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(canvas)

    # --- font grid (Limine: 8x16 glyphs, spacing 1, scale by resolution) ----------------
    scale = get("term_font_scale")
    if scale and re.fullmatch(r"[1-8]x[1-8]", scale):
        sx, sy = (int(v) for v in scale.split("x"))
    else:
        sx = sy = 4 if W >= 5120 and H >= 2880 else 2 if W >= 2560 and H >= 1440 else 1
    spacing = int(get("term_font_spacing", "1"))
    fh = 16
    font_path = Path(a.font) if a.font else (resolve_path(get("term_font"), a.esp) if get("term_font") else DEFAULT_BITMAP_FONT)
    if a.font or get("term_font"):
        size = get("term_font_size", "8x16")
        if re.fullmatch(r"8x\d+", size):
            fh = int(size.split("x")[1])
    try:
        bmf = BitmapFont(font_path, fh, sx, sy, spacing)
        if font_path != DEFAULT_BITMAP_FONT:
            notes.append(f"font {font_path.name} (8x{fh})")
    except (OSError, ValueError) as e:
        bmf, fh = None, 16
        notes.append(f"bitmap font unavailable ({e}); using TTF approximation")
    cw, ch = (8 + spacing) * sx, fh * sy
    font = load_font(int(14 * sy))
    cols = (box[2] - box[0]) // cw
    rows_n = (box[3] - box[1]) // ch
    x0 = box[0] + ((box[2] - box[0]) - cols * cw) // 2
    y0 = box[1] + ((box[3] - box[1]) - rows_n * ch) // 2

    pal = (g.get("term_palette") or [";".join(DEFAULT_PALETTE)])[0].split(";")
    pal_b = (g.get("term_palette_bright") or [""])[0].split(";")
    pal_col = lambda i, bright=False: hexrgb((pal_b if bright and len(pal_b) == 8 else pal)[i])
    fg = hexrgb(get("term_foreground"), "aaaaaa")
    # Interface colours default to the palette's green/cyan slots (so a custom term_palette recolours them)
    help_c = hexrgb(get("interface_help_colour") or get("interface_help_color")) if (get("interface_help_colour") or get("interface_help_color")) else pal_col(2)
    help_cb = get("interface_help_colour_bright") or get("interface_help_color_bright")
    help_cb = hexrgb(help_cb) if help_cb else pal_col(2, True)
    brand_c = hexrgb(get("interface_branding_colour") or get("interface_branding_color")) if (get("interface_branding_colour") or get("interface_branding_color")) else pal_col(6)
    comment_c = pal_col(6)

    def put(row, col, segs):
        """segs: list of (text, colour[, reverse]). Draw on the character grid."""
        x = x0 + col * cw
        y = y0 + row * ch
        for seg in segs:
            text, colour = seg[0], seg[1]
            if len(seg) > 2 and seg[2]:  # reverse video: fg as background, bg as text
                d.rectangle((x, y, x + len(text) * cw, y + ch), fill=colour)
                colour = bg_rgb
            for chr_ in text:
                if bmf:
                    canvas.paste(Image.new("RGB", (cw, ch), colour), (x, y), bmf.mask(chr_))
                elif chr_ in "─│├└":  # TTF fallback: draw box glyphs as lines so they join
                    mx, my = x + cw // 2, y + ch // 2
                    lw = max(1, sx)
                    if chr_ in "─├└":
                        d.line((mx if chr_ != "─" else x, my, x + cw, my), fill=colour, width=lw)
                    if chr_ in "│├":
                        d.line((mx, y, mx, y + ch), fill=colour, width=lw)
                    if chr_ == "└":
                        d.line((mx, y, mx, my), fill=colour, width=lw)
                else:
                    d.text((x + (cw - font.getlength(chr_)) / 2, y + (ch - 14 * sy) / 2 - sy), chr_, font=font, fill=colour)
                x += cw

    def centered(row, segs):
        put(row, max(0, (cols - sum(len(s_[0]) for s_ in segs)) // 2), segs)

    # --- entries ------------------------------------------------------------------------
    vis = visible_rows(tree, set(a.expand))
    sel = pick_default(vis, get("default_entry"))
    cur = vis[sel]

    # --- header: branding, help (depends on the selected entry), firmware key -----------
    # An explicitly empty `interface_branding:` hides the title line
    brand = get("interface_branding") if "interface_branding" in g else f"Limine {limine_version(a.esp)} (x86-64, UEFI{', Secure Boot' if secure_boot_active() else ''})"
    if brand.strip():
        centered(0, [(brand, brand_c)])
    editor_off = get("editor_enabled", "yes") == "no" or strict_mode(a.esp)
    if get("interface_help_hidden", "no") != "yes":
        action = ("Collapse" if cur["open"] else "Expand") if cur["dir"] else "Boot"
        segs = [("ARROWS", help_c), (" Select    ", fg), ("ENTER", help_c), (" " + action, fg)]
        if not cur["dir"] and not editor_off:
            segs += [("    ", fg), ("E", help_c), (" Edit", fg)]
        centered(2, segs)
        centered(4, [("S", help_c), (" Firmware Setup", fg)])

    # --- countdown (row is a best guess; not yet verified against the real screen) -------
    timeout = get("timeout", "5")
    counting = not a.interrupted and timeout not in ("no", "0")
    if counting:
        centered(6, [("Booting automatically in ", fg), (timeout.split(".")[0], help_cb), ("...", fg)])
    elif timeout == "0":
        notes.append("timeout 0: the menu is skipped entirely at boot")

    # --- tree: block centred horizontally and vertically --------------------------------
    top_free, bottom_free = 8, rows_n - 3
    max_rows = max(1, bottom_free - top_free)
    first = max(0, min(sel - max_rows // 2, len(vis) - max_rows))
    shown = vis[first:first + max_rows]
    prefixes = [tree_prefix(r) for r in shown]
    block_w = max(len(p) + len(r["name"]) for p, r in zip(prefixes, shown))
    left = max(0, (cols - block_w) // 2)
    row0 = max(top_free, (rows_n - len(shown)) // 2)
    for i, (r, pre) in enumerate(zip(shown, prefixes)):
        if first + i == sel:  # Limine highlights " name " only, in reverse video
            put(row0 + i, left, [(pre[:-1], fg), (" " + r["name"] + " ", fg, True)])
        else:
            put(row0 + i, left, [(pre + r["name"], fg)])

    # --- bottom: selected entry's comment (cyan) ----------------------------------------
    if cur["comment"]:
        centered(rows_n - 2, [(cur["comment"][:cols], comment_c)])

    canvas.save(a.out)
    print(f"wrote {a.out} ({W}x{H}, font scale {sx}x{sy}, {cols}x{rows_n} cells)")
    print(f"selected: {'/'.join(cur['path'])} | timeout: {timeout}{' (countdown shown)' if counting else ''}")
    for n in notes:
        print("note:", n)


if __name__ == "__main__":
    sys.exit(main())
