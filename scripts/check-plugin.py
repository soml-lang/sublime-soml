"""
Checks the commands and key bindings of the package inside Sublime Text. Run it with `scripts/st-run script . scripts/check-plugin.py --name SOML`.

Sublime Text cannot simulate a key press, so a key binding is checked by evaluating its context with the real scopes and running its command.
"""

import datetime
import json
import os
import re
import sys
import tempfile
import time

import sublime

soml = sys.modules['SOML.soml']

failures = []
count = 0

# With `--background`, Sublime Text may start without a window.
if sublime.active_window() is None:
	sublime.run_command('new_window')

window = sublime.active_window()
directory = tempfile.mkdtemp()


def check(name, actual, expected):
	global count
	count += 1
	if actual != expected:
		failures.append(f'{name}:\n  expected {expected!r}\n  actual   {actual!r}')


def new_view(text):
	view = window.new_file(syntax='Packages/SOML/SOML.sublime-syntax')
	view.settings().set('auto_indent', False)
	view.run_command('append', {'characters': text})
	return view


def text_of(view):
	return view.substr(sublime.Region(0, view.size()))


def with_caret(view):
	"""The text with `|` at the caret."""
	caret = view.sel()[0].b
	text = text_of(view)
	return text[:caret] + '|' + text[caret:]


def view_with_caret(document):
	"""A view of the document, with the caret where the `|` is."""
	view = new_view(document.replace('|', ''))
	view.sel().clear()
	view.sel().add(sublime.Region(document.index('|')))
	return view


###[ FORMAT ]##################################################################

view = view_with_caret("pool: {min: 2,   max: 16,} # c\nname:   'x'\not|her: 1\nlast:    2\n")
view.run_command('soml_format')
check('format', with_caret(view), "pool: {min: 2, max: 16} # c\nname: 'x'\not|her: 1\nlast: 2\n")
view.run_command('undo')
check('format is one undo step', text_of(view), "pool: {min: 2,   max: 16,} # c\nname:   'x'\nother: 1\nlast:    2\n")



def formatted_with_caret(document):
	view = view_with_caret(document)
	view.run_command('soml_format')
	return with_caret(view)


# A caret on a line that changes keeps its place among the characters around it.
check('format keeps the caret after removed spaces', formatted_with_caret('pool: {min: 2,|   max: 16,}\n'), 'pool: {min: 2,| max: 16}\n')
check('format keeps the caret before removed spaces', formatted_with_caret('a:|   1\n'), 'a:| 1\n')
check('format keeps the caret after a removed comma', formatted_with_caret('a: [\n1,|\n2]\n'), 'a: [\n\t1|\n\t2\n]\n')
check('format keeps the caret when the lines around it change', formatted_with_caret('a:   1|\nb:    [1,2]\nc:  3\n'), 'a: 1|\nb: [1, 2]\nc: 3\n')
for repeated_value in ("'x,y'", "'x y'"):
	document = f"a: [\n  {repeated_value}\n\n\n  'x|y'\n  {repeated_value}\n\n\n  {repeated_value}\n  {repeated_value}\n\n]\n"
	formatted = f"a: [\n\t{repeated_value}\n\n\t'x|y'\n\t{repeated_value}\n\n\t{repeated_value}\n\t{repeated_value}\n]\n"
	check(f'format keeps the caret in a unique array item among repeated {repeated_value} lines', formatted_with_caret(document), formatted)
check('format keeps the caret after repeated blank lines', formatted_with_caret("a: [\n\t'x,y',\n\n\n\t'x,y',\n\n\t'x,y'\n\n\n\t'x|y'\n\n\t'x,y'\n\n\n\t'x,y',\n\n\t'x,y',\n\n]\n"), "a: [\n\t'x,y'\n\n\t'x,y'\n\n\t'x,y'\n\n\t'x|y'\n\n\t'x,y'\n\n\t'x,y'\n\n\t'x,y'\n]\n")
check('format keeps the caret with several repeated blank lines', formatted_with_caret("a: [\n\t'x,y'\n\n\n\t'x,y',\n\n\n  'x,y',\n\n\n\t'x|y',\n\n\n  'x,y'\n\n]\n"), "a: [\n\t'x,y'\n\n\t'x,y'\n\n\t'x,y'\n\n\t'x|y'\n\n\t'x,y'\n]\n")
long_document = 'a: {\n' + ''.join(f'    key{index}:   {index},\n' + ('\n\n' if index == 10 else '') for index in range(300)) + '}\n'
long_formatted = soml.format(long_document)
check('format keeps the caret after blank lines that go in a long document', formatted_with_caret(long_document.replace('key250', 'key2|50')), long_formatted.replace('key250', 'key2|50'))
check('format keeps the caret in an indented line', formatted_with_caret('a: {\n        b|: 1\n}\n'), 'a: {\n\tb|: 1\n}\n')
check('format keeps the caret at the end of a joined line', formatted_with_caret('a: 1   |\n\n\n\nb: 2\n'), 'a: 1|\n\nb: 2\n')
two_carets = view_with_caret('a:   1|\nb:    2\n')
two_carets.sel().add(sublime.Region(0))
two_carets.sel().add(sublime.Region(13))
two_carets.run_command('soml_format')
check('format keeps every caret', [region.b for region in two_carets.sel()], [0, 4, 8])
selection_view = new_view('a:   [1]\nb:    2\nc: 3\n')
selection_view.sel().clear()
selection_view.sel().add(sublime.Region(9, 16))
selection_view.run_command('soml_format')
check('format keeps a selection on its text', selection_view.substr(selection_view.sel()[0]), 'b: 2')
view = view_with_caret('a: {\n' + ''.join(f'        k{index}:   {index}\n' for index in range(2000)) + '}|\n')
view.run_command('soml_format')
check('format a long document', with_caret(view), 'a: {\n' + ''.join(f'\tk{index}: {index}\n' for index in range(2000)) + '}|\n')

view = new_view('a: 1\na: 2\n')
view.run_command('soml_format')
check('format leaves an invalid document', text_of(view), 'a: 1\na: 2\n')

view = new_view("name:   'café 😀'\ndescription:\n\t'''\n\tx  \n\t'''\n")
view.run_command('soml_format')
check('format keeps Unicode and block strings', text_of(view), "name: 'café 😀'\ndescription:\n\t'''\n\tx  \n\t'''\n")

view = new_view("a:   1\nb:\n\t'''\n\tx\ty\n\t'''\n")
view.settings().set('translate_tabs_to_spaces', True)
view.run_command('soml_format')
check('format keeps a tab in a block string with translate_tabs_to_spaces', text_of(view), "a: 1\nb:\n\t'''\n\tx\ty\n\t'''\n")
check('format leaves translate_tabs_to_spaces as it was', view.settings().get('translate_tabs_to_spaces'), True)

# A command does not leave the setting on a view that inherits it, so the view still follows the settings of the syntax. Changed in memory only.
view = new_view('a:   1\n')
view.run_command('soml_format')
syntax_settings = sublime.load_settings('SOML.sublime-settings')
syntax_settings.set('translate_tabs_to_spaces', True)
try:
	check('format leaves an inherited translate_tabs_to_spaces inherited', view.settings().get('translate_tabs_to_spaces'), True)
finally:
	syntax_settings.erase('translate_tabs_to_spaces')

###[ PASTE JSON AS SOML ]######################################################

# Replaced in this process only, so the real clipboard is never used.
clipboard = ''
sublime.get_clipboard = lambda *arguments: clipboard


def set_clipboard(text):
	global clipboard
	clipboard = text


sublime.set_clipboard = set_clipboard


def paste(document, json_text):
	global clipboard
	clipboard = json_text
	view = view_with_caret(document)
	view.run_command('soml_paste_json')
	return text_of(view)


