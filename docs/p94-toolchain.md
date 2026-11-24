# Compiler einrichten: `brew p94-toolchain`

SteamOS bringt weder Compiler noch C-Header mit. Die Toolchain besteht aus Homebrews `gcc`, der Formel
`steamos-sysroot` (Header aus den SteamOS-Paketen) und diesem Befehl, der specs-Datei, crt-Links und clang-Konfiguration
schreibt. `p94-brew-bootstrap` erledigt das in Schritt 6; von Hand geht es so:

1. Installiere gcc und hefte es an, damit `brew upgrade` es nicht ohne diese Einrichtung ersetzt:

   ```bash
   brew install --skip-post-install gcc
   brew pin gcc
   ```

2. Installiere das Sysroot. Homebrew lehnt Quell-Installationen ab, solange `bin/clang` fehlt; lege dafür einen Link
   an und entferne ihn danach (ersetze `16` durch die Hauptversion von gcc):

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

`setup` endet mit einer Prüfung; bei `✗` steht der Befehl zur Abhilfe darunter.
Erwartet: lauter `✓` und zuletzt `✓ Toolchain bereit`.

## Nach einem SteamOS-Update

Prüfe die Header mit `brew p94-toolchain check`. Passen sie nicht mehr, nennt die Prüfung den Befehl zum Erneuern
(`brew p94-sync`). Aktualisiere gcc mit `brew p94-toolchain gcc-upgrade` statt mit `brew upgrade gcc`; `--dry-run`
zeigt vorher die Schritte. `gcc-upgrade` ist nur im Trockenlauf und mit Attrappen geprüft, nicht an einem echten
gcc-Wechsel.

clang baut C-Programme; C++ mit `clang++` ist nicht geprüft (libstdc++-Header fehlen, Stand 2026-11-04).
