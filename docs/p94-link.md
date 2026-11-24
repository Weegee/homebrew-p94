# Dateien ins Home verlinken: `brew p94-link`

Formeln schreiben nie ins Home. Sie liefern eine Linkliste unter `share/p94-links/FORMEL.links`; `brew p94-link` legt
daraus Verknüpfungen an (Units, Skills, Autostart, Konfiguration) und entfernt veraltete.

## Links anlegen

1. Zeige zuerst, was passieren würde:

   ```bash
   brew p94-link --dry-run
   ```

2. Lege die Links an:

   ```bash
   brew p94-link
   ```

   Erwartet: eine Zeile je Link und zuletzt `✓ 2 Links angelegt, 0 entfernt, 0 Konflikte`.

Rufe den Befehl nach `brew install`, nach einem `brew upgrade` mit geänderter Linkliste und nach `brew uninstall` auf.

Mit `FORMEL` wirkt der Befehl nur auf diese Formel. `--remove` entfernt Links (ohne Namen: alle), `--list` zeigt die
verwalteten Links.

Der Befehl überschreibt nie eine Datei, die er nicht selbst angelegt hat: Bei einem Konflikt endet er mit Exit 1. Den
Zustand speichert er in `~/.local/state/p94-link/state.json`.

## Format der Linkliste

Jede Zeile hat die Form `TYP QUELLE [ZIEL] [OPTION]`, Kommentare beginnen mit `#`:

```text
format 1
unit    lib/systemd/user/p94-hello.service  enable
config  share/p94-hello/hello.conf          p94-hello/hello.conf
```

QUELLE liegt im Keg der Formel (`HOMEBREW_PREFIX/opt/FORMEL`). ZIEL ist relativ zum Zielordner des Typs, ohne `..`.
Die Option `enable` schaltet eine Unit mit `systemctl --user enable` ein.

| TYP | Zielordner | ZIEL |
|---|---|---|
| `unit` | `~/.config/systemd/user` | optional |
| `skill` | `~/.claude/skills` | optional |
| `autostart` | `~/.config/autostart` | optional |
| `fontconfig`, `fish-conf` | `~/.config/fontconfig/conf.d`, `~/.config/fish/conf.d` | optional |
| `applications` | `~/.local/share/applications` | optional |
| `config` | `~/.config` | Pflicht |
| `data` | `~/.local/share` | Pflicht |
