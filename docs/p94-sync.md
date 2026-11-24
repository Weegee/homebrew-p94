# SteamOS-Spiegelformeln erzeugen: `brew p94-sync`

Die Formeln `steamos-sysroot`, `steamos-tools` und `steamos-pyside` sind erzeugt: Sie laden Pakete vom SteamOS-Spiegel
und entpacken sie im Keg. Ändere die Liste unter `steamos/`, nie die Formel. `brew p94-sync` erzeugt die Formeln aus
den Listen, prüft sie mit `brew style` und `brew audit` und committet sie im Projektordner des Taps. Die Formeln der
Werkzeuge (`claude-tools` und andere) schreibt die CI von Weegee/p94 nach jedem Release.

## Ein Programm aus dem SteamOS-Spiegel ergänzen

1. Klone den Tap als Projektordner. `brew p94-sync` committet dort; der Tap-Klon von Homebrew taugt dafür nicht, weil
   `brew update` ihn zurücksetzt. Liegt er woanders, setze `P94_TAP_PROJEKT`:

   ```bash
   git clone https://github.com/Weegee/homebrew-p94.git ~/Projects/Linux/homebrew-p94
   ```

2. Finde den Paketnamen (`NAME`) in der Paketdatenbank des Abbilds:

   ```bash
   bsdtar -tf /usr/lib/holo/pacmandb/sync/extra-3.9.db | grep '^NAME-'
   ```

3. Füge am Ende von `steamos/steamos-tools.toml` einen Eintrag ein. `test` ist optional: ein Aufruf, der ohne root und
   Bildschirm mit Exit 0 endet. Pakete ohne Programm, etwa Python-Module, bekommen `root = true` statt `bin`.

   ```toml
   [[package]]
   name = "NAME"
   bin = ["BEFEHL"]
   test = ["BEFEHL", "--version"]
   ```

4. Zeige die Änderung und erzeuge dann die Formel:

   ```bash
   brew p94-sync --dry-run
   brew p94-sync --steamos-only
   ```

5. Installiere sie und prüfe, dass der Befehl da ist:

   ```bash
   brew install weegee/p94/steamos-tools
   command -v BEFEHL
   ```

`git push` machst du selbst. Exit 1 gibt es bei einem Fehler, etwa wenn `brew style` oder `brew audit` Befunde melden.
Fehlt eine Bibliothek im Abbild und in der Liste, bricht der Befehl ab und nennt sie. Läuft ein SteamOS-Update, schließe
es ab und starte neu.