check('paste members', paste('|', '{"a": 1.0, "b": 1, "c": {"d": [1, "x\\ny"]}, "e e": null}'), 'a: 1.0\nb: 1\nc: {\n\td: [\n\t\t1\n\t\t"x\\ny"\n\t]\n}\n\'e e\': null')
check('paste after a key', paste('key: |\n', '{"a": 1}'), 'key: {\n\ta: 1\n}\n')
check('paste indented', paste('pool: {\n\t|\n}\n', '{"min": 2, "max": {"x": 1}}'), 'pool: {\n\tmin: 2\n\tmax: {\n\t\tx: 1\n\t}\n}\n')
check('paste a string', paste('key: |\n', '"hello"'), "key: 'hello'\n")


def pasted_selection(document, json_text, selections=()):
	"""The selection after pasting, as `(a, b)` pairs, with a caret at the `|` and the other selections."""
	global clipboard
	clipboard = json_text
	view = view_with_caret(document)
	for a, b in selections:
		view.sel().add(sublime.Region(a, b))

	view.run_command('soml_paste_json')
	return [(region.a, region.b) for region in view.sel()]


# The caret goes after the pasted text, as with the built-in paste, so typing does not replace it.


def paste_with_spaces(document, json_text):
	global clipboard
	clipboard = json_text
	view = view_with_caret(document)
	view.settings().set('translate_tabs_to_spaces', True)
	view.settings().set('tab_size', 2)
	view.run_command('soml_paste_json')
	return text_of(view)


check('paste members indented with spaces', paste_with_spaces('o: {\n  |\n}\n', '{"a": {"b": [1]}}'), 'o: {\n  a: {\n    b: [\n      1\n    ]\n  }\n}\n')
check('paste a value indented with spaces', paste_with_spaces('o: {\n  k: |\n}\n', '[1, "x\\ty"]'), 'o: {\n  k: [\n    1\n    "x\\ty"\n  ]\n}\n')
check('paste puts the caret after a value', pasted_selection('key: |\n', '{"a": 1}'), [(14, 14)])
check('paste puts the caret after members', pasted_selection('|', '{"a": 1, "b": 2}'), [(9, 9)])
check('paste puts the caret after a value that replaces a selection', pasted_selection('key: |1\n', '2', [(5, 6)]), [(6, 6)])
check('paste keeps a selection where nothing is pasted', pasted_selection('|a: 1\nb: 2\n', '{}', [(0, 4)]), [(0, 4)])


def paste_with_two_carets(document, point, json_text):
	global clipboard
	clipboard = json_text
	view = view_with_caret(document)
	view.sel().add(sublime.Region(point))
	view.run_command('soml_paste_json')
	return with_caret(view)


def pasted_with_caret(document, json_text):
	global clipboard
	clipboard = json_text
	view = view_with_caret(document)
	view.run_command('soml_paste_json')
	return with_caret(view)


check('paste in empty braces puts the caret after them', pasted_with_caret('a: {|}\n', '{"x": 1}'), 'a: {\n\tx: 1\n}|\n')
check('paste in empty braces with spaces puts the caret after them', pasted_with_caret('a: { | } # c\n', '{"x": 1}'), 'a: {\n\tx: 1\n}| # c\n')
check('paste with two carets in one pair of empty braces', paste_with_two_carets('a: { | }\n', 6, '{"x": 1}'), 'a: {\n\tx: 1\n}|\n')
check('paste puts every caret after its value', pasted_selection('a: |\nb: \n', '1', [(7, 7)]), [(4, 4), (9, 9)])
check('paste an array', paste('key: |\n', '[1, 2]'), 'key: [\n\t1\n\t2\n]\n')
check('paste before text', paste('|a: 1\n', '{"x": 1, "y": 2}'), 'x: 1\ny: 2\na: 1\n')
check('paste before indented text', paste('k: {\n\t|a: 1\n}\n', '{"x": 1}'), 'k: {\n\tx: 1\n\ta: 1\n}\n')
check('paste an object in an array', paste('k: [\n\t|\n]\n', '{"x": 1}'), 'k: [\n\t{\n\t\tx: 1\n\t}\n]\n')
check('paste an object in an object in an array', paste('k: [{\n\t|\n}]\n', '{"x": 1}'), 'k: [{\n\tx: 1\n}]\n')
check('paste an object in empty braces', paste('deps: {|}\n', '{"x": 1}'), 'deps: {\n\tx: 1\n}\n')
check('paste an object in empty braces with spaces', paste('\tdeps: { | }\n', '{"x": 1, "y": [2]}'), '\tdeps: {\n\t\tx: 1\n\t\ty: [\n\t\t\t2\n\t\t]\n\t}\n')
check('paste an object in empty braces in an array', paste('a: [{|}, 2]\n', '{"x": 1}'), 'a: [{\n\tx: 1\n}, 2]\n')
check('paste an object in the empty braces of a document', paste('{|}\n', '{"x": 1}'), '{\n\tx: 1\n}\n')
check('paste an object in empty braces on a line of their own in an array', paste('k: [\n\t{|}\n]\n', '{"x": 1}'), 'k: [\n\t{\n\t\tx: 1\n\t}\n]\n')
check('paste an object in empty braces on the line after a key', paste('k:\n\t{|}\n', '{"x": 1}'), 'k:\n\t{\n\t\tx: 1\n\t}\n')
check('paste an empty object in empty braces', paste('deps: {|}\n', '{}'), 'deps: {}\n')
check('paste an object on the line after a key', paste('k:\n\t|\n', '{"x": 1}'), 'k:\n\t{\n\t\tx: 1\n\t}\n')
check('paste an object at the start of the line after a key', paste('k:\n|\n', '{"x": 1}'), 'k:\n{\n\tx: 1\n}\n')
check('paste an object after a key and a comment', paste('k: # note\n\t|\n', '{"x": 1}'), 'k: # note\n\t{\n\t\tx: 1\n\t}\n')
check('paste an object after a key and a block comment', paste('k: /* a */ /* b */\n\t|\n', '{"x": 1}'), 'k: /* a */ /* b */\n\t{\n\t\tx: 1\n\t}\n')
check('paste an object after a nested key', paste('o: {\n\tk:\n\t\t|\n}\n', '{"x": 1}'), 'o: {\n\tk:\n\t\t{\n\t\t\tx: 1\n\t\t}\n}\n')
check('paste an object after a key in an array', paste('k: [\n\t{a:\n\t\t|\n\t}\n]\n', '{"x": 1}'), 'k: [\n\t{a:\n\t\t{\n\t\t\tx: 1\n\t\t}\n\t}\n]\n')
check('paste members after a comment that ends with a colon', paste('# see:\n|\n', '{"x": 1}'), '# see:\nx: 1\n')
check('paste members after a member', paste('a: 1\n|\n', '{"x": 1}'), 'a: 1\nx: 1\n')
check('paste members after a key with a colon in it', paste("'a:': 1\n|\n", '{"x": 1}'), "'a:': 1\nx: 1\n")

for name, json_text in {
	'a duplicate key': '{"a": 1, "a": 2}',
	'a float that is too large': '{"a": 1e400}',
	'a float that rounds to zero': '{"a": 1e-400}',
	'NaN': '{"a": NaN}',
	'an int outside int64': '{"a": 9223372036854775808}',
	'a carriage return': '{"a": "\\r"}',
	'deep nesting': '[' * 100_000 + ']' * 100_000,
	'text that is not JSON': 'a: 1',
}.items():
	check(f'paste rejects {name}', paste('x: 1\n|', json_text), 'x: 1\n')

###[ KEY PATHS ]###############################################################

