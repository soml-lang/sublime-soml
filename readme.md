# SOML for Sublime Text

> [SOML](https://soml.sh) support for [Sublime Text](https://www.sublimetext.com), a config format for humans

> [!NOTE]
> The format is a draft.

*Requires Sublime Text 4213 or later.*

## Install

Install `SOML` with [Package Control](https://packagecontrol.io), or clone this repository into the Sublime Text `Packages` folder as `SOML`. The folder name matters, because the files refer to `Packages/SOML/…`.

## Features

- Highlighting, with errors marked as you type, such as `country: no`, `0xff`, `30m1h`, `2026-02-30T00:00:00Z`, `"\q"`, `[1 2]`, and two members on one line
- Formatting, optionally on save
- The key path of the caret in the status bar
- Trailing whitespace removed on save, except where it is part of a value
- Typing the third quote of `'''` or `"""` closes the block string, and Enter puts its content on its own line
- Top-level keys in *Goto Symbol*, comment toggling, folding, and indentation

The syntax knows whether a key or a value comes next, so `2024-01-01: 'x'`, `404: 'x'`, and `true: 1` have keys, and `[1, 2024-01-01T00:00:00Z]` has an instant.

### Hover

Hover a value to see what it means:

- An instant in your time zone, in UTC, and how far away it is, such as “In 3 weeks”
- A duration, with a day as 24 hours: `90m` is “1 hour 30 minutes” and “5,400 seconds”
- A hexadecimal, octal, or binary int in decimal, and an octal file mode as permissions: `0o644` is “420” and “rw-r--r--”
- A decimal int of five or more digits, grouped: `86400000` is “86,400,000”

It includes [soml-python](https://github.com/soml-lang/soml-python), so nothing else needs to be installed.

## Commands

In the command palette:

- *SOML: Format Document*: Normalize the layout, as the [specification](https://github.com/soml-lang/soml/blob/main/spec.md#formatting) describes, and keep comments, member order, and how each value is written. It also changes CRLF line endings to LF and the encoding to UTF-8 without a BOM. A document that is not valid is left as it is, with the error in the status bar.
- *SOML: Goto Key*: Go to a key at any depth, by its key path.
- *SOML: Copy Key Path*: Copy the key path of each caret, one per line, as [soml-cli](https://github.com/soml-lang/soml-cli) takes it, such as `servers[0].host` or `'the name'.port`.
- *SOML: Toggle Quotes*: Switch a string or a quoted key between `'...'` and `"..."`. A string with a `'`, a line break, or a control character stays `"..."`.
- *SOML: Toggle Block String*: Switch a string between one line and a block string, which goes on the line after its key, as the formatter writes it.
- *SOML: Toggle One Line*: Put an object or an array on one line, as in `ports: [80, 443]`, or on several. Unlike *Join Lines*, it adds the commas that one line needs. A comment or a block string cannot go on one line.
- *SOML: Insert Current Instant in UTC*, and *in Local Time*
- *SOML: Convert to SOML*: In a JSON, JSONC, JSON5, or TOML file, open it as SOML in a new tab, which saves next to the file.
- *SOML: Paste JSON as SOML*: Paste JSON, JSONC, or JSON5. At the start of a line in an object, an object becomes members, in an empty `{}` it takes the place of the `{}`, and elsewhere it becomes a value.
- *SOML: Trim Trailing Whitespace*

### JSON and TOML

- An int stays an int and a float stays a float. A JSON5 hexadecimal number is an int, and `Infinity` becomes `infinity`.
- A TOML date-time with an offset becomes the same instant in UTC, to the microsecond.
- Comments are not kept.
- What SOML cannot hold is not converted or pasted, and the reason is shown in the status bar, such as a duplicate key, an int outside int64, a float that is too large or too small for 64 bits, NaN, a string with a carriage return, or a TOML local date, time, or date-time.

## Settings

*Preferences › Package Settings › SOML › Settings*, or *Preferences: SOML Settings* in the command palette. These are syntax-specific settings, so they can also be set per project.

- `soml_format_on_save` (`false`): Format the document before saving.
- `soml_trim_trailing_white_space_on_save` (`true`): Remove trailing spaces and tabs before saving, except in a block string, where they are part of the value. For the same reason, the built-in `trim_trailing_white_space_on_save` is off.
- `soml_show_key_path` (`true`): Show the key path of the caret in the status bar.
- `soml_show_value_on_hover` (`true`): Explain a value on hover.

The package also sets tabs, LF line endings in new files, and `-` as part of a word, so `content-type` is one word.

## Limitations

- The syntax is not a validator. Use *Format Document*, or `soml check` from [soml-cli](https://github.com/soml-lang/soml-cli). It does not check what needs arithmetic, such as an int outside int64, `1e999`, `1.5ns`, or `0001-01-01T00:00:00+00:01`, which is before the year 1 in UTC. It does not check what needs the whole document either, such as a duplicate key, the nesting limit, or the indentation of a block string.
- The key path, *Goto Key*, and *Toggle One Line* need a valid document. They are also not available in a document with an instant or a duration finer than a microsecond, such as `1ns`, because soml-python holds microseconds.
- Reindenting expects a block string as the formatter writes it: on the line after its key, with its closing delimiter at the indentation of its opening one. A block string that begins on the line of its key, or whose closing delimiter is indented more, can make the lines after it indented wrongly, and so can a block comment over several lines with code after it on its last line, and an object that begins on the line after its key, which the formatter writes when a comment comes after the `:`. Format the document first.
- *Goto Symbol* lists only the top-level keys. Use *Goto Key* for the others.
- Code blocks marked `soml` in Markdown are not highlighted, because a package cannot add a language to the built-in Markdown syntax ([sublimehq/sublime_text#5004](https://github.com/sublimehq/sublime_text/issues/5004)).
- A file with CRLF line endings or a BOM looks valid, because Sublime Text hides both. Format it to fix it.

## Scopes

For theme authors. Every scope ends with `.soml`. The scopes follow the built-in JSON and TOML syntaxes, so color schemes that support those color SOML too.

- **Key:** `meta.mapping.key meta.string string.unquoted`, or `string.quoted.single` or `string.quoted.double` for a quoted key
- **`:`:** `punctuation.separator.key-value`
- **Value of a member:** `meta.mapping.value`
- **String:** `meta.string string.quoted.single`, or `double`
- **Block string:** `meta.string string.quoted.single.block`, or `double`
- **Quotes:** `punctuation.definition.string.begin`, or `end`
- **Escape:** `constant.character.escape`
- **Int:** `meta.number.integer.decimal`, or `hexadecimal`, `octal`, `binary`, with `constant.numeric.base` for the prefix and `constant.numeric.value` for the digits
- **Float:** `meta.number.float.decimal constant.numeric.value`, and `meta.number.float.other constant.numeric.value` for `infinity`
- **`-` of a number or duration:** `keyword.operator.arithmetic`
- **Duration:** `meta.number.duration`, with `constant.numeric.value` for each number and `constant.numeric.suffix` for each unit
- **Instant:** `constant.other.datetime`, with `punctuation.separator.date`, `punctuation.separator.time`, `storage.modifier.timezone`, and more for its parts
- **`true` and `false`:** `constant.language.boolean.true`, or `false`
- **`null`:** `constant.language.null`
- **Comment:** `comment.line.number-sign`, or `comment.block`
- **`{` and `}`:** `meta.mapping punctuation.section.mapping.begin`, or `end`
- **`[` and `]`:** `meta.sequence punctuation.section.sequence.begin`, or `end`
- **`,`:** `punctuation.separator.sequence`
- **Error:** `invalid.illegal.*`

## Development

```sh
npm install
npm test
```

This runs the syntax tests in [`tests`](tests), checks of the commands, and a check of every document in the [conformance suite](https://github.com/soml-lang/soml/tree/main/conformance). It runs Sublime Text on macOS as a second instance in the background, with its own data folder, so it does not take the focus or touch your settings. It expects [soml-javascript](https://github.com/soml-lang/soml-javascript) and [soml](https://github.com/soml-lang/soml) next to this repository.

The [`soml`](soml) folder is a copy of [soml-python](https://github.com/soml-lang/soml-python). To update it, run `cp ../soml-python/src/soml/*.py soml/`.
