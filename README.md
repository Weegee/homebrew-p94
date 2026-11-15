# homebrew-p94

homebrew-p94 ist ein Homebrew-Tap für SteamOS: Er liefert eigene CLI-Werkzeuge (zum Beispiel `claude-tools`) und eine
Build-Toolchain (gcc und clang mit den SteamOS-Headern), damit Homebrew auf dem schreibgeschützten System als
Paketverwaltung taugt.

Für SteamOS 3.9 mit Homebrew in `/home/linuxbrew/.linuxbrew`. Der Code entstand mit Unterstützung von KI (Claude von
Anthropic).

## Installation

Voraussetzung: Homebrew ist installiert. Wenn nicht, richtet [`bin/p94-brew-bootstrap`](#homebrew-einrichten) es ein.

1. Binde den Tap ein:

   ```bash
   brew tap weegee/p94
   ```

2. Installiere ein Werkzeug, zum Beispiel `claude-tools`:

   ```bash
   brew install weegee/p94/claude-tools
   ```

3. Prüfe, dass es läuft:

   ```bash
   claude-brain --version
   ```

   Erwartet: eine Zeile `claude-brain JJJJMMTT.NN`.

Die Formeln laden die bereinigten Quelltexte aus den Releases von Weegee/p94. Formeln, die Dateien ins Home legen
würden, tun das nie selbst; sie nennen in den Hinweisen den Befehl `brew p94-link FORMEL`.

| Formel | Inhalt |
|---|---|
| `claude-tools` | Befehle für Claude Code: Modellwahl, Audits, Recherche und Wissensabgleich |
| `gamemode-apps` | Steam-Verknüpfungen für Apps im Game Mode von SteamOS, je Steam-Konto |
| `steamos-unattended-upgrades` | automatische Updates für SteamOS, Homebrew und Flatpak mit Status-Anzeige |
| `steamos-sysroot` | C- und Kernel-Header aus den SteamOS-Paketen, damit gcc und clang bauen können |
| `steamos-tools`, `steamos-pyside` | Programme und Python-Module aus dem SteamOS-Paketspiegel ohne eigene Homebrew-Formel |

## Nutzung

Der Tap bringt drei Befehle für `brew` mit.

### Dateien ins Home verlinken: `brew p94-link`

Formeln schreiben nie ins Home. Eine Formel liefert stattdessen eine Linkliste unter `share/p94-links/FORMEL.links`;
`brew p94-link` legt daraus Verknüpfungen an (Units, Skills, Autostart, Konfiguration) und entfernt veraltete.

1. Zeige zuerst, was passieren würde:

   ```bash
   brew p94-link --dry-run
   ```

2. Lege die Links an:

   ```bash
   brew p94-link
   ```

   ```text
   ✓ verlinkt  ~/.config/systemd/user/p94-hello.service → /home/linuxbrew/.linuxbrew/opt/p94-hello/lib/systemd/user/p94-hello.service
   ✓ verlinkt  ~/.config/p94-hello/hello.conf → /home/linuxbrew/.linuxbrew/opt/p94-hello/share/p94-hello/hello.conf
   ✓ 2 Links angelegt, 0 entfernt, 0 Konflikte; systemctl --user daemon-reload ausgeführt
   ```

Rufe den Befehl nach `brew install`, nach einem `brew upgrade`, bei dem sich die Linkliste ändert, und nach
`brew uninstall` auf. Die Links zeigen auf `HOMEBREW_PREFIX/opt/FORMEL`; ein Upgrade braucht deshalb keinen neuen Link.

| Aufruf | Wirkung |
|---|---|
| `brew p94-link` | alle Linklisten anwenden |
| `brew p94-link FORMEL` | die Linkliste dieser Formel anwenden |
| `brew p94-link --dry-run` | Links und `systemctl`-Aufrufe zeigen, nichts ändern |
| `brew p94-link --remove [FORMEL]` | die Links der Formel entfernen (ohne Namen: alle) |
| `brew p94-link --list` | die verwalteten Links zeigen |

Der Befehl überschreibt nie eine Datei, die er nicht selbst angelegt hat: Liegt am Ziel etwas anderes, meldet er einen
Konflikt und endet mit Exit 1. Den Zustand speichert er in `~/.local/state/p94-link/state.json`. Units mit der Option
`enable` schaltet er mit `systemctl --user enable` ein und biegt die Aktivierungslinks auf den Unit-Link um, damit sie
ein `brew cleanup` nach einem Upgrade überstehen.

Format der Linkliste (`format 1`, Kommentare mit `#`); jede Zeile hat die Form `TYP QUELLE [ZIEL] [OPTION]`:

```text
format 1
unit    lib/systemd/user/p94-hello.service  enable
config  share/p94-hello/hello.conf          p94-hello/hello.conf
```

QUELLE ist relativ zu `HOMEBREW_PREFIX/opt/FORMEL` und muss im Keg der Formel liegen. ZIEL ist relativ zum Zielordner
des Typs, nicht absolut, ohne `..` und ohne führenden Punkt.

| TYP | Zielordner | ZIEL | Option |
|---|---|---|---|
| `unit` | `~/.config/systemd/user` | optional | `enable` |
| `skill` | `~/.claude/skills` | optional | keine |
| `autostart` | `~/.config/autostart` | optional | keine |
| `fontconfig` | `~/.config/fontconfig/conf.d` | optional | keine |
| `fish-conf` | `~/.config/fish/conf.d` | optional | keine |
| `applications` | `~/.local/share/applications` | optional | keine |
| `config` | `~/.config` | Pflicht | keine |
| `data` | `~/.local/share` | Pflicht | keine |

### Compiler einrichten: `brew p94-toolchain`

SteamOS bringt weder einen Compiler noch C-Header mit. Die Toolchain besteht aus drei Teilen:

- `gcc`: Homebrews Compiler. Er wird mit `--skip-post-install` installiert, weil seine Einrichtung `/usr/bin/cc`
  verlangt, und angeheftet, damit `brew upgrade` ihn nicht ohne diese Einrichtung ersetzt.
- `steamos-sysroot`: die C- und Kernel-Header aus den SteamOS-Paketen sowie die Links `cc`, `gcc`, `c++`, `g++` und
  `cpp` in `bin/`.
- `brew p94-toolchain`: schreibt die specs-Datei von gcc, die crt-Links und die clang-Konfiguration und prüft alles.

Der Bootstrap erledigt das in Schritt 6. Von Hand richtest du die Toolchain so ein:

1. Installiere gcc und hefte es an:

   ```bash
   brew install --skip-post-install gcc
   brew pin gcc
   ```

2. Installiere das Sysroot. Homebrew lehnt Quell-Installationen ab, solange `bin/gcc` und `bin/clang` fehlen; das
   Sysroot liefert `bin/gcc` erst selbst. Lege deshalb für diesen einen Aufruf einen Link an und entferne ihn danach
   (ersetze `16` durch die Hauptversion von gcc):

   ```bash
   ln -s ../opt/gcc/bin/gcc-16 /home/linuxbrew/.linuxbrew/bin/clang
   brew install weegee/p94/steamos-sysroot
   rm /home/linuxbrew/.linuxbrew/bin/clang
   ```

3. Installiere clang und richte alles ein:

   ```bash
   brew install llvm
   brew p94-toolchain setup
   ```

`brew p94-toolchain setup` endet mit einer Prüfung. Jede Zeile beginnt mit `✓` oder `✗`; bei `✗` steht der Befehl zur
Abhilfe darunter.

```text
✓ gcc 16 installiert (/home/linuxbrew/.linuxbrew/opt/gcc/bin/gcc-16)
✓ gcc angeheftet
✓ steamos-sysroot 20261023.100 installiert
✓ Header passen zum System (glibc 2.43+r37+gfdf10644d6ee-1, linux-api-headers 7.1-1)
✓ Probe: C mit cc
✓ Toolchain bereit
```

Nach jedem SteamOS-Update prüfst du die Header mit `brew p94-toolchain check`. Passen sie nicht mehr zu den Paketen im
System, nennt die Prüfung den Befehl zum Erneuern (`brew p94-sync`). gcc aktualisierst du mit
`brew p94-toolchain gcc-upgrade` statt mit `brew upgrade gcc`: der Befehl löst die Anheftung, installiert mit
`--skip-post-install`, richtet neu ein und heftet wieder an. `--dry-run` zeigt vorher die Schritte. Der Befehl ist nur im
Trockenlauf und mit Attrappen geprüft (nicht geprüft an einem echten gcc-Wechsel).

clang baut C-Programme. C++ mit `clang++` ist nicht Teil der Prüfung: die Header von libstdc++ finden sich dort noch
nicht (Stand 2026-11-04, nicht weiter untersucht).

### SteamOS-Spiegelformeln erzeugen: `brew p94-sync`

Die Formeln `steamos-sysroot`, `steamos-tools` und `steamos-pyside` sind erzeugt: Sie laden Pakete vom SteamOS-Spiegel
(Homebrew prüft die Prüfsumme aus der Paketdatenbank des Abbilds) und entpacken sie im Keg. Ändere die Liste unter
`steamos/`, nie die Formel. `brew p94-sync` erzeugt die Formeln aus den Listen, prüft sie mit `brew style` und
`brew audit` und committet sie im Projektordner des Taps.

Die Formeln der Werkzeuge (`claude-tools` und andere) schreibt die CI von Weegee/p94 nach jedem Release in den Tap;
`brew p94-sync` braucht dafür keine Quellen mehr.

So ergänzt du ein Programm aus dem SteamOS-Spiegel, hier mit `NAME` für das Paket und `BEFEHL` für das Programm:

1. Klone den Tap als Projektordner. `brew p94-sync` committet dort; der Tap-Klon von Homebrew wäre dafür ungeeignet,
   weil `brew update` ihn zurücksetzt:

   ```bash
   git clone https://github.com/Weegee/homebrew-p94.git ~/Projects/Linux/homebrew-p94
   ```

   Liegt der Projektordner woanders, setze `P94_TAP_PROJEKT` auf seinen Pfad.
2. Finde den Paketnamen in der Paketdatenbank des Abbilds:

   ```bash
   bsdtar -tf /usr/lib/holo/pacmandb/sync/extra-3.9.db | grep '^NAME-'
   ```

3. Füge am Ende von `steamos/steamos-tools.toml` einen Eintrag ein. `test` ist optional und nennt einen Aufruf, der ohne
   root und ohne Bildschirm mit Exit 0 endet. Pakete ohne Programm, etwa Python-Module, bekommen `root = true` statt
   `bin`.

   ```toml
   [[package]]
   name = "NAME"
   bin = ["BEFEHL"]
   test = ["BEFEHL", "--version"]
   ```

4. Zeige, was sich ändern würde, und erzeuge dann die Formel:

   ```bash
   brew p94-sync --dry-run
   brew p94-sync --steamos-only
   ```

5. Installiere oder aktualisiere sie und prüfe, dass der Befehl da ist:

   ```bash
   brew install weegee/p94/steamos-tools
   command -v BEFEHL
   ```

Das Veröffentlichen bleibt Handarbeit: `brew p94-sync` committet nur im Projektordner, `git push` machst du selbst.
Quellen ohne Tag, ohne Vorlage oder ohne Zugriff meldet der Befehl als `übersprungen`; Exit 1 gibt es bei einem Fehler,
etwa wenn `brew style` oder `brew audit` Befunde meldet. Braucht ein Paket eine Bibliothek, die weder im Abbild noch in
der Liste steht, bricht der Befehl ab und nennt das fehlende Paket. Läuft gerade ein SteamOS-Update und die Version in
der Paketdatenbank weicht vom Abbild ab, meldet der Befehl den Konflikt; schließe das Update ab und starte neu.

## Konfiguration

| Datei oder Variable | Wirkung |
|---|---|
| `p94-sync.toml` | `[steamos] lists`: die Paketlisten für die Spiegelformeln; optional `[[source]]` mit `name` und `url` für Quellprojekte mit Formelvorlagen in `packaging/homebrew/` |
| `Brewfile` | base-devel, Sprachen, Prüf- und Laufzeitwerkzeuge; Installation mit `brew bundle install --no-upgrade --file Brewfile` |
| `P94_TAP_PROJEKT` | Projektordner, in den `brew p94-sync` committet (Vorgabe: `~/Projects/Linux/homebrew-p94`, wenn es ein Git-Repository ist) |
| `P94_BREW_PREFIX` | Homebrew-Prefix (Vorgabe: `/home/linuxbrew/.linuxbrew`) |

### Homebrew einrichten

`bin/p94-brew-bootstrap` installiert Homebrew nach `/home/linuxbrew/.linuxbrew`, bindet den Tap und die Shell ein und
richtet Toolchain und Brewfile ein. Voraussetzungen: SteamOS 3.9, ein normaler Benutzer (nicht root), `git`, `curl`,
`bsdtar` und `/usr/bin/python3` aus dem Abbild. `sudo` braucht der Bootstrap einmal, um `/home/linuxbrew` anzulegen. Er
bindet Homebrew über die chezmoi-Quelle (`~/.local/share/chezmoi`) ein und lässt `~/.bash_profile` unverändert.

1. Klone das Projekt und wechsle hinein:

   ```bash
   git clone https://github.com/Weegee/homebrew-p94.git ~/Projects/Linux/homebrew-p94
   cd ~/Projects/Linux/homebrew-p94
   ```

2. Prüfe zuerst, was passieren würde:

   ```bash
   bin/p94-brew-bootstrap --dry-run
   ```

3. Führe den Bootstrap aus:

   ```bash
   bin/p94-brew-bootstrap
   ```

   Er arbeitet neun Schritte ab; jeder prüft zuerst, ob er schon erledigt ist: Voraussetzungen, Verzeichnis anlegen,
   Homebrew installieren (Commit und Prüfsumme von `install.sh` sind festgelegt), Tap einbinden, Shell-Einbindung für
   bash und fish, Toolchain, Brewfile, Prüfwerkzeuge von Homebrew (`brew style`, `audit`, `test`) und zuletzt
   `brew doctor` mit `brew p94-toolchain check`. Der erste Lauf dauert je nach Netz zehn bis zwanzig Minuten
   (Schätzung, nicht gemessen), vor allem das Brewfile (llvm, rust und openjdk sind groß).
4. Prüfe das Ergebnis:

   ```bash
   /home/linuxbrew/.linuxbrew/bin/brew --version
   ```

   Erwartet: eine Zeile `Homebrew 7.…`.

Ein zweiter Lauf ändert nichts und endet mit `✓ Fertig: 0 Schritte geändert, 7 schon erledigt.`

Die Shell-Einbindung legt drei Dateien an: `~/.config/bash/homebrew.bash` und `~/.config/fish/conf.d/homebrew.fish`
(interaktive Shells: `brew shellenv`, Vervollständigungen, Snippets aus Formeln) und
`~/.config/environment.d/60-homebrew.conf` (hängt Homebrew **hinten** an den `PATH` von Units, Plasma und Game Mode,
sodass Systembefehle wie `python3` Vorrang behalten). Prüfe sie mit `tests/shell/test-shell.sh` und öffne danach eine
neue Shell mit `exec bash -l`.

### Werkzeuge aus `~/.local` umstellen

`bin/p94-brew-migrate` stellt von Hand installierte Werkzeuge in `~/.local` auf Homebrew um: gh, Node.js mit graft,
Neovim, diff-so-fancy, chezmoi und die SteamOS-Werkzeuge (ethtool, turbostat, vainfo). Er setzt eine chezmoi-Quelle voraus,
deren Vorlagen er anpasst. Der Lauf verschiebt alte Dateien in eine Sicherung unter
`~/.local/state/homebrew-umstieg/`, löscht nichts, und `--rollback` stellt sie wieder her. Zeige die Vorschau mit:

```bash
bin/p94-brew-migrate --dry-run
```

## Weitere Dokumentation

- [docs/formel-konvention.md](docs/formel-konvention.md): wie ein Quellprojekt seine Formel mitbringt, mit der
  Prüfung per `bin/p94-formula-try`.
- [CHANGELOG.md](CHANGELOG.md): Änderungen je Version.

## Rückweg

Prüfe zuerst, was entfernt würde:

```bash
bin/p94-brew-bootstrap --uninstall --dry-run
```

> **Warnung:** `--uninstall` entfernt Homebrew samt aller Formeln und löscht `/home/linuxbrew`, auch Daten unter
> `/home/linuxbrew/.linuxbrew/var` und Formeln, die nicht aus dem Brewfile stammen. Sichere solche Daten vorher.
> Danach fehlen alle Werkzeuge aus Homebrew; mit `bin/p94-brew-bootstrap` richtest du sie wieder ein.

Dann entferne es. Der echte Lauf von `--uninstall` ist nicht geprüft.

```bash
bin/p94-brew-bootstrap --uninstall
```

Der Bootstrap fragt vorher einmal nach (`-y` überspringt die Frage). Er entfernt die verwalteten Links, das Vertrauen
für den Tap, Homebrew samt aller Formeln und seinen Zustand unter `~/.local/state/p94-link` und `~/.cache/p94-sync`.
Der geklonte Projektordner bleibt erhalten.

## Fehlerberichte

Fehler und Wünsche meldest du unter https://github.com/Weegee/p94/issues.

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE).