plugin = sys.modules['SOML.plugin']
paths_document = "name: 'x'\nservers: [\n\t{host: 'a', 'the name': 1}\n]\n'logging.file': 2\n"


def copied_key_path(document, *points):
	"""The clipboard after Copy Key Path, with a caret at the `|` and at the points."""
	set_clipboard('')
	view = view_with_caret(document)
	for point in points:
		view.sel().add(sublime.Region(point))

	view.run_command('soml_copy_key_path')
	return clipboard


check('copy key path in an array', copied_key_path(paths_document.replace("'a'", "'|a'")), 'servers[0].host')
check('copy key path of a quoted key', copied_key_path(paths_document.replace(' 1}', ' |1}')), "servers[0].'the name'")
check('copy key path of a key with a dot', copied_key_path(paths_document.replace(': 2', ': |2')), "'logging.file'")
check('copy key path on a key', copied_key_path('|' + paths_document), 'name')
check('copy key path outside a member', copied_key_path(paths_document + '|'), '')
# Each on a line of its own, as the built-in Copy copies several selections.
check('copy key path at every caret', copied_key_path('a: 1|\nb: [2]\n', 9), 'a\nb[0]')
check('copy key path at the carets in a member', copied_key_path('a: 1|\nb: 2\n', 0), 'a\na')
check('copy key path skips a caret outside a member', copied_key_path('a: 1|\n# c\n', 7), 'a')
check('copy key path of an invalid document', copied_key_path('a: |1\na: 2\n'), '')

tree = soml.tree.parse(paths_document)
check('goto key entries', [plugin.format_path(path) for path, _ in plugin.members(tree.body)], ['name', 'servers', 'servers[0].host', "servers[0].'the name'", "'logging.file'"])
check('goto key previews', [plugin.preview(member.value, tree.source) for _, member in plugin.members(tree.body)], ["'x'", '[…]', "'a'", '1', '2'])
check('key path with keys that need quotes', plugin.format_path(['a\nb', 0, "it's"]), '"a\\nb"[0]."it\'s"')


def applied(old, changes):
	for start, end, replacement in reversed(changes):
		old = old[:start] + replacement + old[end:]

	return old


for old, new in [('', 'a\n'), ('a: 1\n', ''), ('a:   1\nb:  2\n', 'a: 1\nb: 2\n'), ('a: [\n1,\n2]\n', 'a: [\n\t1\n\t2\n]\n'), ('x\u2028y\n\x85\n', 'x\u2028 y\n'), ('a\n' * 3000, 'b\n' * 3000), ('[' + ', '.join(['1'] * 4000) + ']', '[\n' + '\n'.join(['\t1'] * 4000) + '\n]')]:
	check(f'text changes give the new text for {old[:20]!r}', applied(old, plugin.text_changes(old, new)), new)

# Comparing characters or lines takes time that grows much faster than their count, which these took seconds to minutes for.
numbers = ', '.join(str(index * 37 % 100) for index in range(800))
for name, old, new in [
	('a long line of numbers that is split', f'a: [{numbers}]\n', soml.format(f'a: [\n{numbers}]\n')),
	('a long line of the same item that is split', '[' + ', '.join(['1'] * 1600) + ']', '[\n' + '\t1\n' * 1600 + ']'),
	('lines of numbers that get spaces', 'grid: [\n' + ''.join('\t[' + ','.join('0' * 78) + ']\n' for _ in range(750)) + ']\n', 'grid: [\n' + ''.join('\t[' + ', '.join('0' * 78) + ']\n' for _ in range(750)) + ']\n'),
	('records with values that repeat', ''.join(f"user{index}: {{\n\tname:   'user{index}'\n\tcountry: 'c{index % 50}'\n\tage: {index % 70}\n}}\n" for index in range(2000)), ''.join(f"user{index}: {{\n\tname: 'user{index}'\n\tcountry: 'c{index % 50}'\n\tage: {index % 70}\n}}\n" for index in range(2000))),
	('records with values that repeat and lines that go', ''.join(f"user{index}: {{\n\tname:   'user{index}'\n\n\tage: {index % 70}\n}}\n" for index in range(2000)), ''.join(f"user{index}: {{\n\tname: 'user{index}'\n\tage: {index % 70}\n}}\n" for index in range(2000))),
	('blank lines between members', ''.join(f'k{index}:    {index}\n\n\n' for index in range(1000)), ''.join(f'k{index}: {index}\n\n' for index in range(1000))),
	('blank lines between items', 'a: [\n' + ''.join(f'  {index},\n\n' for index in range(2000)) + ']\n', 'a: [\n' + ''.join(f'\t{index}\n\n' for index in range(2000)) + ']\n'),
	('many lines that are the same', 'a: [\n' + '\t\t1\n' * 20000 + ']\n', 'a: [\n' + '\t\t1\n' * 10000 + '\t\t2\n' + '\t\t1\n' * 9999 + ']\n'),
]:
	started = time.monotonic()
	changes = plugin.text_changes(old, new)
	check(f'text changes are quick for {name}', (applied(old, changes) == new, time.monotonic() - started < 2), (True, True))

check('text changes are in order and do not overlap', all(first[1] <= second[0] for first, second in zip(plugin.text_changes('a:   1\nb:  2\n', 'a: 1\nb: 2\n'), plugin.text_changes('a:   1\nb:  2\n', 'a: 1\nb: 2\n')[1:])), True)
check('a point before a change stays', plugin.moved_point(1, [(3, 5, 'x')]), 1)
check('a point at the start of a change stays before it', plugin.moved_point(3, [(3, 5, 'x')]), 3)
check('a point at an insertion stays before it', plugin.moved_point(3, [(3, 3, 'xyz')]), 3)
check('a point in a change goes to the same place in the replacement', plugin.moved_point(4, [(3, 6, 'xyz')]), 4)
check('a point in a change that gets shorter goes to its end', plugin.moved_point(5, [(3, 6, 'x')]), 4)
check('a point at the end of a change goes after the replacement', plugin.moved_point(5, [(3, 5, 'xyz')]), 6)
check('a point after changes moves with them', plugin.moved_point(10, [(1, 2, ''), (3, 3, 'ab'), (5, 7, 'xyz')]), 12)

###[ HOVER ]###################################################################

check('hover a duration', plugin.describe_duration('1h30m'), ['<b>1 hour 30 minutes</b>', '5,400 seconds'])
check('hover seconds', plugin.describe_duration('30s'), ['<b>30 seconds</b>'])
check('hover milliseconds', plugin.describe_duration('250ms'), ['<b>250 milliseconds</b>', '0.25 seconds'])
check('hover a negative duration', plugin.describe_duration('-1.5s'), ['<b>-1 second 500 milliseconds</b>', '-1.5 seconds'])
check('hover days', plugin.describe_duration('36h'), ['<b>1 day 12 hours</b>', '129,600 seconds'])
check('hover a nanosecond', plugin.describe_duration('1ns'), ['<b>1 nanosecond</b>', '0.000000001 seconds'])
check('hover a fraction of an hour', plugin.describe_duration('1_000.5h'), ['<b>41 days 16 hours 30 minutes</b>', '3,601,800 seconds'])
check('hover a zero duration', plugin.describe_duration('0s'), ['<b>0 seconds</b>'])
check('hover hexadecimal', plugin.describe_integer('1F90', 16), ['<b>8,080</b>'])
check('hover octal', plugin.describe_integer('644', 8), ['<b>420</b>', '0x1A4', 'rw-r--r--'])
check('hover binary', plugin.describe_integer('1010_1100', 2), ['<b>172</b>', '0xAC'])

