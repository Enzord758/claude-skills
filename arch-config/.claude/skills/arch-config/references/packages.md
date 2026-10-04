# Packages: pacman, yay, CachyOS repos

## Contents
1. Repos and mirrors
2. Updating
3. Installing / removing (repo, AUR, Flatpak — which one?)
4. Keyring and signature errors
5. .pacnew / .pacsave
6. "It broke after an update" — downgrade and rollback
7. Cleanup: orphans and cache
8. makepkg / building AUR packages
9. Useful queries

## 1. Repos and mirrors

`/etc/pacman.conf` order (top wins when the same package exists in several repos):
`cachyos-znver4`, `cachyos-core-znver4`, `cachyos-extra-znver4`, `cachyos`, then Arch `core`, `extra`, `multilib`.

- The znver4 repos are CachyOS rebuilds of Arch packages optimised for Zen 4. They must stay **above** core/extra; moving Arch repos up silently swaps hundreds of packages back to generic builds on the next `-Syu`, and mixing in a different arch level (v3, generic) does the same in reverse. Don't reorder, don't add `[testing]`/`[cachyos-testing]` unless the user explicitly wants testing.
- Mirrors: Arch → `/etc/pacman.d/mirrorlist`, regenerated weekly by `reflector.timer` using `/etc/xdg/reflector/reflector.conf` (`--latest 5 --sort age --protocol https`, no country filter). For faster downloads from Denmark, the improvement is in that config (e.g. `--country Denmark,Germany,Sweden,Netherlands --latest 10 --sort rate`), then `systemctl start reflector.service`. CachyOS → `cachyos-mirrorlist` / `cachyos-v4-mirrorlist` files shipped by packages of the same name (not reflector). Upgrades of those packages produce `.pacnew` files — normally just take the new one.
- `ParallelDownloads = 5`. No `IgnorePkg` set. `SigLevel = Required DatabaseOptional`.

## 2. Updating

- Full upgrade is the only supported way: `sudo pacman -Syu` (repo only) or `yay -Syu` as enzord (repo + AUR; yay asks for sudo itself). The user also has `topgrade` (config in dotfiles) which runs yay, flatpak, firmware etc. — it's interactive, so leave it to the user.
- **Never** `pacman -Sy <pkg>` or `-Sy` without `u`: that's a partial upgrade — the new package links against libraries the rest of the system doesn't have yet. Installing a single package uses `-S` against the current DB; if it 404s because the DB is stale, the answer is a full `-Syu`.
- Checking without touching the system: `checkupdates` (pacman-contrib, uses a temp DB copy) and `yay -Qua` for AUR. `arch-check.sh` does both.
- **AUR cooldown (deliberate hardening):** `~/.config/yay/init.lua` (stow, `~/dotfiles/yay`) holds back any AUR upgrade whose package was modified on the AUR less than 72 h ago — a guard against "adopt orphan, push malicious update". Held packages are logged in `~/.local/state/yay/cooldown.log`. So AUR updates listed by `yay -Qua` that are <72 h old are *expected* to stay pending: don't list them as a to-do for the user; say when they'll be released (AUR `LastModified` + 72 h, from `curl -s 'https://aur.archlinux.org/rpc/v5/info?arg[]=<pkg>' | jq '.results[].LastModified'`). Bypass only on the user's explicit request: `YAY_NO_COOLDOWN=1 yay -Syu`.
- Before a big upgrade (kernel, nvidia, mesa, glibc, Hyprland): skim https://archlinux.org/news/ and the CachyOS announcements for manual-intervention notes. snap-pac takes a **pre**-snapshot of every transaction automatically (the post hook `/etc/pacman.d/hooks/zz-snap-pac-post.hook` is masked to `/dev/null` on purpose — don't say "before and after"), and limine-snapper-sync makes them bootable — that's the safety net.
- Kernel and `linux-cachyos-nvidia-open` (prebuilt module) must move together — they always do in a full `-Syu`. DKMS modules (`xone-dkms-git` for the Xbox controller dongle) rebuild on kernel upgrade via `70-dkms-upgrade.hook` and need `linux-cachyos-headers` at the same version. If a DKMS build fails, the controller simply stops working after reboot — check `dkms status`.
- After a kernel upgrade the running kernel's modules directory is gone → anything that needs a new module (USB stick filesystem, a new device) fails until reboot. `arch-check.sh` flags it. Tell the user to reboot rather than debugging it.
- Initramfs is rebuilt automatically by limine's own pacman hook (`/etc/pacman.d/hooks/90-mkinitcpio-install.hook` from `limine-mkinitcpio-hook`, which overrides the stock mkinitcpio hook on purpose). Don't "fix" that override.

