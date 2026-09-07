"""Pi-only Bash lifecycle tests. Temporary fixtures; no installs or live services."""
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
ROOT = SCRIPTS.parents[1]


class RootRejection(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0, 'actual root guard requires root runner')
    def test_root_refused_before_account_lookup_or_mutations(self):
        for script, args in [('entrypoint.sh', ['install']), ('entrypoint.sh', ['initialize-home']),
                             ('start.sh', ['session']), ('start.sh', ['service']),
                             ('manage.sh', ['status']), ('manage.sh', ['version']),
                             ('manage.sh', ['update', 'a' * 40])]:
            result = subprocess.run(['/bin/bash', SCRIPTS / script, *args],
                                    env={'PATH': '/usr/bin:/bin'}, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('never root', result.stderr)

    def test_no_privileged_install_or_shared_framework(self):
        text = (SCRIPTS / 'entrypoint.sh').read_text()
        self.assertIn('[[ $EUID != 0 && $UID != 0 ]]', text)
        self.assertIn('$EUID == "${PI_UID:-}"', text)
        for obsolete in ('apt-get', 'runuser', 'PI_BUILD_USER', 'provision()', 'lifecycle.py'):
            self.assertNotIn(obsolete, text)
        for name in ('pi', 'pi-run', 'pi-mgr', 'init.sh', 'Dockerfile', 'docker-compose.yml'):
            docker = (ROOT / 'pi' / name).read_text()
            self.assertNotIn('scripts/start.sh', docker)
            self.assertNotIn('scripts/entrypoint.sh', docker)


@unittest.skipIf(os.geteuid() == 0, 'run fixture Git/build/launch tests as a real non-root user')
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pi-lifecycle-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.repo = self.root / 'repo'
        self.component = self.repo / 'pi'
        self.prefix = self.component / '.runtime'
        self.workspace = self.root / 'workspace with spaces'
        self.bin = self.root / 'fixtures'
        for path in (self.home, self.component, self.workspace, self.bin):
            path.mkdir(parents=True)
        self.user = pwd.getpwuid(os.geteuid()).pw_name
        self.trace = self.root / 'build-calls'
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin', PI_USER=self.user,
                        PI_REPO=str(self.repo), PI_ROOT=str(self.component), PI_PREFIX=str(self.prefix),
                        PI_WORKSPACE=str(self.workspace), PI_UNIT='fixture.service', PI_BRANCH='agents/devai-team',
                        HOME='/wrong-home', PI_PORT='30141', PI_WEB_PASSWORD='web-secret-nonce',
                        PI_WEB_ALLOWED_HOSTS='pi.example', OPENAI_API_KEY='provider-secret-nonce',
                        NODE_OPTIONS='poison', NPM_CONFIG_REGISTRY='https://invalid.example',
                        FIXTURE_NODE=str(self.bin / 'node'), FIXTURE_NPM=str(self.bin / 'npm'))
        self.mock('getent', f"printf '%s\\n' '{self.user}:x:{os.geteuid()}:{os.getegid()}::{self.home}:/bin/bash'")
        for name in ('skills', 'commands'):
            (self.repo / 'agent' / name).mkdir(parents=True)
            (self.repo / 'agent' / name / '.keep').touch()
        (self.repo / 'agent/prompts').symlink_to('commands')
        (self.repo / '.gitignore').write_text('/pi/.runtime/\n/pi/.build.*/\n/pi/.lifecycle.lock\n')
        (self.repo / 'tracked').write_text('initial')
        self.git('init', '-q', '-b', 'agents/devai-team')
        self.git('add', '.')
        self.commit('fixture initial')
        # Executed through real env -i and real timeout, not a mocked root/user guard.
        common = ('#!/usr/bin/python3\nimport json,os,sys\nfrom pathlib import Path\n'
                  f'trace=Path({str(self.trace)!r})\n'
                  'assert os.geteuid()!=0\n'
                  'with trace.open("a") as out: out.write(json.dumps({"args":sys.argv,"env":dict(os.environ),"cwd":os.getcwd()})+"\\n")\n')
        node = common + '''if len(sys.argv)>3:
 root=Path(sys.argv[3])/"lib/node_modules"
 for name,version in zip(("@earendil-works/pi-coding-agent","@agegr/pi-web"),sys.argv[4:]):
  assert json.loads((root/name/"package.json").read_text())["version"]==version
'''
        npm = common + f'''if "--version" in sys.argv:
 print("10.9.0"); sys.exit(0)
if Path({str(self.root / 'fail-build')!r}).exists(): sys.exit(42)
prefix=Path(sys.argv[sys.argv.index("--prefix")+1])
for name,version in (("@earendil-works/pi-coding-agent","0.85.1"),("@agegr/pi-web","0.9.0")):
 path=prefix/"lib/node_modules"/name; path.mkdir(parents=True)
 (path/"package.json").write_text(json.dumps({{"version":version}}))
(prefix/"bin").mkdir()
for name in ("pi","pi-web"):
 path=prefix/"bin"/name; path.write_text({self.binary_program()!r}); path.chmod(0o755)
'''
        for name, text in [('node', node), ('npm', npm)]:
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)

    def mock(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def binary_program(self):
        return ('#!/usr/bin/python3\nimport os,sys,json\n'
                'if "--version" in sys.argv: print("0.85.1")\n'
                'elif "--help" in sys.argv: print("fixture help")\n'
                'else: print(json.dumps({"args":sys.argv[1:],"pid":os.getpid(),"uid":os.geteuid(),'
                '"cwd":os.getcwd(),"home":os.environ["HOME"],"provider":bool(os.environ.get("OPENAI_API_KEY")),'
                '"password":bool(os.environ.get("PI_WEB_PASSWORD")),"node_options":os.environ.get("NODE_OPTIONS")}))\n')

    def seed_runtime(self):
        (self.prefix / 'bin').mkdir(parents=True, exist_ok=True)
        for name in ('pi', 'pi-web'):
            path = self.prefix / 'bin' / name
            path.write_text(self.binary_program())
            path.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(['/usr/bin/git', '-C', str(self.repo), *args],
                                       env={'PATH': '/usr/bin:/bin', 'HOME': str(self.home)},
                                       text=True, stderr=subprocess.PIPE).strip()

    def commit(self, message):
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', message)

    def run_script(self, script, *args, **env):
        return subprocess.run(['/bin/bash', SCRIPTS / script, *args],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=20)

    def shell(self, script, body, **env):
        return subprocess.run(['/bin/bash', '-c', f'source {shlex.quote(str(SCRIPTS / script))}; load_contract; ' + body],
                              env=dict(self.env, **env), text=True, capture_output=True, timeout=20)

    def install(self, body='install_runtime'):
        # Swap only the two OS executable paths for fixture binaries. Real env -i,
        # timeout, UID checks, version validation, filesystem and locks still run.
        return self.shell('entrypoint.sh', '''env() {
            local arg; local -a args=()
            for arg in "$@"; do
                case "$arg" in
                    /usr/bin/node) args+=("$FIXTURE_NODE") ;;
                    /usr/bin/npm) args+=("$FIXTURE_NPM") ;;
                    *) args+=("$arg") ;;
                esac
            done
            command env "${args[@]}"
        }; ''' + body)

    def assert_failed(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn('provider-secret-nonce', result.stdout + result.stderr)
        self.assertNotIn('web-secret-nonce', result.stdout + result.stderr)

    def test_dirty_install_is_nonroot_selected_only_idempotent_and_secret_free(self):
        (self.repo / 'tracked').write_text('agent edit')
        (self.repo / 'new-edit').write_text('uncommitted')
        result = self.install('install_runtime; install_runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        installs = [c for c in calls if 'install' in c['args']]
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0]['args'][-2:], ['@earendil-works/pi-coding-agent@0.85.1', '@agegr/pi-web@0.9.0'])
        self.assertIn('--ignore-scripts=false', installs[0]['args'])
        for call in calls:
            for key in ('PI_WEB_PASSWORD', 'PI_WEB_ALLOWED_HOSTS', 'OPENAI_API_KEY', 'NODE_OPTIONS'):
                self.assertNotIn(key, call['env'])
            self.assertNotEqual(call['env']['HOME'], str(self.home))
        configs = [a.split('=', 1)[1] for a in installs[0]['args'] if a.startswith(('--userconfig=', '--globalconfig='))]
        self.assertEqual(len(set(configs)), 2)
        self.assertEqual((self.repo / 'tracked').read_text(), 'agent edit')
        self.assertEqual((self.repo / 'new-edit').read_text(), 'uncommitted')
        self.assertFalse((self.repo / 'omp').exists())
        self.assertEqual((self.home / '.pi/agent/skills').readlink(), self.repo / 'agent/skills')
        self.assertEqual(list(self.component.glob('.build.*')), [])

    def test_failed_build_and_failed_promotion_preserve_runtime(self):
        self.seed_runtime()
        before = (self.prefix / 'bin/pi').read_bytes()
        (self.root / 'fail-build').touch()
        self.assert_failed(self.install(), 'existing runtime preserved')
        self.assertEqual((self.prefix / 'bin/pi').read_bytes(), before)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(len(list(self.component.glob('.build.*'))), 1)
        (self.root / 'fail-build').unlink()
        result = self.install('''mv() {
            if [[ "$*" == *"/runtime $PI_PREFIX" ]]; then return 42; fi
            command mv "$@"
        }; install_runtime''')
        self.assert_failed(result, 'promotion failed')
        self.assertEqual((self.prefix / 'bin/pi').read_bytes(), before)

    def test_version_mismatch_rebuilds_and_post_promotion_verifies(self):
        self.assertEqual(self.install().returncode, 0)
        package = self.prefix / 'lib/node_modules/@agegr/pi-web/package.json'
        package.write_text('{"version":"wrong"}')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(package.read_text())['version'], '0.9.0')
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertTrue(any(str(self.prefix) in c['args'] for c in calls))

    def test_session_service_exact_args_home_uid_pid_and_loopback(self):
        self.seed_runtime()
        for mode, args, expected in [('session', ['-p', 'two words', '--resume'], ['-p', 'two words', '--resume']),
                                     ('service', [], ['--hostname', '127.0.0.1', '--port', '30141', '--no-open'])]:
            with subprocess.Popen(['/bin/bash', SCRIPTS / 'start.sh', mode, *args], env=self.env,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                output, error = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, error)
                data = json.loads(output)
                self.assertEqual(data['pid'], process.pid)
            self.assertEqual(data['uid'], os.geteuid())
            self.assertEqual(data['args'], expected)
            self.assertEqual(data['home'], str(self.home))
            self.assertEqual(data['cwd'], str(self.workspace))
            self.assertTrue(data['provider'])
            self.assertTrue(data['password'])  # retain original launch environment behavior
            self.assertIsNone(data['node_options'])

    def test_invalid_service_inputs_and_contract_fail_without_launch(self):
        self.seed_runtime()
        for port in ('0', '80', '65536', '030141', '1;id'):
            self.assert_failed(self.run_script('start.sh', 'service', PI_PORT=port), 'port must')
        self.assert_failed(self.run_script('start.sh', 'service', '--hostname', '0.0.0.0'), 'no extra flags')
        self.assert_failed(self.run_script('start.sh', 'service', PI_WEB_PASSWORD=''), 'supply web password')
        for key, value in [('PI_PREFIX', str(self.home)), ('PI_ROOT', str(self.repo)), ('PI_WORKSPACE', str(self.prefix))]:
            self.assertNotEqual(self.run_script('start.sh', 'session', **{key: value}).returncode, 0)
        self.assert_failed(self.run_script('start.sh', 'session', PI_UNIT='--all'), 'invalid unit')
        self.mock('getent', f"printf '%s\\n' '{self.user}:x:0:0::{self.home}:/bin/bash'")
        self.assert_failed(self.run_script('entrypoint.sh', 'install'), 'non-root account')
        self.mock('getent', f"printf '%s\\n' '{self.user}:x:99999:99999::{self.home}:/bin/bash'")
        self.assert_failed(self.run_script('entrypoint.sh', 'install'), 'exact account UID')

    def test_managed_link_migration_preserves_auth_sessions_settings_and_real_dirs(self):
        config = self.home / '.pi/agent'
        config.mkdir(parents=True)
        old = self.root / 'old-repo'
        old.mkdir()
        (config / 'skills').symlink_to(old / 'agent/skills')
        (config / 'prompts').symlink_to(self.root / 'unknown')
        (config / 'agents').mkdir()
        (config / 'agents/mine').write_text('real resource')
        for name in ('auth.json', 'settings.json', 'agent.db', 'config.yml', 'models.json'):
            (config / name).write_text('preserve ' + name)
        (config / 'sessions').mkdir()
        (config / 'sessions/one').write_text('saved session')
        # Without the explicit previous checkout, do not guess which link to migrate.
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / 'skills').readlink(), old / 'agent/skills')
        for _ in range(2):
            result = self.run_script('entrypoint.sh', 'initialize-home', PI_PREVIOUS_REPO=str(old))
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / 'skills').readlink(), self.repo / 'agent/skills')
        self.assertEqual((config / 'prompts').readlink(), self.root / 'unknown')
        self.assertEqual((config / 'agents/mine').read_text(), 'real resource')
        for name in ('auth.json', 'settings.json', 'agent.db', 'config.yml', 'models.json'):
            self.assertEqual((config / name).read_text(), 'preserve ' + name)
        self.assertEqual((config / 'sessions/one').read_text(), 'saved session')
        self.assertTrue(old.exists())

    def test_install_passes_previous_checkout_only_to_home_migration(self):
        old = self.root / 'old-repo'
        old.mkdir()
        config = self.home / '.pi/agent'
        config.mkdir(parents=True)
        (config / 'skills').symlink_to(old / 'agent/skills')
        (config / 'auth.json').write_text('preserved auth')
        self.env['PI_PREVIOUS_REPO'] = str(old)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / 'skills').readlink(), self.repo / 'agent/skills')
        self.assertEqual((config / 'auth.json').read_text(), 'preserved auth')
        for line in self.trace.read_text().splitlines():
            self.assertNotIn('PI_PREVIOUS_REPO', json.loads(line)['env'])

    def test_default_copy_is_allowlisted_exclusive_and_preserves_existing(self):
        source = self.component / '.pi/agent'
        (source / 'themes').mkdir(parents=True)
        for name in ('settings.json', 'themes/nord.json', 'auth.json', 'models.json'):
            (source / name).write_text('default ' + name)
        self.git('add', '.')
        self.commit('fixture defaults')
        config = self.home / '.pi/agent'
        config.mkdir(parents=True)
        (config / 'settings.json').write_text('private settings')
        self.assertEqual(self.run_script('entrypoint.sh', 'initialize-home').returncode, 0)
        self.assertEqual((config / 'settings.json').read_text(), 'private settings')
        self.assertEqual((config / 'themes/nord.json').read_text(), 'default themes/nord.json')
        self.assertFalse((config / 'auth.json').exists())
        self.assertFalse((config / 'models.json').exists())
        (config / 'themes/nord.json').unlink()
        failure = self.shell('entrypoint.sh', '''pi_git() {
            if [[ $1 == show ]]; then printf partial; return 42; fi
            command git -C "$PI_REPO" "$@"
        }; initialize_home''')
        self.assertNotEqual(failure.returncode, 0)
        self.assertFalse((config / 'themes/nord.json').exists())
        self.assertFalse(list((config / 'themes').glob('.pi-default.*')))
        result = self.shell('entrypoint.sh', '''ln() {
            printf concurrent > "$PI_HOME/.pi/agent/themes/nord.json"
            command ln "$@"
        }; initialize_home''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / 'themes/nord.json').read_text(), 'concurrent')

    def test_redirected_state_and_runtime_are_preserved(self):
        (self.home / '.pi').symlink_to(self.repo)
        self.assert_failed(self.run_script('entrypoint.sh', 'initialize-home'), 'redirected Pi state')
        self.seed_runtime()
        self.assert_failed(self.run_script('start.sh', 'session'), 'redirected Pi state')
        (self.prefix / 'bin/pi').unlink()
        (self.prefix / 'bin/pi-web').unlink()
        (self.prefix / 'bin').rmdir()
        self.prefix.rmdir()
        self.prefix.symlink_to(self.home)
        self.assert_failed(self.run_script('entrypoint.sh', 'install'), 'canonical absolute')

    def test_checkout_subdirectory_rejected_before_install(self):
        nested = self.repo / 'nested'
        (nested / 'pi').mkdir(parents=True)
        self.assert_failed(self.run_script('entrypoint.sh', 'install', PI_REPO=str(nested),
                           PI_ROOT=str(nested / 'pi'), PI_PREFIX=str(nested / 'pi/.runtime')), 'whole agents Git checkout')
        self.assertFalse((nested / 'pi/.runtime').exists())
        self.assertFalse(self.trace.exists())

    def update_target(self, collision=False):
        if collision:
            with (self.repo / '.gitignore').open('a') as ignore:
                ignore.write('private.scratch\n')
            self.git('add', '.gitignore')
            self.commit('fixture ignore')
        first = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-qb', 'fixture-upstream')
        (self.repo / 'tracked').write_text('upstream edit')
        self.git('add', 'tracked')
        if collision:
            (self.repo / 'private.scratch').write_text('upstream collision')
            self.git('add', '-f', 'private.scratch')
        self.commit('fixture upstream')
        target = self.git('rev-parse', 'HEAD')
        remote = self.root / 'origin.git'
        subprocess.run(['/usr/bin/git', 'clone', '-q', '--bare', self.repo, remote], check=True)
        subprocess.run(['/usr/bin/git', '-C', remote, 'update-ref', 'refs/heads/agents/devai-team', target], check=True)
        self.git('remote', 'add', 'origin', str(remote))
        self.git('checkout', '-q', 'agents/devai-team')
        return first, target

    def test_explicit_update_ff_only_preserves_branch_and_ignored_runtime(self):
        first, target = self.update_target()
        self.seed_runtime()
        result = self.run_script('manage.sh', 'update-check', target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), first)
        result = self.run_script('manage.sh', 'update', target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), target)
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD'), 'agents/devai-team')
        self.assertTrue((self.prefix / 'bin/pi').exists())

    def test_explicit_update_refuses_dirty_tree_divergence_and_wrong_branch(self):
        first, target = self.update_target()
        (self.repo / 'untracked').write_text('keep')
        self.assert_failed(self.run_script('manage.sh', 'update', target), 'dirty')
        (self.repo / 'untracked').unlink()
        (self.repo / 'tracked').write_text('local edit')
        self.assert_failed(self.run_script('manage.sh', 'update-check', target), 'dirty')
        self.assertEqual(self.git('rev-parse', 'HEAD'), first)
        self.git('add', 'tracked')
        self.commit('fixture local commit')
        self.assert_failed(self.run_script('manage.sh', 'update', target), 'not a fast-forward')
        self.git('checkout', '-qb', 'other')
        self.assert_failed(self.run_script('manage.sh', 'update', target), 'assigned PI_BRANCH')

    def test_explicit_update_refuses_ignored_file_collision(self):
        first, target = self.update_target(collision=True)
        (self.repo / 'private.scratch').write_text('private ignored content')
        result = self.run_script('manage.sh', 'update', target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), first)
        self.assertEqual((self.repo / 'private.scratch').read_text(), 'private ignored content')

    def test_status_is_read_only_and_version_does_not_dump_secrets(self):
        # Intercept exec itself: no host systemctl invocation.
        result = self.shell('manage.sh', 'exec() { printf "%s\\n" "$@"; }; manage_main status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['env', '-i', 'PATH=/usr/bin:/bin', '/usr/bin/systemctl',
                         '--no-pager', 'show', '--property=Id,LoadState,ActiveState,SubState', 'fixture.service'])
        self.seed_runtime()
        result = self.run_script('manage.sh', 'version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '0.85.1')
        self.assert_failed(self.run_script('manage.sh', 'status', 'extra'), 'unexpected arguments')

    def test_lock_bad_commands_and_update_inputs(self):
        self.assert_failed(self.shell('entrypoint.sh', 'exec 8>"$PI_ROOT/.lifecycle.lock"; flock -n 8; install_runtime'), 'another lifecycle')
        for command in ('start', 'stop', 'restart', 'logs'):
            self.assert_failed(self.run_script('manage.sh', command), 'systemctl directly')
        for sha in ('main', '-x', 'a' * 39, 'A' * 40):
            self.assert_failed(self.run_script('manage.sh', 'update', sha), 'full lowercase')
        self.assert_failed(self.run_script('entrypoint.sh', 'provision'), 'usage:')
        self.assert_failed(self.run_script('entrypoint.sh', 'install', 'extra'), 'usage:')


if __name__ == '__main__':
    unittest.main()