check('offset name of UTC', plugin.offset_name(datetime.timedelta(0)), 'UTC')
check('offset name of whole hours', plugin.offset_name(datetime.timedelta(hours=2)), 'UTC+2')
check('offset name with minutes', plugin.offset_name(datetime.timedelta(hours=-5, minutes=-30)), 'UTC-5:30')
check('offset name below an hour', plugin.offset_name(datetime.timedelta(minutes=-30)), 'UTC-0:30')
# A local mean time, which time zones have before about 1900, has seconds.
check('offset name with seconds', plugin.offset_name(datetime.timedelta(hours=6, minutes=42, seconds=4)), 'UTC+6:42:04')
check('negative offset name with seconds', plugin.offset_name(-datetime.timedelta(hours=4, minutes=56, seconds=2)), 'UTC-4:56:02')
check('offset name of only seconds', plugin.offset_name(datetime.timedelta(seconds=-30)), 'UTC-0:00:30')



def relative(instant, now='2026-10-10T12:00:00'):
	return plugin.describe_relative(datetime.datetime.fromisoformat(instant + '+00:00'), datetime.datetime.fromisoformat(now + '+00:00'))


check('relative now', relative('2026-10-10T12:00:00.5'), 'Now')
check('relative seconds', relative('2026-10-10T11:59:01'), '59 seconds ago')
check('relative days', relative('2026-10-12T12:00:00'), 'In 2 days')
check('relative weeks before a month', relative('2026-09-10T12:00:01'), '4 weeks ago')
check('relative month', relative('2026-09-10T12:00:00'), '1 month ago')
check('relative months before a year', relative('2025-10-10T12:00:01'), '11 months ago')
check('relative year', relative('2025-10-10T12:00:00'), '1 year ago')
check('relative years before an anniversary', relative('2022-10-11T00:00:00'), '3 years ago')
check('relative years over leap days', relative('2022-10-10T12:00:00'), '4 years ago')
check('relative future months', relative('2027-01-10T12:00:00'), 'In 3 months')
check('relative from the first instant', relative('0001-01-01T00:00:00'), '2,025 years ago')
check('relative to the last instant', relative('9999-12-31T23:59:59.999999'), 'In 7,973 years')

instant_lines = plugin.describe_instant('2026-09-19T14:00:00.123456789+02:00')
local_offset = datetime.datetime(2026, 9, 19, 12, tzinfo=datetime.UTC).astimezone().utcoffset()
check('hover an instant in local time', instant_lines[0].endswith(' in your time zone') and '.123456789' in instant_lines[0], True)
check('hover an instant in UTC', local_offset == datetime.timedelta(0) or 'Saturday, September 19, 2026, 12:00:00.123456789 UTC' in instant_lines, True)
check('hover a past instant', plugin.describe_instant('2000-01-01T00:00:00Z')[-1].endswith(' years ago'), True)
check('hover a future instant', plugin.describe_instant('9999-12-31T23:59:59Z')[-1].startswith('In '), True)
check('hover the first instant', len(plugin.describe_instant('0001-01-01T00:00:00Z')) >= 2, True)

hover_view = new_view("a: [0x1F90, 1h30m, 2026-09-19T14:00:00Z, 86400000, 42, 'x']\n")
hover_text = text_of(hover_view)
check('hover finds a hexadecimal int', plugin.describe_value(hover_view, hover_text.index('1F90')), ['<b>8,080</b>'])
check('hover finds a duration', plugin.describe_value(hover_view, hover_text.index('30m')), ['<b>1 hour 30 minutes</b>', '5,400 seconds'])
check('hover finds an instant', plugin.describe_value(hover_view, hover_text.index('T14')) is not None, True)
check('hover groups a long int', plugin.describe_value(hover_view, hover_text.index('864')), ['<b>86,400,000</b>'])
check('hover groups a long negative int', plugin.describe_value(new_view('a: -86400000\n'), 4), ['<b>-86,400,000</b>'])
check('hover a negative duration from its sign', plugin.describe_value(new_view('a: -5m\n'), 3), ['<b>-5 minutes</b>', '-300 seconds'])
check('hover skips a short int', plugin.describe_value(hover_view, hover_text.index('42')), None)
check('hover skips an instant outside the range in UTC', plugin.describe_value(new_view('a: 0001-01-01T00:00:00+00:01\n'), 5), None)
check('hover skips a duration that is not a whole number of nanoseconds', plugin.describe_value(new_view('a: 1.5ns\n'), 3), None)
check('hover skips an int outside int64', plugin.describe_value(new_view('a: 99999999999999999999\n'), 3), None)
check('hover skips a hexadecimal int outside int64', plugin.describe_value(new_view('a: 0xFFFFFFFFFFFFFFFFFF\n'), 5), None)
check('hover skips a string', plugin.describe_value(hover_view, hover_text.index("'x'") + 1), None)

###[ STRING CONVERSIONS ]######################################################


def run_on(document, command, **arguments):
	view = view_with_caret(document)
	view.run_command(command, arguments)
	return text_of(view)


check('toggle a literal string', run_on('a: \'x"y\\|\'\n', 'soml_toggle_quotes'), 'a: "x\\"y\\\\"\n')
check('toggle an escaped string', run_on('a: "x y|"\n', 'soml_toggle_quotes'), "a: 'x y'\n")
check('toggle an escaped string with a tab', run_on('a: "x\\ty|"\n', 'soml_toggle_quotes'), 'a: "x\\ty"\n')
check('toggle a string at the end of a file', run_on('a: "x"|', 'soml_toggle_quotes'), "a: 'x'")
check('toggle an escaped string with a quote', run_on('a: "it\'s|"\n', 'soml_toggle_quotes'), 'a: "it\'s"\n')
check('toggle a quoted key', run_on("'a |b': 1\n", 'soml_toggle_quotes'), '"a b": 1\n')
check('toggle with the caret after the string', run_on("a: 'x'|\n", 'soml_toggle_quotes'), 'a: "x"\n')
two_carets = view_with_caret("a: 'x|yz'\n")
two_carets.sel().add(sublime.Region(6))
two_carets.run_command('soml_toggle_quotes')
check('toggle with two carets in one string', text_of(two_carets), 'a: "xyz"\n')
check('toggle a bare key', run_on('a|b: 1\n', 'soml_toggle_quotes'), 'ab: 1\n')

block = "'" * 3
check('to a block string', run_on("key: 'a|'\n", 'soml_toggle_block_string'), f'key:\n\t{block}\n\ta\n\t{block}\n')
check('to a block string with lines', run_on('key: "a\\nb|"\n', 'soml_toggle_block_string'), f'key:\n\t{block}\n\ta\n\tb\n\t{block}\n')
check('from a block string', run_on(f'key:\n\t{block}\n\ta|\n\tb\n\t{block}\n', 'soml_toggle_block_string'), 'key: "a\\nb"\n')
check('from a block string on the line of its key', run_on(f'key: {block}\n\ta|\n\t{block}\n', 'soml_toggle_block_string'), "key: 'a'\n")
check('to a block string in an array', run_on('a: [\n\t"x\\ny|"\n]\n', 'soml_toggle_block_string'), f'a: [\n\t{block}\n\tx\n\ty\n\t{block}\n]\n')
check('to a block string in a one-line array', run_on('a: [1, "x\\ny|"]\n', 'soml_toggle_block_string'), f'a: [1, {block}\n\tx\n\ty\n\t{block}]\n')
check('to a block string with a delimiter in it', run_on('a: "\'\'\'\\nx|"\n', 'soml_toggle_block_string'), f"a:\n\t{block}'\n\t{block}\n\tx\n\t{block}'\n")
check('a block string keeps a trailing space', run_on('a: "x \\ny|"\n', 'soml_toggle_block_string'), f'a:\n\t{block}\n\tx \n\ty\n\t{block}\n')
check('a key is not made a block string', run_on("'a|': 1\n", 'soml_toggle_block_string'), "'a': 1\n")
check('from a block string after a comment that ends with a colon', run_on(f'k: # see:\n\t{block}\n\tx|\n\t{block}\n', 'soml_toggle_block_string'), "k: # see:\n\t'x'\n")
check('from a block string after an array item', run_on(f"a: [\n\t'x'\n\t# note:\n\t{block}\n\ty|\n\t{block}\n]\n", 'soml_toggle_block_string'), "a: [\n\t'x'\n\t# note:\n\t'y'\n]\n")
check('from a block string at the end of a file', run_on(f'k: {block}\n\tx\n\t{block}|', 'soml_toggle_block_string'), "k: 'x'")
check('to a block string with a tab', run_on('a: "x\\ty|"\n', 'soml_toggle_block_string'), 'a:\n\t"""\n\tx\\ty\n\t"""\n')

