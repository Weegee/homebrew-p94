# Homebrew einrichten und zurückbauen

## Einrichten: `p94-brew-bootstrap`

Das Skript installiert Homebrew nach `/home/linuxbrew/.linuxbrew`, bindet den Tap und die Shell ein und richtet
Toolchain und Brewfile ein. Voraussetzungen: SteamOS 3.9, ein normaler Benutzer (nicht root), `git`, `curl`, `bsdtar`
und `/usr/bin/python3` aus dem Abbild. `sudo` braucht es einmal, um `/home/linuxbrew` anzulegen. Mit
`--tap-from-project` bindet es den Tap aus dem Projektordner ein, etwa zum Prüfen eigener Änderungen.

1. Klone das Projekt und wechsle hinein:

   ```bash
   git clone https://github.com/Weegee/homebrew-p94.git ~/Projects/Linux/homebrew-p94
   cd ~/Projects/Linux/homebrew-p94
   ```

2. Prüfe zuerst mit `bin/p94-brew-bootstrap --dry-run`, was passieren würde.
3. Führe es aus; der erste Lauf dauert zehn bis zwanzig Minuten (Schätzung, vor allem das Brewfile):

   ```bash
   bin/p94-brew-bootstrap
   ```

4. Prüfe das Ergebnis:

   ```bash
   /home/linuxbrew/.linuxbrew/bin/brew --version
   ```

   Erwartet: eine Zeile `Homebrew 7.…`. Ein zweiter Lauf ändert nichts und endet mit
   `✓ Fertig: 0 Schritte geändert, 7 schon erledigt.`

Die Shell-Einbindung legt drei Dateien an (`~/.config/bash/homebrew.bash`, `~/.config/fish/conf.d/homebrew.fish`,
`~/.config/environment.d/60-homebrew.conf`); Homebrew steht **hinten** im `PATH`, Systembefehle behalten Vorrang. Öffne
danach eine neue Shell mit `exec bash -l`.

## Werkzeuge aus `~/.local` umstellen: `p94-brew-migrate`

Es stellt von Hand installierte Werkzeuge auf Homebrew um (gh, Node.js, Neovim, diff-so-fancy, chezmoi, ethtool,
turbostat, vainfo) und setzt eine chezmoi-Quelle voraus. Alte Dateien landen unter `~/.local/state/homebrew-umstieg/`;
`--rollback` stellt sie wieder her. Zeige die Vorschau mit `bin/p94-brew-migrate --dry-run`.

## Rückweg

Prüfe zuerst mit `bin/p94-brew-bootstrap --uninstall --dry-run`, was entfernt würde.

> **Warnung:** `--uninstall` entfernt Homebrew samt aller Formeln und löscht `/home/linuxbrew`, auch Daten unter
> `/home/linuxbrew/.linuxbrew/var`. Sichere sie vorher.

Dann entferne es (es fragt einmal nach, `-y` überspringt die Frage). Der Projektordner bleibt. Der echte Lauf ist nicht
geprüft.

```bash
bin/p94-brew-bootstrap --uninstall
```
