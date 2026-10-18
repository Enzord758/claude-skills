# Pitfalls: symptom → cause → fix

| Symptom | Cause | Fix |
|---|---|---|
| `nixos-install`: NAR hash mismatch in `path:/tmp/cfg` | the lock file was written in the middle of evaluating the flake | `nix flake lock` as its own step before disko/install |
| Copying the flake as root: "dubious ownership" | the repo belongs to the user | `git -c safe.directory=<repo> archive HEAD` (and run other git as the user) |
| Greeter fails: script "No such file" under the shell package | the stable channel's greeter module expects the old package layout; the package came from unstable | take that module from unstable with the package (`disabledModules` + import) |
| "Refusing to evaluate package 'electron-N' … insecure" | an app (e.g. Logseq) pins an EOL Electron | `nixpkgs.config.permittedInsecurePackages = [ "electron-N.x.y" ]`, by exact version, with a comment |
| "Refusing to evaluate … not available on" for a CUDA tool (gpu-burn) | it needs `cudaSupport` for the whole package set | leave it out, or a separate nixpkgs instance with cudaSupport just for it (big local builds) |
| A browser from a community flake "missing" | its binary is named after the channel (`zen-beta`) | check the flake's package for `binaryName`/`mainProgram` |
| Compositor fails in the VM, fine on hardware | GPU env vars (`GBM_BACKEND=nvidia-drm`, …) with no such GPU | an option that the test variant turns off |
| Hyprland warns ".conf format … removed in 0.57" | a hyprlang config handed to a newer Hyprland (e.g. greeter `customConfig`) | write it in Lua (`hl.*`); dms-greeter detects Lua by its `hl.` calls even without a .lua suffix |
| Login test types the password but nothing happens | focus isn't on a field (user dropdown); or the greeter's keymap differs from the US qcodes sent | click with an absolute pointer (`-device usb-tablet`, QMP `input-send-event`), map characters for the keymap (Danish `-` is US `slash`) |
| Every check fails with "Connection refused" after a run | the systemd unit that ran the test ended and took the daemonized QEMU with it | boot and check in the same unit, or `systemd-run --scope` |
| A process check passes falsely | `pgrep -f` matched the SSH `sh -c` command line itself | `ps -o args= \| grep "[x]yz"` |
| Second NIC on the real LAN gets no DHCP lease | NixOS' strict reverse-path filter drops replies on the non-default interface; on some hosts macvtap doesn't deliver frames either | `networking.firewall.checkReversePath = "loose"` in the test variant; test LAN-dependent things (NFS exports by hostname) on real hardware |
| Restored desktop looks default (no wallpaper/theme) | the wallpaper choice and themes live outside the tracked dotfiles (state dir, git-ignored theme folders) and old absolute paths | back up the state dir; restore the dotfiles working tree, not just HEAD; rewrite the old home path in the shell's state |
| Old backups don't restore after a home rename | the backup tree has the old home path | restore from whichever home path the backup has, into the new one |
| `sops -d` with the host key: "identity did not match any of the recipients" | the recipient is the `age1…` conversion, but the SSH key was given as an SSH identity (`SOPS_AGE_SSH_PRIVATE_KEY_FILE`) | convert the private key too (`ssh-to-age -private-key -i key`) and use `SOPS_AGE_KEY_FILE`; sops-nix's `sshKeyPaths` does the conversion itself |
| A key piped on stdin to `sops` is "malformed" for the second recipient | `/dev/stdin` can be read once; sops tries several identities | put it in a tmpfs file with umask 077 and shred it after |
| A Rust app from source can't find its assets in the store | it looks for `/usr/share/<app>` or walks up from the binary | read its path code; install assets where it looks (e.g. `$out/assets`) |
| A vendor's "latest" download holds an old version | the convenience link isn't maintained | find the versioned URL the vendor's own updater or the AUR package uses |
| Renaming the home breaks old agent/Claude sessions | they recorded the old working directory | keep a compatibility symlink at the old path |
