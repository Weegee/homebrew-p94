# Formel-Konvention

Diese Seite beschreibt, wie ein Quellprojekt seine Homebrew-Formel mitbringt, damit sie in den Tap
`weegee/p94` gelangt. Sie ist eine Referenz für die Projekte; als durchgehendes Beispiel dient die Testformel
`p94-hello` (`tests/fixtures/p94-hello`).

## Ort und Name

Die Formelvorlage liegt im Quellprojekt unter `packaging/homebrew/FORMEL.rb`. FORMEL ist der Name der Formel in
Kleinbuchstaben mit Bindestrichen, zum Beispiel `p94-hello`. Ein Projekt darf mehrere Vorlagen enthalten; der Tap
bekommt für jede eine Formel. Die Dateien `Formula/steamos-*.rb` erzeugt `brew p94-sync`, die Formeln der Werkzeuge
schreibt die CI von Weegee/p94; ändere beide nie von Hand.

## Vorlage

Die Vorlage von `p94-hello` zeigt alle Teile der Konvention:

```ruby
class P94Hello < Formula
  desc "Testformel von homebrew-p94: Python-Skript mit Unit und Vervollständigungen"
  homepage "https://github.com/example/p94-hello"
  url "https://github.com/example/p94-hello.git",
      tag:      "v00000000.00",
      revision: "0000000000000000000000000000000000000000"
  license "GPL-3.0-or-later"

  depends_on "make" => :build
  depends_on "python@3.14"

  def install
    python = formula_opt_bin("python@3.14")/"python3.14"
    system "make", "install", "PREFIX=#{prefix}", "PYTHON=#{python}", "RUNTIME_BINDIR=#{opt_bin}"
    (share/"p94-links").install "packaging/homebrew/p94-hello.links"
  end

  def caveats
    <<~EOS
      Unit und Konfiguration ins Home verlinken:
        brew p94-link p94-hello
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/p94-hello --version")
    assert_equal "p94-hello unit ok\n", shell_output("#{bin}/p94-hello --unit")
  end
end
```

- `class P94Hello < Formula`: der Klassenname folgt dem Dateinamen (`p94-hello` wird `P94Hello`).
- `desc`: ein Satz ohne Artikel am Anfang und ohne Punkt am Ende; `brew audit` prüft das.
- `url` mit `tag:` und `revision:`: Platzhalter. Die Werkzeuge in diesem Tap tragen stattdessen die Adresse eines
  Quell-Tarballs und seine Prüfsumme ein (siehe Quelle).
- `license`: SPDX-Kennung der Lizenz des Projekts.
- `depends_on "make" => :build`: der Bau braucht `make`; das SteamOS-Abbild hat keins.
- `depends_on "python@3.14"`: die Laufzeit des Skripts (siehe Python-Muster).
- `def install`: ruft `make install` des Projekts mit `PREFIX=#{prefix}`; die Linkliste kommt nach `share/p94-links`.
- `caveats`: nennt den Befehl `brew p94-link FORMEL`, weil Formeln nie ins Home schreiben.
- `test do`: prüft Version und eine Funktionsprobe ohne Netz.

## Quelle

Für die Werkzeuge in diesem Tap steht in der Vorlage ein Platzhalter. Die CI von Weegee/p94 baut nach jedem Release
einen bereinigten Quell-Tarball, lädt ihn ins Release `src` von Weegee/p94 und schreibt `url`, `sha256` und `homepage`
der Formel in diesen Tap. Die Formel lädt also einen Tarball unter
`https://github.com/Weegee/p94/releases/download/src/NAME-VERSION.tar.gz`, kein Git-Repository.

Für Projekte, die `brew p94-sync` über `[[source]]` in `p94-sync.toml` aus Git-Tags holt, gilt: Die Vorlage enthält
`tag: "v00000000.00"` und `revision:` mit 40 Nullen; der Befehl trägt Tag und Commit des neuesten Tags
`vJJJJMMTT.NN` ein. Bei `https`-URLs steht nie `using: :git`: `brew audit` meldet es als überflüssig. Nur lokale Pfade
bekommen es, damit Homebrew sie als Git-Repository liest.

## Bau

Der Bau läuft über `make install PREFIX=#{prefix}` und kennt `DESTDIR`, damit der Arch-Weg (`makepkg`) unverändert
bleibt. Laufzeitpfade, die in installierte Dateien geschrieben werden (Units, Desktop-Dateien, Skripte), zeigen auf
`opt_bin`, `opt_prefix` oder `HOMEBREW_PREFIX`, nie auf den Cellar: dessen Pfad enthält die Version und bricht beim
nächsten Upgrade. Im Makefile steht dafür eine Variable wie `RUNTIME_BINDIR ?= $(BINDIR)`; die Formel übergibt
`RUNTIME_BINDIR=#{opt_bin}`.

## Python-Muster

Skripte laufen mit dem Python von Homebrew, nicht mit `/usr/bin/python3`:

1. Die Formel hat `depends_on "python@3.14"`.
2. Das Makefile hat `PYTHON ?= /usr/bin/python3` und ersetzt damit die Shebang-Zeile
   (`sed -i '1s|^#!.*|#!$(PYTHON)|' ...`); das Arch-Paket behält `/usr/bin/python3`.
