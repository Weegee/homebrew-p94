# Brewfile: base-devel und Werkzeuge für SteamOS (Tap weegee/p94).
# Installieren mit bin/p94-brew-bootstrap, nicht direkt: gcc braucht vorher
# --skip-post-install und brew pin (siehe README, Toolchain).

# C und C++
brew "gcc"
brew "binutils"
brew "make"
brew "cmake"
brew "ninja"
brew "meson"
brew "pkgconf"
brew "autoconf"
brew "automake"
brew "libtool"

# Weitere Mitglieder von Arch base-devel
brew "bison"
brew "flex"
brew "m4"
brew "gettext"
brew "groff"
brew "texinfo"
brew "gpatch"

# Sprachen
brew "python@3.14"
brew "node@24"
brew "rust"
brew "llvm"

# Prüfwerkzeuge der p94-Projekte
brew "shellcheck"
brew "ruff"
brew "gitleaks"

# Laufzeit der p94-Projekte
brew "rclone"
brew "openjdk"
brew "zip"

# SteamOS-Header für gcc und clang (Tap weegee/p94)
brew "weegee/p94/steamos-sysroot"
# Werkzeuge für SteamOS, die sonst in ~/.local lägen
brew "gh"
brew "neovim"
brew "chezmoi"
brew "diff-so-fancy"
brew "weegee/p94/steamos-tools"
brew "weegee/p94/steamos-pyside"
cask "claude-code@latest"
# Eigene Pakete aus Quellprojekten: brew p94-sync legt ihre Formeln erst nach der Anmeldung bei
# GitHub an, der Bootstrap kennt sie also noch nicht. Sie gehören dazu, sobald sie im Tap stehen.
p94_formulae = HOMEBREW_LIBRARY/"Taps/weegee/homebrew-p94/Formula"
%w[claude-tools steamos-unattended-upgrades gamemode-apps].each do |name|
  brew "weegee/p94/#{name}" if (p94_formulae/"#{name}.rb").exist?
end

# Nicht enthalten, mit Grund:
# - archlinux-keyring, pacman, sudo, debugedit, fakeroot: gehören zu pacman (Entscheidung 2026-11-04).
# - file, findutils, gawk, grep, gnu-sed, gzip, gnu-which, jq, git, curl: im SteamOS-Abbild; eine zweite Kopie
#   verdeckte in interaktiven Shells nur die des Systems.
# - bash-completion@2: das System-Paket 2.18 lädt Homebrews Vervollständigungen schon.
# - pyside, pygobject3: der PySide6-Weg ist noch offen.
