"""
Sublime Text plugin used by `st-run`. It runs once on startup: reads the job file, runs syntax tests or dumps tokens, writes the result JSON, and quits Sublime Text.

It only does anything when the job file exists, so it is harmless in a normal session (it is only installed into the isolated data directory anyway).
"""

import json
import os
import traceback

import sublime
import sublime_api

JOB_PATH = os.path.join(os.path.dirname(sublime.packages_path()), 'st-runner-job.json')

# How long to wait (ms) between token snapshots. In testing (build 4215), the first snapshot was always already complete (even for a 20k line file), so this is only a safety check.
POLL_INTERVAL = 10


def plugin_loaded():
	if not os.path.exists(JOB_PATH):
		return

	with open(JOB_PATH, encoding='utf-8') as file:
		job = json.load(file)

	os.unlink(JOB_PATH)

	# Defer so that all packages and syntaxes are loaded first.
	sublime.set_timeout(lambda: start(job), 500)


def start(job):
	if job['kind'] == 'test':
		run_safely(job, lambda: finish(job, run_tests(job)))
	elif job['kind'] == 'dump':
		run_safely(job, lambda: dump(job))
	elif job['kind'] == 'script':
		run_safely(job, lambda: run_script(job))
	else:
		finish(job, {'error': 'Unknown job kind: ' + job['kind']})


def run_safely(job, function):
	"""Report exceptions as the job result, so the instance quits instead of hanging until the timeout."""
	try:
		function()
	except Exception:
		finish(job, {'error': traceback.format_exc()})


def finish(job, result):
	temporary_path = job['output'] + '.partial'
	with open(temporary_path, 'w', encoding='utf-8') as file:
		json.dump(result, file)

	os.replace(temporary_path, job['output'])

	for window in sublime.windows():
		for view in window.views():
			view.set_scratch(True)
			view.close()

	sublime.set_timeout(lambda: sublime.run_command('exit'), 100)


def run_script(job):
	"""Run a Python file inside Sublime Text. It reports its result with `finish(dictionary)`, and wraps its delayed callbacks in `run_safely(function)`."""
	namespace = {
		'__file__': job['script'],
		'finish': lambda result: finish(job, result),
		'run_safely': lambda function: run_safely(job, function),
	}
	with open(job['script'], encoding='utf-8') as file:
		exec(compile(file.read(), job['script'], 'exec'), namespace)


def run_tests(job):
	prefix = 'Packages/' + job['package'] + '/'
	tests = [path for path in sublime.find_resources('syntax_test_*') if path.startswith(prefix)]
	results = []
	for test in sorted(tests):
		assertions, failures = sublime_api.run_syntax_test(test)
		results.append({'test': test, 'assertions': assertions, 'failures': failures})

	return {'packages_path': sublime.packages_path(), 'results': results}


def dump(job):
	window = sublime.active_window()
	if window is None:
		sublime.run_command('new_window')
		window = sublime.active_window()

	syntax = sublime.syntax_from_path(job['syntax'])
	if syntax is None:
		raise ValueError('Syntax not found: ' + job['syntax'])

	output = {}
	files = list(job['files'])

	def next_file():
		if not files:
			finish(job, {'tokens': output})
			return

		path = files.pop(0)
		with open(path, encoding='utf-8', newline='') as file:
			text = file.read()

		view = window.new_file(syntax=syntax.path)
		view.set_scratch(True)
		view.settings().set('auto_indent', False)
		view.run_command('append', {'characters': text})
		if view.size() != len(text):
			raise ValueError(f'Buffer size {view.size()} does not match the file length {len(text)}: {path}')

		wait_for_tokens(view, path, previous=None)

	def wait_for_tokens(view, path, previous):
		# Accept the tokens once two snapshots in a row are identical, in case tokenization is still running in the background.
		tokens = [[region.a, region.b, scope] for region, scope in view.extract_tokens_with_scopes(sublime.Region(0, view.size()))]
		if tokens != previous:
			sublime.set_timeout(lambda: run_safely(job, lambda: wait_for_tokens(view, path, tokens)), POLL_INTERVAL)
			return

		output[path] = tokens
		view.close()
		next_file()

	next_file()
