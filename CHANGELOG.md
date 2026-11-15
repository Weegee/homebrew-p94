# Änderungsprotokoll

## 20261115.01 (2026-11-15)

Erster öffentlicher Stand: Der Tap `weegee/p94` liegt jetzt auf GitHub (`brew tap weegee/p94`).

- **Inkompatibel:** Die Formeln `claude-tools`, `gamemode-apps` und `steamos-unattended-upgrades` laden bereinigte
  Quell-Tarballs aus den Releases von Weegee/p94 statt Git-Tags privater Repositories. Wer sie schon installiert hat,
  aktualisiert mit `brew update && brew upgrade`; vorher brauchte der Abruf einen Zugang zu den privaten Repositories.
- **Inkompatibel:** `brew p94-sync` holt keine Quellprojekte mehr. `p94-sync.toml` enthält keine `[[source]]` mehr, weil
  die CI von Weegee/p94 die Formeln der Werkzeuge nach jedem Release in den Tap schreibt. Der Befehl erzeugt weiter die
  SteamOS-Spiegelformeln. Ein `[[source]]` ohne `url` ist jetzt ein Fehler; vorher galt die Git-Adresse eines privaten
  Repositories mit dem Namen der Quelle als Vorgabe.
- `brew p94-sync` committet im Projektordner, auch wenn `origin` des Taps eine Adresse und kein lokaler Pfad ist (vorher
  ein Fehler). Der Ordner kommt aus der Umgebungsvariable `P94_TAP_PROJEKT`, sonst aus
  `~/Projects/Linux/homebrew-p94`, sofern das ein Git-Repository ist. Fehlt beides, nennt die Fehlermeldung die
  Abhilfe. Das Veröffentlichen mit `git push` bleibt Handarbeit.
- `p94-brew-migrate`: Die Prüfung der gh-Anmeldung ruft `gh auth status` statt `git ls-remote` auf ein privates
  Repository auf. Sie prüft damit weiter, dass das gh von Homebrew angemeldet ist, braucht aber kein privates Repository.
- README neu für den öffentlichen Tap geschrieben; die Formel-Konvention steht jetzt in `docs/formel-konvention.md`.
  Der interne Abnahmebericht `docs/abnahme.md` entfällt.
- Neu: `.github/workflows/test.yml` baut `claude-tools` aus dem Quelltext und führt `brew test` aus (bei Push auf
  `main`, Pull Requests und von Hand).
- Kommentare und Texte nennen keinen bestimmten Rechner mehr, sondern SteamOS; die Beispiel-Repositories der Tests liegen
  unter `example/`.

## 20261104.04 (2026-11-04)

- `brew p94-link`: Aktivierungslinks in `~/.config/systemd/user/*.wants` zeigen jetzt auf den Unit-Link statt auf den
  versionierten Keg. Vorher waren sie nach einem Upgrade mit `brew cleanup` tot, und `systemctl --user is-enabled`
  meldete trotzdem `enabled`. Jeder Aufruf repariert solche Links, für jede verlinkte Unit, auch ohne `enable` in der
  Linkliste.
- Brewfile: gh, neovim, chezmoi, diff-so-fancy, steamos-tools, steamos-pyside und der Cask claude-code@latest gehören
  dazu, claude-tools und steamos-unattended-upgrades, sobald ihre Formeln im Tap stehen. `brew bundle cleanup` würde
  sie so nicht mehr entfernen.
- Tests: Die Wegwerf-Repositories starten kein `git maintenance` mehr im Hintergrund; es schrieb gelegentlich noch in
  `.git`, während der Test den Ordner löschte.

## 20261104.03 (2026-11-04)

- `p94-brew-migrate`: graft landet jetzt im Homebrew-Prefix, auch wenn `~/.npmrc` `prefix=~/.local` setzt. npm läuft mit
  dem node von Homebrew und mit `CXX=c++`, weil Homebrews `make` sonst `g++-11` sucht; graft baut damit nativ statt mit
  `--ignore-scripts`.
- `p94-brew-migrate`: Eine `~/.npmrc`, die nur `prefix=~/.local` enthält, wandert mit dem alten node in die Sicherung.
  Enthält sie mehr, bleibt sie, und eine Warnung nennt die Zeile.
- `p94-brew-migrate`: `~/.claude/settings.json` wird nur angewendet, wenn die graft-Hooks fehlen. Die Hooks hängen nicht
  vom Ort von node ab; lokale Änderungen an der Datei bleiben so erhalten, und ohne Terminal bricht der Lauf nicht mehr an
  der Rückfrage von chezmoi ab.

## 20261104.02 (2026-11-04)

- Paketlisten unter `steamos/` kennen den Schlüssel `root = true`: Pakete ohne Befehle, etwa Python-Module, landen ganz in `libexec/root`.
- Neue Spiegel-Formel steamos-pyside: PySide6 und Shiboken6 aus dem SteamOS-Spiegel für /usr/bin/python3.

## 20261104.01 (2026-11-04)

- Gerüst: Makefile mit `check-basic`, `check`, `check-formulae`; gemeinsame Bibliothek `lib/p94brew`.
- Neuer Befehl bin/p94-brew-bootstrap: installiert Homebrew nach /home/linuxbrew/.linuxbrew und bindet den Tap weegee/p94 ein.
- Shell-Einbindung für bash und fish über chezmoi; Homebrew in environment.d hinten für Units, Plasma und Game Mode.
- Neuer Befehl brew p94-link: verlinkt Units, Skills, Autostart, fontconfig und mehr aus Formeln ins Home.
- Neuer Befehl brew p94-sync: holt Formelvorlagen aus den neuesten Tags der Quellprojekte, prüft und committet sie.
- Spiegel-Formeln steamos-sysroot und steamos-tools, erzeugt aus der SteamOS-Paketdatenbank; Liste erweiterbar.
- Neuer Befehl brew p94-toolchain: macht Homebrews gcc und clang mit den SteamOS-Headern nutzbar und prüft sie nach Updates.
- Brewfile mit base-devel, python@3.14, node@24, rust, llvm und den Prüf- und Laufzeitwerkzeugen der p94-Projekte.
- Der Bootstrap richtet auch Toolchain, Brewfile und die Prüfwerkzeuge von Homebrew ein (neun Schritte).
- Formel-Konvention im README: Vorlage, Quelle, Python, Vervollständigungen, Snippets, Linkliste, Tests.
- Neuer Befehl bin/p94-formula-try: prüft eine Formelvorlage aus einem Quellprojekt in einem Wegwerf-Tap.
- brew p94-link: Das Entfernen der Links einer deinstallierten Formel scheitert nicht mehr an einer Unit, die nicht geladen ist.
- Neuer Befehl bin/p94-brew-migrate: stellt gh, Node.js mit graft, Neovim, diff-so-fancy, chezmoi und die SteamOS-Werkzeuge auf Homebrew um, mit Sicherung und Rückweg.
- Hilfetexte aller Befehle brechen an der Terminalbreite um (`COLUMNS`); `brew p94-toolchain` zeigt als Aufruf `[AKTION] [OPTIONEN]`.
- Neues Prüfskript tests/hig/check-cli.sh: prüft die Ausgabe aller Befehle gegen die Testrezepte von p94-hig (80 Prüfungen).
- Abnahmebericht docs/abnahme.md: Befund je Abnahmekriterium mit Kennzeichnung belegt, abgeleitet oder nicht geprüft.
