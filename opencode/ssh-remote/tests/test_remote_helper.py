"""Real one-shot helper tests: no SSH server, keys, privileged or live operations.

Only test-owned TemporaryDirectories are removed. Symlinks are rejected even
when their destinations stay inside cwd, to prevent approval aliases. Bash is
explicitly NOT a jail; deliberately setsid-detached children are not contained.
"""

import hashlib
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


HELPER = (Path(__file__).resolve().parents[1] / 'remote.py').read_text()


@unittest.skipIf(os.geteuid() == 0, 'helper must be tested as a non-root user')
class RemoteHelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(
            prefix='.opencode-helper-test-', dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def request(self, operation, args, expected=None, **overrides):
        result = dict(operation=operation, cwd=str(self.root), args=args,
                      expected=expected or {}, timeout_ms=5000, max_output_bytes=131072)
        result.update(overrides)
        return result

    def start(self, request=None, raw=None):
        process = subprocess.Popen([sys.executable, '-B', '-u', '-c', HELPER],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        def cleanup():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        process.stdin.write(raw if raw is not None else json.dumps(request).encode() + b'\n')
        process.stdin.flush()
        return process

    def finish(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(8), 'helper did not reply')
        raw = process.stdout.readline(131073)
        self.assertTrue(raw.endswith(b'\n'), raw[:200])
        self.assertLessEqual(len(raw), 131072)
        # The transport closes input ONLY after seeing the completed response.
        if not process.stdin.closed:
            process.stdin.close()
        self.assertEqual(process.wait(timeout=3), 0)
        self.assertEqual(process.stderr.read(), b'')
        self.assertEqual(process.stdout.read(), b'')
        return json.loads(raw)

    def call(self, operation, args, expected=None, **overrides):
        return self.finish(self.start(self.request(operation, args, expected, **overrides)))

    def file(self, name='a.txt', content=b'first\nsecond\n'):
        path = self.root / name
        path.write_bytes(content)
        return path

    def expected(self, *paths):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                if path.exists() else None for path in paths}

    def assert_error(self, response, fragment=None):
        self.assertIs(response['ok'], False, response)
        self.assertEqual(set(response), {'ok', 'error'})
        self.assertLess(len(response['error']), 200)
        if fragment:
            self.assertIn(fragment, response['error'])

    def test_read_offset_and_whole_file_hash(self):
        path = self.file(content=b'one\r\ntwo\r\nthree')
        reply = self.call('read', dict(filePath='a.txt', offset=2, limit=1))
        self.assertEqual(reply, dict(ok=True, output='two\r\n', truncated=True, files=[
            dict(path=str(path), sha256=self.expected(path)[str(path)])]))

    def test_read_suffix_omission_is_truncated(self):
        path = self.file(content=b'one\r\ntwo\r\n')
        before = path.read_bytes()
        reply = self.call('read', dict(filePath='a.txt', offset=1, limit=1))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['output'], 'one\r\n')
        self.assertTrue(reply.get('truncated', False), reply)
        self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
        self.assertEqual(path.read_bytes(), before)

    def test_read_prefix_omission_is_truncated(self):
        path = self.file(content=b'one\r\ntwo\r\n')
        before = path.read_bytes()
        reply = self.call('read', dict(filePath='a.txt', offset=2, limit=10))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['output'], 'two\r\n')
        self.assertTrue(reply.get('truncated', False), reply)
        self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
        self.assertEqual(path.read_bytes(), before)

    def test_read_beyond_eof_is_truncated_even_for_empty_file(self):
        for content in (b'', b'one\n', b'one\r\ntwo\r\n'):
            with self.subTest(content=content):
                path = self.file(content=content)
                reply = self.call('read', dict(filePath='a.txt', offset=10, limit=10))
                self.assertTrue(reply['ok'], reply)
                self.assertEqual(reply['output'], '')
                self.assertTrue(reply.get('truncated', False), reply)
                self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
                self.assertEqual(path.read_bytes(), content)

    def test_read_full_file_explicitly_reports_not_truncated(self):
        for content in (b'', b'\n', b'\r\n', b'one', b'one\n',
                        b'one\ntwo', b'one\r\ntwo\r\n'):
            for limit in (max(1, len(content.splitlines())), 10):
                with self.subTest(content=content, limit=limit):
                    path = self.file(content=content)
                    reply = self.call('read', dict(filePath='a.txt', offset=1, limit=limit))
                    self.assertTrue(reply['ok'], reply)
                    self.assertEqual(reply['output'], content.decode())
                    self.assertIs(reply['truncated'], False, reply)
                    self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
                    self.assertEqual(path.read_bytes(), content)

    def test_read_line_completeness_and_byte_caps_both_apply(self):
        path = self.file(content=b'one\r\ntwo\r\n')
        before = path.read_bytes()
        for args in (dict(filePath='a.txt', offset=1, limit=2),
                     dict(filePath='a.txt', offset=1, limit=1),
                     dict(filePath='a.txt', offset=2, limit=1)):
            with self.subTest(args=args):
                reply = self.call('read', args, max_output_bytes=1)
                self.assertTrue(reply['ok'], reply)
                self.assertIs(reply['truncated'], True, reply)
                self.assertEqual(len(reply['output'].encode()), 1)
                self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
                self.assertEqual(path.read_bytes(), before)

    def test_read_default_limit_marks_omitted_blank_line(self):
        path = self.file(content=b'one\r\n' * 2000 + b'\r\n')
        before = path.read_bytes()
        reply = self.call('read', dict(filePath='a.txt'))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['output'], 'one\r\n' * 2000)
        self.assertIs(reply['truncated'], True, reply)
        self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
        self.assertEqual(path.read_bytes(), before)

    def test_read_zero_offset_or_limit_rejected_without_effects(self):
        for content in (b'', b'one\r\ntwo\r\n'):
            path = self.file(content=content)
            for bounds in (dict(offset=0), dict(limit=0)):
                with self.subTest(content=content, bounds=bounds):
                    self.assert_error(self.call('read', dict(filePath='a.txt', **bounds)), 'bound')
                    self.assertEqual(path.read_bytes(), content)

    def test_read_before_edit_and_stale_write(self):
        path = self.file()
        args = dict(filePath=str(path), oldString='second', newString='updated')
        self.assert_error(self.call('edit', args), 'read required')
        read = self.call('read', dict(filePath=str(path)))
        expected = {item['path']: item['sha256'] for item in read['files']}
        reply = self.call('edit', args, expected)
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(path.read_bytes(), b'first\nupdated\n')
        self.assertEqual(reply['files'][0]['sha256'], self.expected(path)[str(path)])
        self.assert_error(self.call('write', dict(filePath=str(path), content='oops'), expected), 'conflict')
        self.assertEqual(path.read_bytes(), b'first\nupdated\n')

    def test_atomic_write_preserves_mode_and_old_inode(self):
        path = self.file()
        path.chmod(0o751)
        with path.open('rb') as old:
            reply = self.call('write', dict(filePath='a.txt', content='new'), self.expected(path))
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(old.read(), b'first\nsecond\n')
        self.assertEqual(path.read_bytes(), b'new')
        self.assertEqual(path.stat().st_mode & 0o7777, 0o751)
        self.assertEqual(list(self.root.glob('.opencode-*')), [])

    def test_new_file_requires_explicit_absence_and_existing_parent(self):
        path = self.root / 'new.txt'
        args = dict(filePath='new.txt', content='hello')
        self.assert_error(self.call('write', args), 'read required')
        self.assertTrue(self.call('write', args, {str(path): None})['ok'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assert_error(self.call('write', args, {str(path): None}), 'conflict')
        missing = self.root / 'missing' / 'new.txt'
        self.assert_error(self.call('write', dict(filePath=str(missing), content='x'), {str(missing): None}))
        self.assertFalse(missing.parent.exists())

    def test_unique_edit_replace_all_crlf_and_overlapping_match(self):
        path = self.file(content=b'one\r\none\r\n')
        args = dict(filePath='a.txt', oldString='one\n', newString='two\n')
        self.assert_error(self.call('edit', args, self.expected(path)), 'ambiguous')
        args['replaceAll'] = True
        self.assertTrue(self.call('edit', args, self.expected(path))['ok'])
        self.assertEqual(path.read_bytes(), b'two\r\ntwo\r\n')
        path.write_bytes(b'aaa')
        self.assert_error(self.call('edit', dict(filePath='a.txt', oldString='aa', newString='x'), self.expected(path)), 'ambiguous')

    def test_edit_size_checked_before_expansion(self):
        path = self.file(content=b'a' * 10000)
        self.assert_error(self.call('edit', dict(filePath='a.txt', oldString='a',
                                               newString='x' * 10000, replaceAll=True),
                                    self.expected(path)), 'size')
        self.assertEqual(path.stat().st_size, 10000)

    def test_reject_traversal_outside_paths_and_noncanonical_expected(self):
        path = self.file()
        for name in ('../a.txt', 'sub/../a.txt', '/etc/passwd', '//etc/passwd'):
            with self.subTest(name=name):
                self.assert_error(self.call('read', dict(filePath=name)))
        self.assert_error(self.call('write', dict(filePath='a.txt', content='x'),
                                    {'a.txt': self.expected(path)[str(path)]}), 'canonical')
        self.assert_error(self.call('read', dict(filePath='a.txt'), cwd=str(self.root) + '/.'))

    def test_symlink_components_inside_and_outside_and_hardlinks_rejected(self):
        path = self.file()
        (self.root / 'alias').symlink_to(path)
        (self.root / 'directory-alias').symlink_to(self.root, target_is_directory=True)
        (self.root / 'outside').symlink_to('/etc', target_is_directory=True)
        (self.root / 'dangling').symlink_to(self.root / 'absent')
        for name in ('alias', 'directory-alias/a.txt', 'outside/passwd', 'dangling'):
            with self.subTest(name=name):
                self.assert_error(self.call('read', dict(filePath=name)))
                self.assert_error(self.call('write', dict(filePath=name, content='x'),
                                            {str(self.root / name): None}))
        os.link(path, self.root / 'hardlink')
        self.assert_error(self.call('read', dict(filePath='hardlink')), 'hard-link')
        for operation, args in [('bash', dict(command='pwd', workdir='directory-alias')),
                                ('glob', dict(pattern='*', path='directory-alias')),
                                ('grep', dict(pattern='first', path='directory-alias'))]:
            self.assert_error(self.call(operation, args))
        self.assert_error(self.call('read', dict(filePath='a.txt'),
                                    cwd=str(self.root / 'directory-alias')))

    def test_file_payload_is_data_not_shell_code(self):
        name = '$(touch SHOULD_NOT_EXIST).txt'
        content = '`touch ALSO_NOT_CREATED`\n$HOME\n'
        reply = self.call('write', dict(filePath=name, content=content),
                          {str(self.root / name): None})
        self.assertTrue(reply['ok'], reply)
        self.assertEqual((self.root / name).read_text(), content)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {name})

    def test_text_regular_file_and_size_limits(self):
        path = self.file(content=b'\xff')
        self.assert_error(self.call('read', dict(filePath='a.txt')), 'UTF-8')
        path.write_bytes(b'hello\x00world')
        self.assert_error(self.call('read', dict(filePath='a.txt')), 'binary')
        with path.open('wb') as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        self.assert_error(self.call('read', dict(filePath='a.txt')), 'size')
        os.mkfifo(self.root / 'pipe')
        self.assert_error(self.call('read', dict(filePath='pipe')), 'regular')

    def test_patch_add_delete_update_move_and_exact_anchor(self):
        old = self.file(content=b'header\r\none\r\ntwo\r\nend\r\n')
        deleted = self.file('delete.txt', b'delete\n')
        moved, added = self.root / 'moved.txt', self.root / 'added.txt'
        old.chmod(0o740)
        patch = ('*** Begin Patch\n*** Update File: a.txt\n*** Move to: moved.txt\n'
                 '@@ header\n one\n-two\n+THREE\n end\n*** End of File\n'
                 '*** Add File: added.txt\n+added\n*** Delete File: delete.txt\n*** End Patch\n')
        reply = self.call('apply_patch', dict(patchText=patch), self.expected(old, deleted, moved, added))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(moved.read_bytes(), b'header\r\none\r\nTHREE\r\nend\r\n')
        self.assertEqual(moved.stat().st_mode & 0o777, 0o740)
        self.assertEqual(added.read_bytes(), b'added\n')
        self.assertFalse(old.exists())
        self.assertFalse(deleted.exists())
        hashes = {item['path']: item['sha256'] for item in reply['files']}
        self.assertIsNone(hashes[str(old)])
        self.assertIsNone(hashes[str(deleted)])
        self.assertEqual(hashes[str(moved)], self.expected(moved)[str(moved)])

    def test_patch_all_validation_before_effects(self):
        a = self.file(content=b'one\ntwo\n')
        b = self.file('b.txt', b'original\n')
        first = '*** Begin Patch\n*** Update File: a.txt\n@@\n-one\n+changed\n'
        invalid = [
            '*** Update File: b.txt\n@@\n-missing\n+new\n',
            '*** Update File: b.txt\n@@ -1 +1 @@\n-original\n+new\n',
            '*** Delete File: ../outside\n',
            '*** Update File: b.txt\n@@\n+contextless\n',
            '*** Update File: a.txt\n@@\n-two\n+duplicate\n',
            '*** Unknown: no\n',
        ]
        for last in invalid:
            with self.subTest(last=last):
                self.assert_error(self.call('apply_patch', dict(patchText=first + last + '*** End Patch\n'), self.expected(a, b)))
                self.assertEqual(a.read_bytes(), b'one\ntwo\n')
                self.assertEqual(b.read_bytes(), b'original\n')
        expected = self.expected(a, b)
        b.write_bytes(b'changed elsewhere\n')
        self.assert_error(self.call('apply_patch', dict(patchText=first + '*** Delete File: b.txt\n*** End Patch'), expected), 'conflict')
        self.assertEqual(a.read_bytes(), b'one\ntwo\n')

    def test_patch_ambiguous_context_and_mixed_endings_rejected(self):
        path = self.file(content=b'one\none\n')
        patch = '*** Begin Patch\n*** Update File: a.txt\n@@\n-one\n+new\n*** End Patch'
        self.assert_error(self.call('apply_patch', dict(patchText=patch), self.expected(path)), 'ambiguous')
        path.write_bytes(b'one\r\ntwo\n')
        self.assert_error(self.call('apply_patch', dict(patchText=patch), self.expected(path)), 'mixed')

    def test_patch_move_destination_conflicts_and_missing_hash_have_no_effects(self):
        path = self.file(content=b'one\n')
        destination = self.root / 'destination'
        patch = ('*** Begin Patch\n*** Update File: a.txt\n*** Move to: destination\n'
                 '@@\n-one\n+two\n*** End Patch')
        self.assert_error(self.call('apply_patch', dict(patchText=patch), self.expected(path)), 'read required')
        destination.write_bytes(b'existing\n')
        self.assert_error(self.call('apply_patch', dict(patchText=patch), self.expected(path, destination)), 'absent')
        self.assertEqual(path.read_bytes(), b'one\n')
        self.assertEqual(destination.read_bytes(), b'existing\n')

    def test_patch_multiple_hunks_preserve_no_final_newline(self):
        path = self.file(content=b'one\ntwo\nthree\nfour')
        patch = ('*** Begin Patch\n*** Update File: a.txt\n@@\n-one\n+ONE\n two\n'
                 '@@\n three\n-four\n+FOUR\n*** End Patch')
        self.assertTrue(self.call('apply_patch', dict(patchText=patch), self.expected(path))['ok'])
        self.assertEqual(path.read_bytes(), b'ONE\ntwo\nthree\nFOUR')

    @unittest.skipUnless(shutil.which('rg'), 'requires ripgrep')
    def test_glob_grep_option_safety_no_matches_and_invalid_regex(self):
        self.file(content=b'--version\nneedle\n')
        self.file('b.md', b'needle\n')
        (self.root / 'linked.txt').symlink_to(self.root / 'a.txt')
        reply = self.call('glob', dict(pattern='*.txt'))
        self.assertTrue(reply['ok'], reply)
        self.assertIn('a.txt', reply['output'])
        self.assertNotIn('linked.txt', reply['output'])
        reply = self.call('grep', dict(pattern='--version', include='*.txt'))
        self.assertTrue(reply['ok'], reply)
        self.assertIn('a.txt:1:--version', reply['output'])
        self.assertNotIn('ripgrep ', reply['output'])
        for operation in ('glob', 'grep'):
            reply = self.call(operation, dict(pattern='--not-an-option'))
            self.assertTrue(reply['ok'], reply)
            self.assertEqual(reply['exit_code'], 1)
            self.assertEqual(reply['output'], '')
        self.assert_error(self.call('grep', dict(pattern='[private-regex')), 'rg failed')
        self.assert_error(self.call('glob', dict(pattern='[invalid')), 'rg failed')
        reply = self.call('grep', dict(pattern='needle', include='--version'))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['output'], '')

    def test_bash_exit_output_workdir_and_not_containment(self):
        nested = self.root / 'nested'
        nested.mkdir()
        reply = self.call('bash', dict(command='pwd; printf error >&2; exit 7',
                                       workdir='nested', description='test command'))
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['exit_code'], 7)
        self.assertIn(str(nested), reply['output'])
        self.assertIn('error', reply['output'])
        reply = self.call('bash', dict(command='cd /; pwd'))
        self.assertEqual(reply['output'], '/\n')
        self.assert_error(self.call('bash', dict(command='pwd', workdir='/')))
        reply = self.call('bash', dict(command='pwd'), cwd='/')
        self.assertEqual(reply['output'], '/\n')

    def test_output_and_encoded_frame_bounds(self):
        self.file(content=('😀\\"\n' * 40000).encode())
        reply = self.call('read', dict(filePath='a.txt', limit=100000), max_output_bytes=131072)
        self.assertTrue(reply['ok'], reply)
        self.assertTrue(reply['truncated'])
        reply = self.call('bash', dict(command="python3 -c 'import os; os.write(1, b\"x\" * 1000000)'"), max_output_bytes=97)
        self.assertEqual(reply['output'], 'x' * 97)
        self.assertTrue(reply['truncated'])

    def test_strict_request_validation_and_no_private_diagnostics(self):
        base = self.request('read', dict(filePath='secret-do-not-print'))
        variants = [dict(base, surprise='no'), dict(base, timeout_ms=600001),
                    dict(base, max_output_bytes=131073), dict(base, timeout_ms=True),
                    dict(base, operation=[]), dict(base, args={'filePath': 'private', 'bad': 1})]
        for request in variants:
            self.assert_error(self.finish(self.start(request)))
        self.assertNotIn('secret-do-not-print', self.call('read', base['args'])['error'])
        self.assert_error(self.finish(self.start(raw=b'{"private":"secret",}\n')))
        self.assert_error(self.finish(self.start(raw=b'{"x":1,"x":2}\n')), 'duplicate')
        self.assert_error(self.finish(self.start(raw=b'{}\n{}\n')))

    def test_input_size_limit(self):
        self.assert_error(self.finish(self.start(raw=b' ' * (1024 * 1024 + 1))), 'size')

    def test_timeout_bash_local_budget_and_continuous_output(self):
        start = time.monotonic()
        reply = self.call('bash', dict(command='while :; do printf xxxxxxxxxxxx; done', timeout=100),
                          timeout_ms=3000, max_output_bytes=64)
        self.assert_error(reply, 'timed out')
        self.assertLess(time.monotonic() - start, 3)

    def child_command(self):
        # A non-detached child ignores TERM: KILL escalation must stop it too.
        code = ('import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'open("child.pid","w").write(str(os.getpid())); time.sleep(30)')
        return 'python3 -c ' + shlex.quote(code) + ' & wait'

    def wait_child(self):
        path = self.root / 'child.pid'
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if path.exists() and path.read_text().strip():
                return int(path.read_text())
            time.sleep(0.02)
        self.fail('child never started')

    def assert_child_stopped(self, pid):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                status = Path('/proc', str(pid), 'stat').read_text()
            except FileNotFoundError:
                return
            if status.rsplit(')', 1)[1].split()[0] == 'Z':
                return  # init owns orphan reaping; zombie cannot execute
            time.sleep(0.02)
        self.fail('owned non-detached child still running')

    def test_eof_cancels_process_group_and_kills_term_ignoring_child(self):
        process = self.start(self.request('bash', dict(command=self.child_command())))
        pid = self.wait_child()
        process.stdin.close()
        self.assert_error(self.finish(process), 'cancelled')
        self.assert_child_stopped(pid)

    def test_signal_cancels_process_group(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                pidfile = self.root / 'child.pid'
                if pidfile.exists():
                    pidfile.unlink()
                process = self.start(self.request('bash', dict(command=self.child_command())))
                pid = self.wait_child()
                process.send_signal(sig)
                self.assert_error(self.finish(process), 'cancelled')
                self.assert_child_stopped(pid)

    def test_deadline_cleans_group(self):
        process = self.start(self.request('bash', dict(command=self.child_command()), timeout_ms=600))
        pid = self.wait_child()
        self.assert_error(self.finish(process), 'timed out')
        self.assert_child_stopped(pid)

    def test_graceful_term_is_not_blocked_in_child(self):
        code = ('import os,signal,time,sys; '
                'signal.signal(signal.SIGTERM,lambda *_: '
                '(open("graceful","w").write("yes"),sys.exit(0))); '
                'open("child.pid","w").write(str(os.getpid())); time.sleep(30)')
        process = self.start(self.request('bash', dict(command='python3 -c ' + shlex.quote(code))))
        pid = self.wait_child()
        process.stdin.close()
        self.assert_error(self.finish(process), 'cancelled')
        self.assert_child_stopped(pid)
        self.assertTrue((self.root / 'graceful').exists(), 'child did not receive graceful TERM')

    def test_python_patch_loops_obey_deadline_before_effects(self):
        path = self.file(content=b'a\n' * 500000)
        original = self.expected(path)
        patch = ('*** Begin Patch\n*** Update File: a.txt\n@@\n' +
                 ' a\n' * 1000 + '-missing\n+new\n*** End Patch')
        self.assert_error(self.call('apply_patch', dict(patchText=patch), original,
                                    timeout_ms=20), 'timed out')
        self.assertEqual(self.expected(path), original)

    def test_normal_exit_cleans_background_group_even_after_leader_exit(self):
        command = self.child_command().removesuffix(' & wait')
        process = self.start(self.request('bash', dict(command=command + ' >/dev/null 2>&1 & sleep 0.2')))
        pid = self.wait_child()
        self.assertTrue(self.finish(process)['ok'])
        self.assert_child_stopped(pid)


if __name__ == '__main__':
    unittest.main()