tabs_view = view_with_caret('a: "x\\ty|"\n')
tabs_view.settings().set('translate_tabs_to_spaces', True)
tabs_view.run_command('soml_toggle_block_string')
check('to a block string keeps a tab with translate_tabs_to_spaces', soml.loads(text_of(tabs_view)), {'a': 'x\ty'})

for name, value in [('a control character', 'a\\u{1}'), ('a leading line break', '\\nab'), ('a trailing line break', 'ab\\n'), ('a line of spaces', 'a\\n  \\nb'), ('a backslash', 'a\\\\b\\nc')]:
	original = f'a: "{value}"\n'
	converted = run_on(original.replace('"\n', '|"\n'), 'soml_toggle_block_string')
	check(f'a block string with {name} holds the value', soml.loads(converted), soml.loads(original))
	# The caret on the first content line of the block string.
	caret = converted.index('\n', converted.index('\n') + 1) + 2
	check(f'a block string with {name} toggles back', run_on(converted[:caret] + '|' + converted[caret:], 'soml_toggle_block_string'), original)

###[ STRUCTURE ]###############################################################

check('split an array', run_on('ports: [8|0, 443]\n', 'soml_toggle_one_line'), 'ports: [\n\t80\n\t443\n]\n')
check('join an array', run_on('ports: [\n\t8|0\n\t443\n]\n', 'soml_toggle_one_line'), 'ports: [80, 443]\n')
check('join with commas', run_on('a: [\n\t1|,\n\t2,\n]\n', 'soml_toggle_one_line'), 'a: [1, 2]\n')
check('split a nested array', run_on('a: {\n\tb: [|1, 2]\n}\n', 'soml_toggle_one_line'), 'a: {\n\tb: [\n\t\t1\n\t\t2\n\t]\n}\n')
check('join flattens what is inside', run_on('a: {\n\tb: {\n\t\tc: 1\n\t}\n\td: |2\n}\n', 'soml_toggle_one_line'), 'a: {b: {c: 1}, d: 2}\n')
check('join a key with a dot', run_on("a: {\n\t'x.|y': 1\n}\n", 'soml_toggle_one_line'), "a: {'x.y': 1}\n")
check('split keeps a comment', run_on('a: [1, /* c */ |2]\n', 'soml_toggle_one_line'), 'a: [\n\t1\n\t/* c */ 2\n]\n')
check('join refuses a comment', run_on('a: [\n\t1 # c\n\t|2\n]\n', 'soml_toggle_one_line'), 'a: [\n\t1 # c\n\t2\n]\n')
check('join refuses a block string', run_on(f'a: [\n\t|{block}\n\tx\n\t{block}\n]\n', 'soml_toggle_one_line'), f'a: [\n\t{block}\n\tx\n\t{block}\n]\n')
check('toggle one line outside a container', run_on('a: |1\n', 'soml_toggle_one_line'), 'a: 1\n')
many_containers = soml.tree.parse('first: [1, 2]\n' + ''.join(f'other{index}: [1, 2]\n' for index in range(5000)))
started = time.monotonic()
for _ in range(100):
	first_container = plugin.container_at(many_containers, 9)

check('find a container quickly in a long document', (many_containers.source[first_container.range[0]:first_container.range[1]], time.monotonic() - started < 0.2), ('[1, 2]', True))


def run_with_caret(document, command, times=1):
	"""The text with `|` at the caret after running the command."""
	view = view_with_caret(document)
	for _ in range(times):
		view.run_command(command)

	return with_caret(view)


spaces_view = view_with_caret('o: {\n  p: [1|, {a: 2}]\n}\n')
spaces_view.settings().set('translate_tabs_to_spaces', True)
spaces_view.settings().set('tab_size', 2)
spaces_view.run_command('soml_toggle_one_line')
check('split indented with spaces', text_of(spaces_view), 'o: {\n  p: [\n    1\n    {a: 2}\n  ]\n}\n')



def toggled_with_carets(document, *points):
	"""The text after Toggle One Line, with a caret at the `|` and at the points."""
	view = view_with_caret(document)
	for point in points:
		view.sel().add(sublime.Region(point))

	view.run_command('soml_toggle_one_line')
	return text_of(view)


check('split at every caret', toggled_with_carets('a: [1|, 2]\nb: [3, 4]\n', 13), 'a: [\n\t1\n\t2\n]\nb: [\n\t3\n\t4\n]\n')
check('join at every caret', toggled_with_carets('a: [\n\t1|\n]\nb: {\n\tc: 2\n}\n', 18), 'a: [1]\nb: {c: 2}\n')
check('split and join at two carets', toggled_with_carets('a: [1|, 2]\nb: [\n\t3\n]\n', 15), 'a: [\n\t1\n\t2\n]\nb: [3]\n')
check('toggle one line once for two carets in a container', toggled_with_carets('a: [1|, 2]\n', 8), 'a: [\n\t1\n\t2\n]\n')
check('toggle one line in the outer container of two carets', toggled_with_carets('a: [1|, [2, 3]]\n', 9), 'a: [\n\t1\n\t[2, 3]\n]\n')

# The caret keeps its place among the characters around it, so the command can be run again.
check('split keeps the caret', run_with_caret('ports: [80, 44|3]\n', 'soml_toggle_one_line'), 'ports: [\n\t80\n\t44|3\n]\n')
check('join keeps the caret', run_with_caret('ports: [\n\t80\n\t44|3\n]\n', 'soml_toggle_one_line'), 'ports: [80, 44|3]\n')
check('split and join give back the text and the caret', run_with_caret('a: {b: 1, c: |2}\n', 'soml_toggle_one_line', times=2), 'a: {b: 1, c: |2}\n')
check('join and split give back the text and the caret', run_with_caret('a: [\n\t1\n\t|2\n]\n', 'soml_toggle_one_line', times=2), 'a: [\n\t1\n\t|2\n]\n')
undo_view = view_with_caret('a: [1|, 2]\nb: [3, 4]\n')
undo_view.sel().add(sublime.Region(13))
undo_view.run_command('soml_toggle_one_line')
undo_view.run_command('undo')
check('toggle one line at two carets is one undo step', text_of(undo_view), 'a: [1, 2]\nb: [3, 4]\n')
spaces_view = view_with_caret('o: {\n  k: "x\\ny|"\n}\n')
spaces_view.settings().set('translate_tabs_to_spaces', True)
spaces_view.settings().set('tab_size', 2)
spaces_view.run_command('soml_toggle_block_string')
check('to a block string indented with spaces', text_of(spaces_view), "o: {\n  k:\n    '''\n    x\n    y\n    '''\n}\n")
spaces_view.run_command('soml_toggle_block_string')
check('from a block string indented with spaces', with_caret(spaces_view), 'o: {\n  k: "x\\ny|"\n}\n')
check('to a block string keeps the caret', run_with_caret("a: 'x|yz'\n", 'soml_toggle_block_string'), f"a:\n\t{block}\n\tx|yz\n\t{block}\n")
check('to a block string with lines keeps the caret', run_with_caret('a: "x\\ny|"\n', 'soml_toggle_block_string'), f"a:\n\t{block}\n\tx\n\ty|\n\t{block}\n")
check('from a block string keeps the caret', run_with_caret(f"a:\n\t{block}\n\tx|yz\n\t{block}\n", 'soml_toggle_block_string'), "a: 'x|yz'\n")
check('to a block string and back gives back the text and the caret', run_with_caret('a: "x\\ny|z"\n', 'soml_toggle_block_string', times=2), 'a: "x\\ny|z"\n')

