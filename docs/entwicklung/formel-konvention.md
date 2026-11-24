# Formel-Konvention

So bringt ein Quellprojekt seine Homebrew-Formel mit, damit sie in den Tap `weegee/p94` gelangt. Das Beispiel ist die
Testformel `p94-hello` (`tests/fixtures/p94-hello`).

## Ort, Name und Quelle

Die Vorlage liegt im Quellprojekt unter `packaging/homebrew/FORMEL.rb`; FORMEL ist der Name in Kleinbuchstaben mit
Bindestrichen. Ein Projekt darf mehrere Vorlagen enthalten. `Formula/steamos-*.rb` erzeugt `brew p94-sync`, die
Formeln der Werkzeuge schreibt die CI von Weegee/p94: ändere beide nie von Hand.

In der Vorlage stehen `tag: "v00000000.00"` und `revision:` mit 40 Nullen als Platzhalter. Nach jedem Release baut die
CI einen bereinigten Quell-Tarball, lädt ihn ins Release `src` von Weegee/p94 und trägt `url`, `sha256` und `homepage`
in den Tap ein. `using: :git` steht bei `https`-URLs nie (`brew audit` beanstandet es).

## Vorlage

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
  end
end
```

`desc` ist ein Satz ohne Artikel am Anfang und ohne Punkt am Ende; `make` fehlt im SteamOS-Abbild. `test do` prüft
`--version` und eine Funktionsprobe ohne Netz, Dateien im Home und Dienste.

## Regeln

- **Bau:** `make install PREFIX=#{prefix}` mit `DESTDIR`-Unterstützung, damit `makepkg` unverändert bleibt.
  Laufzeitpfade in installierten Dateien zeigen auf `opt_bin`, `opt_prefix` oder `HOMEBREW_PREFIX`, nie auf den
  Cellar (der Pfad enthält die Version). Im Makefile steht dafür etwa `RUNTIME_BINDIR ?= $(BINDIR)`.
- **Python:** Skripte laufen mit Homebrews Python. Das Makefile hat `PYTHON ?= /usr/bin/python3` und ersetzt damit die
  Shebang-Zeile; die Formel übergibt `PYTHON=#{formula_opt_bin("python@3.14")}/python3.14` (`brew style` beanstandet
  `Formula[...].opt_bin`).
- **Vervollständigungen:** bash nach `share/bash-completion/completions/BEFEHL`, fish nach
  `share/fish/vendor_completions.d/BEFEHL.fish`.
- **Snippets** für interaktive Shells: `share/p94/bash.d/FORMEL.bash`, `share/fish/vendor_conf.d/FORMEL.fish`; sie
  geben nichts aus.
- **Home:** Dateien im Home legt `brew p94-link` an, nie die Formel. Das Projekt liefert
  `packaging/homebrew/FORMEL.links` (Format: [docs/p94-link.md](../p94-link.md)), die Formel installiert sie nach
  `share/p94-links/`. Konfiguration im Home legt das Setup-Kommando des Werkzeugs an; die Formel liefert höchstens eine
  Vorlage unter `share/FORMEL/`; nichts unter `etc` (Homebrew legt dort `.default`-Kopien an).
- **Units** liegen unter `lib/systemd/user`; `ExecStart` zeigt über den opt-Pfad auf das Programm. Eingeschaltet wird
  mit `enable` in der Linkliste. Kein `service do`: es legte einen zweiten Weg neben `brew p94-link` an.
- **Laufzeit aus dem SteamOS-Spiegel:** Pakete, die es nur dort gibt, kommen in eine Liste unter `steamos/`
  ([docs/p94-sync.md](../p94-sync.md)); die Formel bekommt `depends_on "weegee/p94/steamos-tools"`. Pakete ohne
  Programm (`root = true`) liegen unter `libexec/root`, Beispiel `steamos-pyside`.

## Vorlage prüfen

`bin/p94-formula-try` prüft die Vorlagen eines Projekts, auch ohne Tag: Es legt den Wegwerf-Tap `p94try/try` an, setzt
die Quelle auf den lokalen Commit, führt `brew style`, `brew audit`, `brew install --build-from-source`, `brew test`
und `brew p94-link --dry-run` aus und räumt auf. Committe die Vorlage zuerst (geprüft wird der Commit).

```bash
bin/p94-formula-try ~/Projects/Linux/PROJEKT
```

Mit `--rev REV` prüfst du einen anderen Commit, mit `--keep` bleibt der Tap stehen (`brew untap p94try/try` räumt ab).
