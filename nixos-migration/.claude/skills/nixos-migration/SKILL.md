---
name: nixos-migration
description: Move an existing Linux desktop (Arch or similar, configured by install scripts and dotfiles) to a NixOS flake that reproduces the same setup, and test it in a QEMU VM before touching the real machine. Covers inventorying the package lists against nixpkgs, choosing stable vs unstable per package, the flake layout (disko, Limine/Secure Boot, NVIDIA, home-manager with the existing dotfiles, desktop on Hyprland/DMS or similar), making dotfiles portable between both systems, porting backup/restore, and an automated VM install-and-login test. Use it whenever someone wants to "switch to NixOS", "turn my install script into a flake", asks what NixOS needs to reproduce their setup, works on a NixOS flake for their own desktop, or has a NixOS VM test that fails — even if they only say "nixos", "flake" or "home-manager".
---

# Migrating a desktop to a NixOS flake

Goal: plain NixOS that behaves like the old machine (same user, disks, boot,
network, desktop, apps, backups), proven in a VM first. Don't port the old
distro's specifics (its kernel builds, repo optimisations, package-manager
tooling): ask the user what "the same" means and write it down.

Read `references/pitfalls.md` when something fails and before the VM test.

## Order of work (each step VM-tested before the next)

1. **Inventory** (read-only): map every package in the old lists to a nixpkgs
   attribute, a NixOS option, "not needed", a community flake, or "own work".
   Use the channel's `packages.json.br` (channels.nixos.org/<channel>/) and
   match by attr, pname and common renames (python-x → python3Packages.x,
   ttf-x-nerd → nerd-fonts.x, -bin/-git suffixes). Verify every name exists.
   Compare stable vs unstable versions for what the user cares about (desktop
   shell, compositor, GPU driver, fan control) before choosing a channel.
2. **Decisions file** in the flake repo: channel(s), hostname, home path and
   group names, bootloader, what's dropped. One line of why each. Update it as
   decisions change; it's what the next session reads.
3. **Skeleton**: disko (disks by-id with serial), bootloader + Secure Boot,
   GPU, user (same uid/gid so restored files keep ownership), network, SSH.
4. **Desktop**: compositor, shell, greeter, audio, fonts; home-manager linking
   the existing dotfiles.
5. **Packages and services** from the inventory.
6. **Backup and restore** ported; secrets (sops-nix/agenix) last, with the user.
7. **Real install** only after the VM install + login test passes; the user
   does it.

## Flake patterns

- **Stable base, unstable where it matters**: two nixpkgs inputs; an overlay
  takes the fast-moving packages from unstable. If a package comes from
  unstable, take **its NixOS module from unstable too**
  (`disabledModules = [ "path/in/nixos/modules.nix" ]; imports = [
  "${nixpkgs-unstable}/nixos/modules/path.nix" ];`, the source passed via
  specialArgs) — stable modules encode the stable package's file layout.
- **Kernel and GPU driver from the same channel**: `boot.kernelPackages =
  unstable.linuxPackages_latest` with `hardware.nvidia.package =
  config.boot.kernelPackages.nvidiaPackages.latest`.
- **A VM-test variant**: same modules plus one test module (test password,
  password SSH, port 22 open in the closed VM, different hostname, GPU env
  off, backup off, heavy extras off), as a second `nixosConfigurations` entry.
  Never let it run the real backup. Evaluate the real config in the test too
  (`nix eval .#nixosConfigurations.<real>.config.system.build.toplevel.drvPath`).
- **Own options** (`options.<ns>.x = mkOption`) for the switches the test
  variant flips; clearer than mkForce on lists.
- **Dotfiles via home-manager, out of store**:
  `config.lib.file.mkOutOfStoreSymlink "${home}/dotfiles/<pkg>/.config/<dir>"`
  so apps that write their own config (shell settings, RGB/fan tools) keep
  working and edits land in the repo. Link login files too (.profile,
  .zprofile, .zshrc).
- **Portable dotfiles** instead of NixOS-only copies: source files from the
  first path that exists (`/usr/share/…` or `/run/current-system/sw/share/…`,
  with `environment.pathsToLink` for the latter), `$HOME`/`os.getenv("HOME")`
  instead of a fixed home, start helpers only if present. Check the old
  system's live session after each change.
- **Backup in the store**: wrap the backup script with `writeShellScriptBin`
  and an explicit PATH, lists via `environment.etc`, the share as an
  `x-systemd.automount` NFS mount, the timer as `systemd.timers`.

## VM test

Use the vm-test-harness skill's techniques (QEMU user-net shaped like the LAN,
serial/QMP, a progress page, a watchdog). NixOS-specific flow that works:

1. Boot the NixOS minimal ISO with empty OVMF vars (Setup Mode); it logs in
   on tty1 by itself: type `sudo passwd root` and the password over QMP
   send-key, then SSH in as root.
2. Copy the committed flake in (`git archive HEAD`), **lock it first**
   (`nix flake lock`), then disko (`--mode destroy,format,mount
   --yes-wipe-all-disks --flake`), then `nixos-install --flake … --no-root-passwd`.
3. Turn Secure Boot on in the vars (virt-fw-vars `--sb`), boot the disk,
   copy in what a restore would bring (dotfiles working tree, wallpapers,
   shell state; rewrite old home paths), check, then log in at the greeter
   with an absolute pointer (usb-tablet) and keyboard over QMP, and check the
   session from SSH (compositor runs as the user, its config-errors command
   is empty, the shell bar runs, autostart ran).
4. Keep the saved `flake.lock` from the run and commit it.

Checks must not match their own command line: `ps -u user -o args= | grep
"[p]attern"`, not `pgrep -f pattern` over SSH.