###[ INSERT CURRENT INSTANT ]##################################################

utc_text = run_on('a: |\n', 'soml_insert_instant')
instant_view = view_with_caret('a: |\nb: \n')
instant_view.sel().add(sublime.Region(text_of(instant_view).index('b: ') + 3))
instant_view.run_command('soml_insert_instant')
check('insert an instant puts every caret after it', [(region.a, region.b) for region in instant_view.sel()], [(23, 23), (47, 47)])
check('insert an instant in UTC', re.fullmatch(r'a: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n', utc_text) is not None and isinstance(soml.loads(utc_text)['a'], datetime.datetime), True)
local_text = run_on('a: |\n', 'soml_insert_instant', local=True)
check('insert an instant in local time', re.fullmatch(r'a: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d\n', local_text) is not None and isinstance(soml.loads(local_text)['a'], datetime.datetime), True)

###[ CONVERT TO SOML ]#########################################################


def convert(syntax, text, path=None):
	"""The SOML view that Convert to SOML opens, or `None` when it opens none."""
	source = window.new_file(syntax=syntax)
	source.run_command('append', {'characters': text})
	if path is not None:
		source.retarget(path)

	views_before = len(window.views())
	source.run_command('soml_convert_to_soml')
	return window.active_view() if len(window.views()) > views_before else None


json_view = convert('Packages/JSON/JSON.sublime-syntax', '{"name": "api", "port": 8080, "ratio": 1.0, "tags": ["a"], "big": 9223372036854775807}', '/tmp/config.json')
check('convert JSON to SOML', text_of(json_view), "name: 'api'\nport: 8080\nratio: 1.0\ntags: [\n\t'a'\n]\nbig: 9223372036854775807\n")
check('convert JSON to SOML uses the SOML syntax', json_view.syntax().scope, 'source.soml')
check('convert JSON to SOML names the tab', json_view.name(), 'config.soml')
check('convert JSON to SOML saves next to the file', json_view.settings().get('default_dir'), '/tmp')
toml_view = convert('Packages/TOML/TOML.sublime-syntax', 'title = "x" # A comment\n[server]\nport = 8080\nat = 2026-09-19T14:00:00+02:00\n[[servers]]\nhost = "a"\n')
check('convert TOML to SOML', text_of(toml_view), "title: 'x'\nserver: {\n\tport: 8080\n\tat: 2026-09-19T12:00:00Z\n}\nservers: [\n\t{\n\t\thost: 'a'\n\t}\n]\n")

for name, syntax, text in [
	('a duplicate JSON key', 'Packages/JSON/JSON.sublime-syntax', '{"a": 1, "a": 2}'),
	('a JSON scalar', 'Packages/JSON/JSON.sublime-syntax', '5'),
	('JSON that is not valid', 'Packages/JSON/JSON.sublime-syntax', '{"a": }'),
	('a TOML local date', 'Packages/TOML/TOML.sublime-syntax', '[server]\nstart = 2026-09-19\n'),
	('a TOML local date-time', 'Packages/TOML/TOML.sublime-syntax', 'start = 2026-09-19T14:00:00\n'),
	('a TOML local time', 'Packages/TOML/TOML.sublime-syntax', 'start = 14:00:00\n'),
	('TOML NaN', 'Packages/TOML/TOML.sublime-syntax', 'a = nan\n'),
	('a TOML int outside int64', 'Packages/TOML/TOML.sublime-syntax', 'a = 9223372036854775808\n'),
]:
	check(f'convert to SOML refuses {name}', convert(syntax, text), None)

check('convert to SOML refuses a TOML float that is too large', convert('Packages/TOML/TOML.sublime-syntax', 'a = 1e999\n'), None)
check('convert to SOML refuses a TOML float that rounds to zero', convert('Packages/TOML/TOML.sublime-syntax', 'a = 1e-999\n'), None)
check('convert TOML infinity and underscores', text_of(convert('Packages/TOML/TOML.sublime-syntax', 'a = -inf\nb = 1_000.5\nc = 0.0\n')), 'a: -infinity\nb: 1000.5\nc: 0.0\n')
check('convert TOML inline tables and dotted keys', text_of(convert('Packages/TOML/TOML.sublime-syntax', 'a.b = 1\nc = {d = [1, {e = "x"}]}\n"f.g" = 2\n')), "a: {\n\tb: 1\n}\nc: {\n\td: [\n\t\t1\n\t\t{\n\t\t\te: 'x'\n\t\t}\n\t]\n}\n'f.g': 2\n")
check('convert to SOML in an uppercase JSON5 file', text_of(convert('Packages/Text/Plain text.tmLanguage', '{a: 1}', '/tmp/CONFIG.JSON5')), 'a: 1\n')
check('paste an empty object at the start of a line', paste('k: {\n\t|\n}\n', '{}'), 'k: {\n\t\n}\n')
check('paste an empty object after a key', paste('k: |\n', '{}'), 'k: {}\n')
check('the TOML local date reason', plugin.unsupported_value({'server': {'start': datetime.date(2026, 9, 19)}}), 'SOML has no date without a time, at server.start')
jsonc_view = convert('Packages/JSON/JSON.sublime-syntax', '// A comment\n{\n\t"a": 1, /* note */\n\t"b": [1, 2,],\n}\n', '/tmp/settings.jsonc')
check('convert JSONC to SOML', text_of(jsonc_view), 'a: 1\nb: [\n\t1\n\t2\n]\n')
json5_text = "{\n\tunquoted: 'single',\n\thex: 0xFF,\n\tplus: +1,\n\tleading: .5,\n\ttrailing: 5.,\n\tlimit: Infinity,\n\tlines: 'a\\\nb',\n\tescape: '\\x41\\u00e9',\n}\n"
json5_view = convert('Packages/Text/Plain text.tmLanguage', json5_text, '/tmp/config.json5')
check('convert JSON5 to SOML', text_of(json5_view), "unquoted: 'single'\nhex: 255\nplus: 1\nleading: 0.5\ntrailing: 5.0\nlimit: infinity\nlines: 'ab'\nescape: 'Aé'\n")
check('convert to SOML refuses JSON5 NaN', convert('Packages/Text/Plain text.tmLanguage', '{a: NaN}', '/tmp/nan.json5'), None)
check('convert to SOML is not in a text file', plugin.SomlConvertToSomlCommand(window.new_file(syntax='Packages/Text/Plain text.tmLanguage')).is_enabled(), False)
check('paste JSON5 as SOML', paste('|', "{a: 'x', b: [1, 2,], // c\n}"), "a: 'x'\nb: [\n\t1\n\t2\n]")
check('paste JSONC as SOML', paste('|', '{"a": 1 /* c */}'), 'a: 1')

