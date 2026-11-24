class SteamosUnattendedUpgrades < Formula
  desc "Automatische Updates für SteamOS, Homebrew und Flatpak mit Status-Anzeige"
  homepage "https://github.com/Weegee/p94"
  url "https://github.com/Weegee/p94/releases/download/src/steamos-unattended-upgrades-20261124.02.tar.gz"
  sha256 "54dceacb896f88817346a250cfbb1c8dd598bb2b4bf5d96e8226be04a3849e57"
  license "GPL-3.0-or-later"

  depends_on "make" => :build
  depends_on :linux
  depends_on "weegee/p94/steamos-pyside"

  def install
    system "make", "install", "PREFIX=#{prefix}", "RUNTIME_BINDIR=#{opt_bin}", "BREW_PREFIX=#{HOMEBREW_PREFIX}"
    (share/"p94-links").install "packaging/homebrew/steamos-unattended-upgrades.links"
  end

  def caveats
    <<~EOS
      Units, Autostart, Startmenü-Eintrag und Symbole ins Home verlinken:
        brew p94-link steamos-unattended-upgrades
      Den Systemteil für SteamOS und systemweite Flatpaks einmal einrichten:
        sudo #{HOMEBREW_PREFIX}/bin/suu setup
      Nach einem Upgrade meldet suu, wenn der Systemteil veraltet ist; dann setup erneut ausführen.
      Die Steam-Verknüpfung für den Game Mode legt gamemode-apps an (ab 20261109.06). Installiere es zuerst:
        brew install weegee/p94/gamemode-apps
      Ist eine ältere Fassung installiert, aktualisiere sie mit brew upgrade gamemode-apps. Meldet Homebrew
      danach einen Konflikt an bin/suu-gamemode, verknüpfe neu:
        brew link steamos-unattended-upgrades
    EOS
  end

  test do
    assert_match "suu #{version}", shell_output("#{bin}/suu --version")
    assert_match "Befehle:", shell_output("#{bin}/suu --help")
    assert_match "suu-gui (suu) #{version}", shell_output("#{bin}/suu-gui --version")
    assert_path_exists share/"suu/system"
  end
end
