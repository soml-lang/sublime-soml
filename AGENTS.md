# Agents

This is a Sublime Text package for [SOML](https://soml.sh). It targets only the latest Sublime Text (build 4215) and its Python 3.14 plugin host. The package name is `SOML`, not the folder name, so resource paths are `Packages/SOML/…`.

## Files

- `SOML.sublime-syntax` is the syntax. Its scopes follow the built-in JSON and TOML syntaxes, so the built-in color schemes color keys. The readme lists the scopes for theme authors.
- `plugin.py` has the commands. `soml/` is [soml-python](https://github.com/soml-lang/soml-python), copied as it is, and the plugin imports it with `from . import soml`. Do not edit `soml/`. Change soml-python and copy it again with `cp ../soml-python/src/soml/*.py soml/`.
- `json5/` reads JSON, JSONC, and JSON5 for *Convert to SOML* and *Paste JSON as SOML*. It passes the [JSON5 test suite](https://github.com/json5/json5-tests), except that a duplicate key is an error, as in SOML.
- `tests/` has the syntax tests, including symbol and reindent tests. `test.js` checks the scope of every token in every valid document of the conformance suite in `../soml` against the reference parser.

## Testing

Run `npm test`. It runs xo, the syntax tests, `scripts/check-plugin.py` (the commands and key bindings, run inside Sublime Text), and `test.js`.

`scripts/st-run` runs the installed Sublime Text as a second, isolated instance, and it must stay that way:

- It must never take the focus. It starts Sublime Text with `--background`. Do not launch Sublime Text with `open`, `subl`, or anything else that activates it, and do not remove `--background`. In `scripts/check-plugin.py`, do not open a real quick panel, input panel, or popup, and do not call `focus_view` or `focus_group`, because they can bring Sublime Text to the front. Replace the API call and call its callbacks, as the Goto Key check does.
- It must never touch the user's own Sublime Text, its data, or its settings. It uses `CFFIXED_USER_HOME` (`HOME` is ignored on macOS), `--multiinstance`, and `sandbox-exec`, and it kills only the process it started. Never kill another Sublime Text process.
- Runs share one isolated data directory, so a run waits for any other run to finish. Do not run it with another copy of the script that does not take the lock.
- Each launch takes a few seconds, so give it many files at once: `scripts/st-run dump SOML.sublime-syntax FILE… --package . --name SOML --merge` prints the scope of every token.

Sublime Text cannot simulate a key press, so `scripts/check-plugin.py` tests a key binding by evaluating its context with the real scopes and running its command. It replaces `sublime.get_clipboard` in the test instance, so it never reads the real clipboard. Keep it that way.

In a syntax test, carets point at columns of the line above, and a tab counts as one column. An assertion line may not contain a tab after the `#`. `tests/syntax_test_soml.soml` was generated once and is now edited by hand, so count the columns carefully.

## Releasing

The version is in the Install section of the readme. To release, change it in a commit whose message is only the version, such as `0.0.2`, and tag that commit with the same version. Package Control uses the tags.