json5 = sys.modules['SOML.json5']
check('JSON5 keeps an int and a float apart', json5.loads('[1, 1.0, 1e2, 0x10, -0]'), [1, 1.0, 100.0, 16, 0])
check('JSON5 reads a non-ASCII digit after \\0', json5.loads('"\\0\u0663"'), '\x00\u0663')
check('JSON5 reads a surrogate pair', json5.loads('"\\ud83d\\ude00"'), '😀')
for name, text in [('a leading zero', '[01]'), ('a duplicate key', '{a: 1, a: 2}'), ('a comment that is not closed', '[1 /* c'), ('a line break in a string', '"a\nb"'), ('a digit escape', "'\\1'"), ('a leading comma', '[,1]'), ('two commas', '[1,,]'), ('a float that is too large', '1e400'), ('deep nesting', '[' * 500 + ']' * 500), ('an int with too many digits', '1' + '0' * 5000)]:
	try:
		json5.loads(text)
		check(f'JSON5 refuses {name}', 'read', 'refused')
	except json5.JSON5DecodeError:
		check(f'JSON5 refuses {name}', 'refused', 'refused')


def json5_error(text):
	try:
		json5.loads(text)
	except json5.JSON5DecodeError as error:
		return str(error)

	return None


check('JSON5 error for a string that ends after \\0', json5_error('"\\0'), 'A string is not closed, at line 1, column 4')
check('JSON5 error for \\0 before a digit', json5_error('"\\01"'), 'A \\0 escape cannot be followed by a digit, at line 1, column 4')
check('JSON5 reads \\0 at the end of a string', json5.loads('"\\0"'), '\x00')
# The message goes to the status bar, so a long number is cut short, as an int that is too large is.
check('JSON5 error for a long float that is too large', json5_error('1' * 400 + '.0'), f'The number {"1" * 20}… is too large for a 64-bit float, at line 1, column 1')
check('JSON5 error for a long float that rounds to zero', json5_error('0.' + '0' * 400 + '1'), f'The number 0.{"0" * 18}… is too small to be told apart from zero, at line 1, column 1')
check('JSON5 error for a short float that is too large', json5_error('[1e400]'), 'The number 1e400 is too large for a 64-bit float, at line 1, column 2')
check('JSON5 error for an int that is too large', json5_error('1' * 5000), f'The number {"1" * 20}… is too large, at line 1, column 1')
for name, line_break in [('carriage return', '\r'), ('CRLF', '\r\n'), ('line separator', '\u2028'), ('paragraph separator', '\u2029')]:
	check(f'JSON5 error after {name}', json5_error(f'[1,{line_break},]'), 'Unexpected character, at line 2, column 1')
check('JSON5 error after mixed line breaks', json5_error('[1,\r\n2,\u2028 ,]'), 'Unexpected character, at line 3, column 2')

check('convert to SOML is not in a SOML file', new_view('a: 1\n').window() is not None and plugin.SomlConvertToSomlCommand(new_view('a: 1\n')).is_enabled(), False)

###[ TRIM TRAILING WHITESPACE ]################################################

check('trim trailing whitespace', run_on(f'a: 1   \nb: {block}  \n\tx  \n\t{block}  \n# c  \n|', 'soml_trim_trailing_whitespace'), f'a: 1\nb: {block}\n\tx  \n\t{block}\n# c\n')

###[ AUTO INDENT ]#############################################################


def enter(document):
	"""The text after inserting a line break at the `|`, with auto indent on, as Enter does."""
	view = view_with_caret(document)
	view.settings().set('auto_indent', True)
	view.run_command('insert', {'characters': '\n'})
	return with_caret(view)


check('enter after a key', enter('a:|\n'), 'a:\n\t|\n')
check('enter after a bracket', enter('a: {|\n}\n'), 'a: {\n\t|\n}\n')
check('enter after a bracket that is followed by closed brackets', enter('a: {b: [1, 2],|\n}\n'), 'a: {b: [1, 2],\n\t|\n}\n')
check('enter after a bracket and a block comment', enter('a: [ /* c */|\n]\n'), 'a: [ /* c */\n\t|\n]\n')
check('enter after a bracket and an open block comment', enter('a: [ /* c|\n*/]\n'), 'a: [ /* c\n\t|\n*/]\n')
check('enter after a bracket and a line comment', enter('a: [ # c|\n]\n'), 'a: [ # c\n\t|\n]\n')
# The lines of a block string are its value, and the lines of a block comment are prose.
check('enter in a block string after a colon', enter(f'a:\n\t{block}\n\tFor example:|\n\t{block}\n'), f'a:\n\t{block}\n\tFor example:\n\t|\n\t{block}\n')
check('enter in a block string after a bracket', enter(f'a:\n\t{block}\n\tx: [|\n\t{block}\n'), f'a:\n\t{block}\n\tx: [\n\t|\n\t{block}\n')
check('enter in an escaped block string after a brace', enter('a:\n\t"""\n\tx {|\n\t"""\n'), 'a:\n\t"""\n\tx {\n\t|\n\t"""\n')
check('enter in a block string after a word and a colon', enter(f'a:\n\t{block}\n\tUsage:|\n\t{block}\n'), f'a:\n\t{block}\n\tUsage:\n\t|\n\t{block}\n')
check('enter in a block comment after a brace', enter('/*\n\tx {|\n*/\na: 1\n'), '/*\n\tx {\n\t|\n*/\na: 1\n')
check('enter in a block string after a bracket and an open block comment', enter(f'a:\n\t{block}\n\tx [ /* y|\n\t{block}\n'), f'a:\n\t{block}\n\tx [ /* y\n\t|\n\t{block}\n')
check('enter in a block comment after a colon', enter('/*\n\tNote:|\n*/\na: 1\n'), '/*\n\tNote:\n\t|\n*/\na: 1\n')
check('enter in a block comment after a bracket', enter('a: 1 /* [|\n*/\n'), 'a: 1 /* [\n|\n*/\n')

###[ KEY BINDINGS ]############################################################

keymap = json.loads(re.sub(r'^\s*//.*$', '', sublime.load_resource('Packages/SOML/Default.sublime-keymap'), flags=re.MULTILINE))


def binding_for(view, key):
	caret = view.sel()[0].b
	line = view.line(caret)
	preceding = view.substr(sublime.Region(line.begin(), caret))
	following = view.substr(sublime.Region(caret, line.end()))

	def matches(context):
		operand = context.get('operand', True)
		if context['key'] == 'selector':
			return view.match_selector(caret, operand)

		if context['key'] in ('preceding_text', 'following_text'):
			found = re.search(operand, preceding if context['key'] == 'preceding_text' else following) is not None
			return found if context['operator'] == 'regex_contains' else not found

		return True

	return next((binding for binding in keymap if binding['keys'] == [key] and all(matches(context) for context in binding['context'])), None)


def press(document, key):
	"""The text after pressing the key, or `None` when no binding of the package applies."""
	view = view_with_caret(document)
	binding = binding_for(view, key)
	if binding is None:
		return None

	# A key binding runs a window command, such as `chain`, on the window.
	if binding['command'] == 'chain':
		window.run_command(binding['command'], binding.get('args', {}))
	else:
		view.run_command(binding['command'], binding.get('args', {}))

	return with_caret(view)


check('third quote', press("key: ''|\n", "'"), "key: '''|'''\n")
check('third double quote', press('key: ""|\n', '"'), 'key: """|"""\n')
check('third quote at the end of the file', press("key: ''|", "'"), "key: '''|'''")
check('third double quote at the end of the file', press('key: ""|', '"'), 'key: """|"""')
check('third quote before a comma', press("a: [''|, 1]\n", "'"), "a: ['''|''', 1]\n")
check('enter', press("key: '''|'''\n", 'enter'), "key: '''\n|\n'''\n")
check('enter on an indented line', press("a:\n\t'''|'''\n", 'enter'), "a:\n\t'''\n\t|\n\t'''\n")
check('enter in a double block string', press('key: """|"""\n', 'enter'), 'key: """\n|\n"""\n')
check('backspace in a double block string', press('key: """|"""\n', 'backspace'), 'key: "|"\n')
check('backspace', press("key: '''|'''\n", 'backspace'), "key: '|'\n")

