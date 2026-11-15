# Homebrew for interactive fish (homebrew-p94), a conf.d snippet.
# Managed by chezmoi; source of truth: ~/Projects/Linux/homebrew-p94/shell/homebrew.fish
status is-interactive; or return
set -l prefix /home/linuxbrew/.linuxbrew
test -x $prefix/bin/brew; or return

# Order after this block: ~/.local/bin, Homebrew bin, sbin, node@24, rest.
if test -d $prefix/opt/node@24/bin
    fish_add_path --global --move --path $prefix/opt/node@24/bin
end
$prefix/bin/brew shellenv fish | source
fish_add_path --global --move --path $HOME/.local/bin

# Completions and functions from formulae, right after the user's own directories.
function __p94_insert_after --argument-names var anchor
    set -l add $argv[3..-1]
    set -l new
    set -l inserted 0
    for p in $$var
        set -a new $p
        if test $inserted = 0; and test "$p" = "$anchor"
            set -a new $add
            set inserted 1
        end
    end
    test $inserted = 1; or set new $add $new
    set -g $var $new
end
set -l comp
for d in $prefix/share/fish/vendor_completions.d $prefix/share/fish/completions
    test -d $d; and not contains -- $d $fish_complete_path; and set -a comp $d
end
set -q comp[1]; and __p94_insert_after fish_complete_path $__fish_config_dir/completions $comp
set -l func $prefix/share/fish/vendor_functions.d
if test -d $func; and not contains -- $func $fish_function_path
    __p94_insert_after fish_function_path $__fish_config_dir/functions $func
end
functions -e __p94_insert_after
for f in $prefix/share/fish/vendor_conf.d/*.fish
    source $f
end
