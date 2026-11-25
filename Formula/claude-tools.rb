class ClaudeTools < Formula
  include Language::Python::Shebang

  desc "Befehle für Claude Code: Modellwahl, Audits, Recherche und Wissensabgleich"
  homepage "https://github.com/Weegee/p94"
  # Vorlage: Die CI des Taps Weegee/homebrew-p94 trägt url und sha256 der Veröffentlichung ein.
  url "https://github.com/Weegee/p94/releases/download/src/claude-tools-20261125.01.tar.gz"
  sha256 "385b70a21703bbd9e3c5433338ddc4bdb0185cd6c128fbe33e27944d35a716c7"
  license "GPL-3.0-or-later"

  depends_on "make" => :build
  depends_on "python@3.14"

  def install
    python = formula_opt_bin("python@3.14")/"python3.14"
    system "make", "install", "PREFIX=#{prefix}", "PYTHON=#{python}",
           "RUNTIME_BINDIR=#{opt_bin}", "RUNTIME_PKGLIBDIR=#{opt_lib}/claude-tools"
    rewrite_shebang detected_python_shebang, bin/"claude-brain", bin/"claude-sdk", bin/"claude-jobs", bin/"claude-post-ui", bin/"claude-post-gui"
    (share/"p94-links").install "packaging/homebrew/claude-tools.links"
  end

  def caveats
    <<~EOS
      Units von claude-brain ins Home verlinken und einmalig einrichten:
        brew p94-link claude-tools
        claude-brain setup
      Claude Code selbst installiert diese Formel nicht (nativer Installer von Anthropic).
      Den Skill claude-research liefert die Formel als Plugin p94-research in einer Verzeichnis-Marketplace:
        claude plugin marketplace add #{HOMEBREW_PREFIX}/share/claude-tools
        claude plugin install p94-research@claude-tools
      chezmoi trägt beides in settings.json ein. Eine Kopie des Skills ohne Plugin liegt unter:
        #{HOMEBREW_PREFIX}/share/claude-tools/skills/claude-research
    EOS
  end

  test do
    assert_equal "claude-brain #{version}\n", shell_output("#{bin}/claude-brain --version")
    assert_equal "claude-audit #{version}\n", shell_output("#{bin}/claude-audit --version")
    assert_match "ExecStart=#{opt_bin}/claude-brain sync --quiet",
                 (lib/"systemd/user/claude-brain.service").read
    assert_match "#!#{formula_opt_bin("python@3.14")}/python3.14", (bin/"claude-brain").read.lines.first
    (testpath/"bin/claude").write "#!/bin/sh\nprintf '%s\\n' \"$@\"\n"
    chmod 0755, testpath/"bin/claude"
    with_env(PATH: "#{testpath}/bin:#{ENV.fetch("PATH")}") do
      assert_equal "--model\nopus\n--effort\nhigh\n-p\nProbe\n", shell_output("#{bin}/claude-opus -p Probe")
    end
    market = share/"claude-tools"
    plugin = market/"plugins/p94-research"
    assert_match "\"version\": \"#{version}\"", (plugin/".claude-plugin/plugin.json").read
    assert_match "\"source\": \"./plugins/p94-research\"", (market/".claude-plugin/marketplace.json").read
    assert_equal (plugin/"skills/claude-research/SKILL.md").read, (market/"skills/claude-research/SKILL.md").read
    completion = share/"bash-completion/completions/claude-plan"
    assert_match "complete -F _claude_tools claude-plan",
                 shell_output("bash --norc -c 'source #{completion}; complete -p claude-plan'")
    snippet = share/"p94/bash.d/claude-tools.bash"
    system "bash", "-n", snippet
    # Outside an interactive shell the snippet does nothing (tests/test_tools.py checks the hook).
    assert_equal "", shell_output("bash --norc -c 'source #{snippet}; declare -F __claude_brain_after_session'", 1)
  end
end
