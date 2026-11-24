class GamemodeApps < Formula
  desc "Steam-Verknüpfungen für Apps im Game Mode von SteamOS, je Steam-Konto"
  homepage "https://github.com/Weegee/p94"
  url "https://github.com/Weegee/p94/releases/download/src/gamemode-apps-20261124.02.tar.gz"
  sha256 "b25a0f9d84360b573065043e5b70d7dc4dcd4e52aa5e1e48b2d150c3caf1e385"
  license "GPL-3.0-or-later"

  depends_on "make" => :build
  depends_on :linux

  # The scripts keep /usr/bin/python3 from the SteamOS image (project rule): the Game Mode hook must not
  # depend on Homebrew's Python. Deviation from the tap's python@3.14 pattern.
  # RUNTIME_APPSD: apps of other projects link their folder into the prefix (share/gamemode-apps/apps.d/ID),
  # not into this keg, so the sync reads the prefix path, which survives upgrades of either keg.
  def install
    system "make", "install", "PREFIX=#{prefix}", "RUNTIME_BINDIR=#{HOMEBREW_PREFIX}/bin",
           "RUNTIME_DATADIR=#{opt_share}/gamemode-apps",
           "RUNTIME_DOCDIR=#{opt_share}/doc/gamemode-apps",
           "RUNTIME_APPSD=#{HOMEBREW_PREFIX}/share/gamemode-apps/apps.d"
    (share/"p94-links").install "packaging/homebrew/gamemode-apps.links"
  end

  def caveats
    <<~EOS
      Hook vor dem Steam-Start und Stummschalttaste ins Home verlinken:
        brew p94-link gamemode-apps
        systemctl --user start discord-mute-button.service
      Der nächste Steam-Start im Game Mode legt die Verknüpfungen an. YouTube und die Web-Dienste brauchen
      im Desktop-Modus:
        flatpak install --system flathub rocks.shy.VacuumTube com.google.Chrome
      Umzug von ~/.local/share/discord-gamemode: #{opt_share}/doc/gamemode-apps/docs/entwicklung/migration.md
    EOS
  end

  test do
    assert_match "gamemode-apps-sync (gamemode-apps) #{version}",
                 shell_output("#{bin}/gamemode-apps-sync --version")
    assert_match "Aufruf:", shell_output("#{bin}/gamemode-apps-sync --help")
    assert_equal "13699167424669024256\n",
                 shell_output("#{bin}/gamemode-apps-sync --gameid discord")
    assert_path_exists share/"p94-links/gamemode-apps.links"
  end
end
