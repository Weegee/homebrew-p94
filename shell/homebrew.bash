# Homebrew for interactive bash (homebrew-p94), loaded from ~/.config/bash/bashrc.
# Managed by chezmoi; source of truth: ~/Projects/Linux/homebrew-p94/shell/homebrew.bash
[[ $- == *i* ]] || return 0
[[ -x /home/linuxbrew/.linuxbrew/bin/brew ]] || return 0

_p94_path_remove() { # $1: directory to drop from PATH
    local p=":$PATH:"
    while [[ $p == *":$1:"* ]]; do p=${p//":$1:"/:}; done
    p=${p#:}
    PATH=${p%:}
}
# environment.d appends Homebrew at the end; move it to the front for interactive use.
_p94_path_remove /home/linuxbrew/.linuxbrew/bin
_p94_path_remove /home/linuxbrew/.linuxbrew/sbin
_p94_path_remove /home/linuxbrew/.linuxbrew/opt/node@24/bin
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv bash)"
# node@24 is keg-only: keep it right behind Homebrew's bin and sbin.
if [[ -d $HOMEBREW_PREFIX/opt/node@24/bin ]]; then
    PATH="$HOMEBREW_PREFIX/bin:$HOMEBREW_PREFIX/sbin:$HOMEBREW_PREFIX/opt/node@24/bin${PATH#"$HOMEBREW_PREFIX/bin:$HOMEBREW_PREFIX/sbin"}"
fi
# ~/.local/bin stays first: own scripts, and old installs until the migration.
_p94_path_remove "$HOME/.local/bin"
PATH="$HOME/.local/bin:$PATH"
unset -f _p94_path_remove

# share/bash-completion/completions is loaded on demand by the system's bash-completion;
# etc/bash_completion.d (Homebrew's bash_completion directory) is not, so load it here.
# shellcheck disable=SC1090
for _p94_f in "$HOMEBREW_PREFIX"/etc/bash_completion.d/*; do
    [[ -r $_p94_f ]] && source "$_p94_f"
done
# Snippets from formulae (hooks, aliases): the bash counterpart of fish vendor_conf.d.
# shellcheck disable=SC1090
for _p94_f in "$HOMEBREW_PREFIX"/share/p94/bash.d/*.bash; do
    [[ -r $_p94_f ]] && source "$_p94_f"
done
unset _p94_f