3. Die Formel übergibt `PYTHON=#{formula_opt_bin("python@3.14")}/python3.14`. `formula_opt_bin` statt
   `Formula["python@3.14"].opt_bin`, weil `brew style` die lange Form beanstandet (Homebrew 7.0).

Ohne Makefile-Variable geht es auch mit `include Language::Python::Shebang` und
`rewrite_shebang detected_python_shebang, *bin.children`.

## Vervollständigungen

- bash: nach `share/bash-completion/completions/BEFEHL` installieren. `bash_completion.install` schreibt nach
  `etc/bash_completion.d`; die Shell-Einbindung lädt zwar beide Orte, der erste lädt aber erst bei Bedarf und kostet
  den Start der Shell nichts.
- fish: nach `share/fish/vendor_completions.d/BEFEHL.fish` installieren.

## Snippets

Hooks, Aliase und Funktionen für interaktive Shells liegen in `share/p94/bash.d/FORMEL.bash` (bash) und
`share/fish/vendor_conf.d/FORMEL.fish` (fish). Die Dateien geben nichts aus und definieren Funktionen, Aliase und
Hooks. Der bash-Ort `share/p94/bash.d` liegt nicht unter `etc`, weil Homebrew dort bei Upgrades Standarddateien
(`.default`) anlegt und Änderungen daran sich mit Versionen mischen.

## Linkliste

Dateien im Home legt `brew p94-link` an, nie die Formel. Das Projekt liefert dafür `packaging/homebrew/FORMEL.links`,
die Formel installiert sie nach `share/p94-links/FORMEL.links`, und der Arch-Weg bleibt dadurch gleich. Das Format steht
im README unter [Dateien ins Home verlinken](../README.md#dateien-ins-home-verlinken-brew-p94-link):

```text
format 1
unit    lib/systemd/user/p94-hello.service
config  share/p94-hello/hello.conf  p94-hello/hello.conf
```

Nach der Installation verlinkst du mit `brew p94-link FORMEL`; die `caveats` der Formel nennen den Befehl.

## Units

Units liegen im Keg unter `lib/systemd/user`. `ExecStart` zeigt über den opt-Pfad auf das Programm, damit die Unit ein
Upgrade überlebt. Eingeschaltet wird sie über die Option `enable` in der Linkliste (`unit  PFAD  enable`). Die Formel
verwendet kein `service do`: damit würde `brew services` eigene Units in `~/.config/systemd/user` anlegen, ein zweiter
Weg neben `brew p94-link`.

## Dateien in etc meiden

Dateien unter `etc` ändern sich mit Versionen und erzeugen `.default`-Kopien. Konfiguration im Home legt das
Setup-Kommando des Werkzeugs an; die Formel liefert höchstens eine Vorlage unter `share/FORMEL/`, die `brew p94-link`
als `config` verlinkt.

## Laufzeit aus dem SteamOS-Spiegel

Braucht ein Werkzeug Bibliotheken oder Programme, die es als Pakete im SteamOS-Spiegel gibt, aber nicht als Formel,
nimmst du das Paket in eine Liste unter `steamos/` auf (siehe README, Abschnitt
[SteamOS-Spiegelformeln erzeugen](../README.md#steamos-spiegelformeln-erzeugen-brew-p94-sync)). Die Formel des
Werkzeugs bekommt dann `depends_on "weegee/p94/steamos-tools"` oder den Namen der neuen Liste. Pakete ohne Programm,
etwa Python-Module, stehen mit `root = true` in der Liste; die Formel entpackt sie nach `libexec/root`, und wer sie
nutzt, liest sie von `$(brew --prefix)/opt/FORMEL/libexec/root`. Ein Beispiel ist `steamos-pyside`.

## Tests

`test do` prüft `--version` und eine Funktionsprobe, ohne Netz und ohne Zugangsdaten. Die Probe läuft in einem
Wegwerf-Ordner; sie schreibt nichts ins Home und startet keine Dienste.

## Vorlage prüfen

`bin/p94-formula-try` prüft die Vorlagen eines Projekts, auch ohne Tag. Es legt den Wegwerf-Tap `p94try/try` an, setzt
die Quelle auf den lokalen Commit und führt `brew style`, `brew audit`, `brew install --build-from-source`,
`brew test` und `brew p94-link --dry-run` aus. Danach räumt es auf.

1. Wechsle in dein Projekt und committe die Vorlage (geprüft wird der Commit, nicht der Arbeitsordner).
2. Führe die Prüfung aus; ersetze `PROJEKT` durch den Ordner des Projekts:

   ```bash
   bin/p94-formula-try ~/Projects/Linux/PROJEKT
   ```

   ```text
   Prüfe 1 Formel aus ~/Projects/Linux/PROJEKT (Commit 68952a8)
   p94-hello: brew style ...
   ✓ p94-hello: brew style
   p94-hello: brew audit ...
   ✓ p94-hello: brew audit
   p94-hello: brew install --build-from-source ...
   ✓ p94-hello: brew install --build-from-source
   p94-hello: brew test ...
   ✓ p94-hello: brew test
   p94-hello: brew p94-link --dry-run ...
   ✓ p94-hello: brew p94-link --dry-run
   ✓ Alle Prüfungen bestanden
   ```

Mit `--rev REV` prüfst du einen anderen Commit, mit `--keep` bleiben Tap und Formel für eigene Versuche stehen
(`brew untap p94try/try` räumt sie ab).
