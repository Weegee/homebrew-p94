# homebrew-p94

Homebrew-Tap `weegee/p94` für SteamOS: Formeln, die Befehle `brew p94-link`, `p94-toolchain`, `p94-sync` und die Skripte
`p94-brew-bootstrap`, `p94-brew-migrate`, `p94-formula-try`.

- Code: `lib/p94brew/` (Python), Einstiege in `cmd/` und `bin/`. Prüfen: `make check-basic` (Syntax und Unit-Tests),
  Ausgabeprüfung `tests/hig/check-cli.sh` (braucht ein installiertes Homebrew).
- `Formula/steamos-*.rb` erzeugt `brew p94-sync`, die Formeln der Werkzeuge die CI von Weegee/p94: nie von Hand ändern.
- Docs: README für alle, `docs/` für Nutzer (eine Seite je Befehl), `docs/entwicklung/` für Entwickler. Ein neues
  Feature ändert die Seite seines Befehls im selben Commit.
- p94-hig: Teile Terminal (Hilfe als Form c: `-h` und `--help` kurz, `--help all` ausführlich) und Doku. Vor jeder
  sichtbaren Ausgabe den Skill p94-hig:p94-hig laden; die Budgets prüft `python3 <Skill>/beispiele/abnahme.py .`.
