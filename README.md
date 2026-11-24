# homebrew-p94

homebrew-p94 ist ein Homebrew-Tap für SteamOS: Er liefert eigene CLI-Werkzeuge (zum Beispiel `claude-tools`) und eine
Build-Toolchain (gcc und clang mit den SteamOS-Headern), damit Homebrew auf dem schreibgeschützten System als
Paketverwaltung taugt. Für SteamOS 3.9 mit Homebrew in `/home/linuxbrew/.linuxbrew`. Der Code entstand mit
Unterstützung von KI (Claude von Anthropic).

## Installation

Voraussetzung: Homebrew ist installiert. Wenn nicht, richtet es [`p94-brew-bootstrap`](docs/homebrew-einrichten.md) ein.

1. Binde den Tap ein:

   ```bash
   brew tap weegee/p94
   ```

2. Installiere ein Werkzeug, zum Beispiel `claude-tools`:

   ```bash
   brew install weegee/p94/claude-tools
   ```

3. Prüfe mit `claude-brain --version`, dass es läuft; erwartet ist eine Zeile `claude-brain JJJJMMTT.NN`.

Formeln schreiben nie ins Home; sie nennen in den Hinweisen den Befehl `brew p94-link FORMEL`.

| Formel | Inhalt |
|---|---|
| `claude-tools` | Befehle für Claude Code: Modellwahl, Audits, Recherche und Wissensabgleich |
| `gamemode-apps` | Steam-Verknüpfungen für Apps im Game Mode von SteamOS, je Steam-Konto |
| `steamos-unattended-upgrades` | automatische Updates für SteamOS, Homebrew und Flatpak mit Status-Anzeige |
| `steamos-sysroot` | C- und Kernel-Header aus den SteamOS-Paketen, damit gcc und clang bauen können |
| `steamos-tools`, `steamos-pyside` | Programme und Python-Module aus dem SteamOS-Paketspiegel |

## Befehle

Jeder Befehl zeigt mit `--help` eine Übersicht und mit `--help all` alle Einzelheiten.

| Befehl | Wirkung | Seite |
|---|---|---|
| `brew p94-link` | verlinkt Dateien aus Formeln ins Home | [docs/p94-link.md](docs/p94-link.md) |
| `brew p94-toolchain` | richtet gcc und clang für SteamOS ein und prüft sie | [docs/p94-toolchain.md](docs/p94-toolchain.md) |
| `brew p94-sync` | erzeugt die SteamOS-Spiegelformeln aus `steamos/` | [docs/p94-sync.md](docs/p94-sync.md) |
| `p94-brew-bootstrap` | richtet Homebrew samt Tap und Shell ein, baut es zurück | [docs/homebrew-einrichten.md](docs/homebrew-einrichten.md) |
| `p94-brew-migrate` | stellt Werkzeuge aus `~/.local` auf Homebrew um | [docs/homebrew-einrichten.md](docs/homebrew-einrichten.md) |
| `p94-formula-try` | prüft die Formelvorlage eines Projekts | [docs/entwicklung/formel-konvention.md](docs/entwicklung/formel-konvention.md) |

## Weiterlesen

- [Änderungen je Version](CHANGELOG.md)
- Fehler und Wünsche: https://github.com/Weegee/p94/issues
- Lizenz: GPL-3.0-or-later, siehe [LICENSE](LICENSE)