## 3. Installing / removing

Choosing a source, in order of preference:
1. Official repos (Arch + CachyOS): `pacman -Ss <term>`, `pacman -Si <pkg>`. If a `-bin`/`-git` AUR variant exists alongside a repo package, prefer the repo one.
2. AUR via yay (as enzord): look at the PKGBUILD before installing something obscure (`yay -Gp <pkg>`), check votes/last update with `yay -Si <pkg>`. Prefer `-bin` for big Electron/proprietary apps (no hour-long compile), the plain name for small tools.
3. Flatpak (flathub system remote) for sandboxed proprietary apps or when the AUR package is stale/broken.
Give the user one recommendation with a reason, not all three.

- Install: `sudo pacman -S <pkg>` / `yay -S <pkg>`. Mark installed-as-dependency things correctly: `pacman -D --asdeps <pkg>` / `--asexplicit`.
- Remove: `sudo pacman -Rns <pkg>` (removes now-unneeded deps and backup configs → `.pacsave`). Show what it will take with it first: `pacman -Rsp <pkg>` (`--print` can't be combined with `-n`). Never `-Rdd` (ignores deps — breaks things).
- Which package provides a file / command: `pacman -Qo /path` (installed), `pacman -F <name>` (all repos; needs `sudo pacman -Fy` once).

## 4. Keyring and signature errors

"signature from … is unknown trust / invalid or corrupted package (PGP signature)":
1. Usually the keyring package is older than the packager key: `sudo pacman -Sy archlinux-keyring cachyos-keyring && sudo pacman -Su` (this is the one sanctioned `-Sy` without `u` — it's immediately followed by `-Su`).
2. If that fails: `sudo pacman-key --populate archlinux cachyos`, and check the clock (`timedatectl` — NTP is on here).
3. Never set `SigLevel = Never` as a fix.

## 5. .pacnew / .pacsave

pacman never overwrites a config you've modified; it writes `<file>.pacnew` next to it (or `.pacsave` on removal). Find them: `find /etc /boot -xdev -name '*.pacnew' -o -name '*.pacsave'` (as root; `arch-check.sh` does it).

`pacdiff` is interactive (vimdiff) — don't run it from your shell. Instead:
1. `diff -u /etc/X /etc/X.pacnew` and read what changed upstream versus what's local.
2. Propose a merged file: upstream's new structure/defaults + the user's deliberate changes. Then install it, keep `X.claude-bak`, delete the `.pacnew`.

Per-file rules on this machine:
- `pacman.conf.pacnew` — keep the CachyOS repo blocks (above core) and `ParallelDownloads`; take upstream's new options.
- `mirrorlist.pacnew` — delete it; reflector owns the live file.
- `cachyos*-mirrorlist.pacnew` — take the new one (`mv`).
- `makepkg.conf.pacnew` — keep the user's `-march=native -O3`, LTO, `!debug`; take upstream's other changes. Moving the user's flags into `/etc/makepkg.conf.d/local.conf` ends this churn — offer it.
- `locale.gen.pacnew` — keep the two enabled lines (`en_DK.UTF-8`, `en_US.UTF-8`); run `locale-gen` only if they changed.
- `passwd`, `group`, `shadow`, `gshadow` `.pacnew` — **never** replace; they contain the real users. Usually just delete the `.pacnew` after confirming no new system user is missing (`systemd-sysusers` creates those anyway).
- `mkinitcpio.conf.pacnew` — keep the nvidia `MODULES` and the absence of `kms`; after changing → `limine-update`.

## 6. "It broke after an update"

1. Find what changed: `grep -E '\[ALPM\] (upgraded|installed|removed)' /var/log/pacman.log | tail -50`, and the error in the journal / app output.
2. Check whether it's known (Arch news, CachyOS announcements, the package's bug tracker) before patching around it.
3. Options, least invasive first:
   - **Downgrade one package** from cache: `ls /var/cache/pacman/pkg/<pkg>-*` → `sudo pacman -U /var/cache/pacman/pkg/<pkg>-<oldver>-x86_64.pkg.tar.zst`. Then hold it temporarily with `IgnorePkg = <pkg>` in pacman.conf, and tell the user it's held (holding a package back is itself a mild partial upgrade — fine for a leaf app, risky for a library; remove the hold as soon as upstream fixes it). Downgrading a library usually means downgrading its dependents too — check `pacman -Qi <pkg>` "Required By".
   - If the old version isn't in the cache, the Arch Linux Archive (`https://archive.archlinux.org/packages/`) has Arch packages; CachyOS znver4 packages aren't there — the equivalent is the generic Arch build, which is fine as a stopgap.
   - **Roll back the whole system**: snap-pac pre-snapshots are listed in the Limine boot menu → boot the snapshot from before the transaction, confirm it works, then make it permanent with `limine-snapper-restore` (user runs it themselves; limine skill). This is the right move for "doesn't boot / desktop doesn't start" after an update.
4. NVIDIA/kernel mismatch symptoms (black screen, `nvidia-smi` "couldn't communicate with the driver"): compare `pacman -Q linux-cachyos linux-cachyos-nvidia-open nvidia-utils` versions and `uname -r`; a pending reboot is the usual cause.

## 7. Cleanup

- **Orphans**: `pacman -Qdtq` lists packages installed as dependencies that nothing needs. Show the list and let the user confirm — some are optional deps they actually use (e.g. a font or a codec). Then `sudo pacman -Rns <names>` (explicit names, not a blind pipe).
- **Explicitly installed but forgotten**: `pacman -Qetq` (explicit, not required by anything) and `pacman -Qmq` (AUR) are the review list — benchmarks, one-off tools and mod managers tend to linger. Also `pacman -Qdttq` (only held by optdepends). Present candidates with size and what they're for; let the user pick.
- **Package cache** (`/var/cache/pacman/pkg`, on its own `@cache` subvolume so snapshots don't pin it): `paccache.timer` is disabled here. `paccache -dk2` (dry run) → `sudo paccache -rk2` keeps two versions per package (enough for a downgrade), `sudo paccache -ruk0` removes uninstalled ones. Enabling `paccache.timer` (weekly, keeps 3) is the set-and-forget option. Don't use `pacman -Scc` — it destroys the downgrade path.
- **Interrupted-download leftovers**: `ls -d /var/cache/pacman/pkg/download-*` — alpm-owned temp dirs from aborted downloads; paccache ignores them. Safe to `rm -rf` while no pacman/yay is running.
- **yay cache**: `~/.cache/yay` holds AUR build dirs; `yay -Sc` asks per-step. Safe to clear.
- **Flatpak**: `flatpak uninstall --unused`.
- **Disk space on Btrfs**: `df` lies a bit; use `btrfs filesystem usage /`. Old snapshots are often what's holding space — snapper's cleanup policy handles it (see storage in `areas.md`), not manual deletion.

## 8. makepkg / AUR builds

- `/etc/makepkg.conf` here has `-march=native -O3`, `MAKEFLAGS="-j$(nproc)"`, LTO, `!debug`. AUR packages built here are therefore not portable to other CPUs — irrelevant unless the user shares builds.
- `-O3` + LTO occasionally breaks an AUR build or a program at runtime. Workaround for one package: `yay -S <pkg> --mflags "--config /path/with/O2/makepkg.conf"` or add `options=(!lto)` in the PKGBUILD via `yay --editmenu`. Don't change the global flags for one package.
- Build as enzord, never as root.
- `yay-debug` is installed (a leftover debug split package from an earlier build with debug on) — harmless, removable.

## 9. Useful queries

- `pacman -Qi <pkg>` (info, deps, required by, install reason), `pacman -Ql <pkg>` (files), `pacman -Qkk <pkg>` (modified files — shows local edits to package-owned configs).
- `pacman -Qqm` foreign/AUR packages (31 here), `pacman -Qqe` explicit packages.
- `expac`-style sizes without expac: `pacman -Qi | awk '/^Name/{n=$3}/^Installed Size/{print $4$5, n}' | sort -h | tail -20`.
- `pacman -Sl cachyos-extra-znver4 | grep installed` — what comes from which repo; `pacman -Si <pkg> | grep Repository`.
