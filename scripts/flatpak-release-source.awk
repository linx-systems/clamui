# Replace exactly one local checkout source in a Flatpak manifest with a pinned
# Git source. The caller supplies URL and commit with -v; input and output are
# YAML so comments and unrelated source records retain their original form.

function indentation(line,    width) {
    width = 0
    while (substr(line, width + 1, 1) == " ") {
        width++
    }
    return width
}

function spaces(width,    text) {
    text = ""
    while (width > 0) {
        text = text " "
        width--
    }
    return text
}

function blank_or_comment(line) {
    return line ~ /^[[:space:]]*$/ || line ~ /^[[:space:]]*#/
}

function is_sources_key(line) {
    return line ~ /^[ ]*sources:[[:space:]]*(#.*)?$/
}

function is_source_entry(line, entry_indent,    rest) {
    if (indentation(line) != entry_indent) {
        return 0
    }
    rest = substr(line, entry_indent + 1)
    return rest ~ /^-[[:space:]]+/
}

# Match a direct source-mapping key. The first key shares the list item's line;
# later keys are indented two spaces below it. Nested mappings and lists cannot
# match either position.
function source_key_is(line, entry_indent, key, value,    line_indent, rest) {
    line_indent = indentation(line)
    if (line_indent == entry_indent) {
        rest = substr(line, entry_indent + 1)
        if (rest !~ /^-[[:space:]]+/) {
            return 0
        }
        sub(/^-[[:space:]]+/, "", rest)
    } else if (line_indent == entry_indent + 2) {
        rest = substr(line, entry_indent + 3)
    } else {
        return 0
    }

    return rest ~ ("^" key ":[[:space:]]*" value "([[:space:]]*(#.*)?)$")
}

function inspect_source_line(line) {
    if (source_key_is(line, source_entry_indent, "type", "dir")) {
        source_is_dir = 1
    }
    if (source_key_is(line, source_entry_indent, "path", "[.][.]")) {
        source_has_parent_path = 1
    }
}

function finish_source_entry() {
    if (source_entry_start != 0 && source_is_dir && source_has_parent_path) {
        replacement_count++
        if (replacement_count == 1) {
            replacement_start = source_entry_start
            replacement_end = source_entry_end
            replacement_indent = source_entry_indent
        }
    }

    source_entry_start = 0
    source_entry_end = 0
    source_is_dir = 0
    source_has_parent_path = 0
}

{
    lines[NR] = $0

    if (in_sources) {
        line_indent = indentation($0)
        if (!blank_or_comment($0) && line_indent <= sources_indent) {
            finish_source_entry()
            in_sources = 0
        } else if (is_source_entry($0, source_entry_indent)) {
            finish_source_entry()
            source_entry_start = NR
            source_entry_end = NR
            inspect_source_line($0)
        } else if (source_entry_start != 0) {
            if (!blank_or_comment($0) && line_indent > source_entry_indent) {
                source_entry_end = NR
            }
            inspect_source_line($0)
        }
    }

    if (!in_sources && is_sources_key($0)) {
        in_sources = 1
        sources_indent = indentation($0)
        source_entry_indent = sources_indent + 2
    }
}

END {
    if (in_sources) {
        finish_source_entry()
    }

    if (replacement_count != 1) {
        if (replacement_count == 0) {
            print "flatpak release source: expected exactly one local dir source with path: .., found none" > "/dev/stderr"
        } else {
            print "flatpak release source: expected exactly one local dir source with path: .., found " replacement_count > "/dev/stderr"
        }
        exit 1
    }

    for (line_number = 1; line_number <= NR; line_number++) {
        if (line_number == replacement_start) {
            print spaces(replacement_indent) "- type: git"
            print spaces(replacement_indent + 2) "url: " url
            print spaces(replacement_indent + 2) "commit: \"" commit "\""
            line_number = replacement_end
        } else {
            print lines[line_number]
        }
    }
}