for name, document, key in [
	('third quote in a comment', "# ''|\n", "'"),
	('third quote in a string', "key: \"a''|\"\n", "'"),
	('third quote before a space in a string', "key: \"say ''| now\"\n", "'"),
	('third double quote before a space in a literal string', "key: 'say \"\"| now'\n", '"'),
	('third quote before a comma in a string in an array', "a: [\"x ''|, y\"]\n", "'"),
	('third quote in a block string', "key: '''\n\t''|\n\t'''\n", "'"),
	('fourth quote', "key: '''|'''\n", "'"),
	('third quote before text', "key: ''|abc\n", "'"),
	('enter in a single-line string', "key: \"x '''|''' y\"\n", 'enter'),
	('enter on a content line of a block string with a longer delimiter', "a:\n\t''''\n\t'''|'''\n\t''''\n", 'enter'),
	('backspace on a content line of a block string with a longer delimiter', "a:\n\t''''\n\t'''|'''\n\t''''\n", 'backspace'),
	('backspace on a content line of an escaped block string with a longer delimiter', 'a:\n\t""""\n\t"""|"""\n\t""""\n', 'backspace'),
	('backspace in a block string of the other quote', "key: \"\"\"\n\t'''|'''\n\t\"\"\"\n", 'backspace'),
]:
	check(f'no binding for {name}', press(document, key), None)

###[ LINE ENDINGS AND ENCODING ]###############################################


def write_file(name, content):
	path = os.path.join(directory, name)
	with open(path, 'wb') as file:
		file.write(content)

	return path


def read_file(path):
	with open(path, 'rb') as file:
		return file.read()


# Opening, saving, and reading back files is asynchronous, so these run one after the other.
files = [
	('format changes CRLF to LF', write_file('crlf.soml', b'a:   1\r\nb: 2\r\n'), False, b'a: 1\nb: 2\n'),
	('format removes a BOM', write_file('bom.soml', '\ufeffa: \'é\'\n'.encode()), False, 'a: \'é\'\n'.encode()),
	('format changes Windows 1252 to UTF-8', write_file('latin.soml', 'a: \'é\'\r\n'.encode('cp1252')), False, 'a: \'é\'\n'.encode()),
	('format on save', write_file('on-save.soml', b'a:   1\r\n'), True, b'a: 1\n'),
	('an invalid document is saved as it is', write_file('invalid.soml', b'a: 1\na: 2\n'), True, b'a: 1\na: 2\n'),
	('save trims trailing whitespace', write_file('trailing.soml', b"a: 1  \nb:\n\t'''\n\tx  \n\t'''\n"), None, b"a: 1\nb:\n\t'''\n\tx  \n\t'''\n"),
]


def next_file():
	if not files:
		finish({'count': count, 'failures': failures})
		return

	name, path, on_save, expected = files.pop(0)
	view = window.open_file(path)

	def when_loaded():
		if view.is_loading():
			sublime.set_timeout(lambda: run_safely(when_loaded), 20)
			return

		# `None` saves with the default settings.
		if on_save:
			view.settings().set('soml_format_on_save', True)
		elif on_save is not None:
			view.run_command('soml_format')

		view.run_command('save')
		sublime.set_timeout(lambda: run_safely(after_save), 300)

	def after_save():
		check(name, read_file(path), expected)
		view.close()
		next_file()

	when_loaded()


def wait_until(condition, then, deadline=None):
	"""Call `then` once the condition holds, or after 10 seconds. The status bar is updated on the async thread, which can be busy for a while with the views of the checks before."""
	deadline = deadline or time.monotonic() + 10
	if condition() or time.monotonic() > deadline:
		then()
	else:
		sublime.set_timeout(lambda: run_safely(lambda: wait_until(condition, then, deadline)), 50)


def check_status_bar():
	view = view_with_caret(paths_document.replace("'a'", "'|a'"))

	def after_update():
		check('status bar shows the key path', view.get_status('soml_key_path'), 'servers[0].host')
		# A command, because changing the selection with the API does not send the event that a caret move sends.
		view.run_command('move_to', {'to': 'eof'})
		wait_until(lambda: view.get_status('soml_key_path') == '', after_moving_out)

	def after_moving_out():
		check('status bar has no key path outside a member', view.get_status('soml_key_path'), '')
		check_opened_file()

	wait_until(lambda: view.get_status('soml_key_path') != '', after_update)


def check_opened_file():
	view = window.open_file(write_file('key-path.soml', b'name: 1\n'))

	def after_update():
		check('status bar shows the key path of an opened file', view.get_status('soml_key_path'), 'name')
		view.close()
		check_syntax_change()

	wait_until(lambda: view.get_status('soml_key_path') != '', after_update)


def check_syntax_change():
	view = view_with_caret('na|me: 1\n')

	def after_update():
		# Without moving the caret, which would send an event.
		view.assign_syntax('Packages/Text/Plain text.tmLanguage')
		wait_until(lambda: view.get_status('soml_key_path') == '', after_changing_syntax)

	def after_changing_syntax():
		check('status bar has no key path after the syntax changes', view.get_status('soml_key_path'), '')
		view.assign_syntax('Packages/SOML/SOML.sublime-syntax')
		view.run_command('move_to', {'to': 'bof'})
		wait_until(lambda: view.get_status('soml_key_path') != '', after_changing_back)

	def after_changing_back():
		check('status bar shows the key path after the syntax changes back', view.get_status('soml_key_path'), 'name')
		check_setting_change(view)

	wait_until(lambda: view.get_status('soml_key_path') != '', after_update)


def check_setting_change(view):
	# Changed in memory only. Without moving the caret, which would send an event.
	settings = sublime.load_settings('SOML.sublime-settings')
	settings.set('soml_show_key_path', False)

	def after_turning_off():
		check('status bar has no key path after the setting is turned off', view.get_status('soml_key_path'), '')
		settings.erase('soml_show_key_path')
		wait_until(lambda: view.get_status('soml_key_path') != '', after_turning_on)

	def after_turning_on():
		check('status bar shows the key path after the setting is turned on', view.get_status('soml_key_path'), 'name')
		check_goto_key()

	wait_until(lambda: view.get_status('soml_key_path') == '', after_turning_off)


def check_goto_key():
	# The quick panel is replaced, because a real one can bring Sublime Text to the front. Its callbacks are called as the panel calls them.
	panel = {}
	show_quick_panel = sublime.Window.show_quick_panel
	sublime.Window.show_quick_panel = lambda self, items, on_select, **arguments: panel.update(items=items, on_select=on_select, **arguments)
	try:
		view = view_with_caret(paths_document.replace("'a'", "'|a'"))
		caret = view.sel()[0]
		view.run_command('soml_goto_key')
	finally:
		sublime.Window.show_quick_panel = show_quick_panel

	check('goto key starts at the key of the caret', panel['items'][panel['selected_index']].trigger, 'servers[0].host')
	panel['on_highlight'](panel['selected_index'] + 1)
	check('goto key previews the highlighted key', view.substr(view.sel()[0]), "'the name'")
	panel['on_select'](-1)
	check('goto key restores the selection when cancelled', list(view.sel()), [caret])
	panel['on_select'](4)
	check('goto key selects the chosen key', view.substr(view.sel()[0]), "'logging.file'")
	next_file()


check_status_bar()
