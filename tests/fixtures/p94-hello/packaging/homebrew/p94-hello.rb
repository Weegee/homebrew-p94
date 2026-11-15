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
