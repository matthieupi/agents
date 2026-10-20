"""Non-root shell/Git/npm tests, plus opt-in isolated real-binary authentication."""
import json
import base64
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import unittest
import urllib.error
import urllib.request

COMPONENT = Path(__file__).resolve().parents[1]
SCRIPTS = COMPONENT / "scripts"


@unittest.skipIf(os.getuid() == 0, "run the suite as a real non-root user")
class NativeLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opencode-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.repo = self.base / "repo"
        self.root = self.repo / "opencode"
        self.root.mkdir(parents=True)
        self.prefix = self.root / ".runtime"
        (self.root / 'scripts').mkdir()
        self.workspace = self.base / "project with spaces"
        self.workspace.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        node = shutil.which('node')
        assert node is not None
        (self.bin / 'node').symlink_to(node)
        (self.bin / 'npm').symlink_to('npm-fixture')
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin", OPENCODE_USER=self.user,
                        OPENCODE_REPO=str(self.repo), OPENCODE_ROOT=str(self.root),
                        OPENCODE_PREFIX=str(self.prefix), OPENCODE_WORKSPACE=str(self.workspace),
                        OPENCODE_PORT="4096", OPENCODE_SERVER_PASSWORD="fake-service-fixture",
                        OPENCODE_BRANCH="assigned", OPENCODE_VERSION="2.3.4")
        self.mock("getent", f"printf '%s\\n' '{self.user}:x:{os.getuid()}:{os.getgid()}::{self.home}:/bin/bash'")
        shutil.copyfile(COMPONENT / ".gitignore", self.root / ".gitignore")
        for name in ("commands", "skills", "system", "gsd"):
            path = self.repo / "agent" / name
            path.mkdir(parents=True)
            (path / "default.md").write_text("shared")
        defaults = self.root / ".opencode/config"
        (defaults / "plugins").mkdir(parents=True)
        (defaults / 'tui-plugins/session-title').mkdir(parents=True)
        for name in ("opencode.json", "opencode.jsonc", "cli.json", "plugins/first-prompt-title.js", "plugins/background-subagents.js",
                     "tui-plugins/session-title.mjs", "tui-plugins/session-title/tui.js"):
            (defaults / name).write_text("{}")
        self.git("init", "-q", "-b", "assigned")
        self.commit("initial")
        self.first = self.git("rev-parse", "HEAD")

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(["/usr/bin/git", "-C", str(self.repo), *args], text=True).strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", message)

    def run_script(self, name, *args, **env):
        return subprocess.run(["/bin/bash", str(SCRIPTS / name), *args],
                              env=dict(self.env, **env), text=True, capture_output=True)

    def shell(self, body, **env):
        return subprocess.run(["/bin/bash", "-c", body], env=dict(self.env, **env),
                              text=True, capture_output=True)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def package(self, version="2.3.4", body=None):
        (self.prefix / "bin").mkdir(parents=True, exist_ok=True)
        package = self.prefix / "node_modules/@opencode/cli"
        package.mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(json.dumps(dict(name="@opencode/cli", version=version)))
        binary = package / "opencode.exe"
        binary.write_text("#!/bin/bash\nset -eu\n" + (body or f"printf '%s\\n' '{version}'") + "\n")
        binary.chmod(0o755)
        (self.prefix / "node_modules/.bin").mkdir(exist_ok=True)
        for link, target in ((self.prefix / "node_modules/.bin/opencode", "../@opencode/cli/opencode.exe"),
                             (self.prefix / "bin/opencode", "../node_modules/.bin/opencode")):
            if not link.is_symlink():
                link.symlink_to(target)

    def install(self, mode="good", **env):
        # Intercept env only to substitute npm's executable AFTER production has
        # constructed its actual env -i arguments. Node, env, Git and shell are real.
        self.mock("npm-fixture", r'''
[[ $EUID != 0 && $HOME == "$PWD" && $HOME == */.build.*/home ]]
[[ ${OPENCODE_SERVER_PASSWORD-unset} == unset && ${OPENCODE_PASSWORD-unset} == unset && ${NODE_OPTIONS-unset} == unset ]]
[[ ${OPENCODE_TEST_HOME-unset} == unset && ${OPENAI_API_KEY-unset} == unset ]]
[[ $XDG_STATE_HOME == "$HOME/.local/state" && $XDG_CACHE_HOME == "$HOME/.cache" ]]
[[ $NPM_CONFIG_REGISTRY == https://registry.npmjs.org ]]
[[ $NPM_CONFIG_USERCONFIG != "$NPM_CONFIG_GLOBALCONFIG" ]]
[[ -f $NPM_CONFIG_USERCONFIG && ! -s $NPM_CONFIG_USERCONFIG && -f $NPM_CONFIG_GLOBALCONFIG && ! -s $NPM_CONFIG_GLOBALCONFIG ]]
[[ " $* " == *" --ignore-scripts=false "* && " $* " == *" --include=optional "* ]]
[[ " $* " != *" --global "* && " $* " == *" --no-save "* && " $* " == *" --package-lock=false "* ]]
[[ ${!#} == @opencode/cli@latest ]]
prefix=''
while (($#)); do if [[ $1 == --prefix ]]; then prefix=$2; shift; fi; shift; done
[[ $(node -p 'JSON.parse(require("fs").readFileSync(process.argv[1])).allowScripts["@opencode/cli"]' "$prefix/package.json") == true ]]
mkdir -p "$prefix/node_modules/.bin" "$prefix/node_modules/@opencode/cli"
printf '{"name":"@opencode/cli","version":"2.3.4"}' > "$prefix/node_modules/@opencode/cli/package.json"
binary="$prefix/node_modules/@opencode/cli/opencode.exe"
printf '#!/bin/bash\nprintf "2.3.4\\n"\n' > "$binary"
chmod +x "$binary"
ln -s ../@opencode/cli/opencode.exe "$prefix/node_modules/.bin/opencode"
''' + ({"good": "", "fail": "exit 42", "wrong": "printf '{}' > \"$prefix/node_modules/@opencode/cli/package.json\"",
         "v1": "printf '{\"name\":\"@opencode/cli\",\"version\":\"1.9.0\"}' > \"$prefix/node_modules/@opencode/cli/package.json\"",
         "binary": "printf '#!/bin/bash\\nprintf wrong\\n' > \"$binary\"",
         "v2-output": "printf '#!/bin/bash\\nprintf \"opencode v2.3.4\\\\n\"\\n' > \"$binary\"",
        "relocation": "printf '#!/bin/bash\\n[[ $0 == */.build.* ]] || exit 23\\nprintf \"2.3.4\\\\n\"\\n' > \"$binary\""}[mode]))
        return self.shell(f'''source "{SCRIPTS / 'entrypoint.sh'}"
env() {{
    local -a args=(); local arg
    for arg in "$@"; do
        [[ $arg != /usr/bin/npm ]] || arg="{self.bin / 'npm-fixture'}"
        [[ $arg != /usr/bin/node ]] || arg="{shutil.which('node')}"
        [[ $arg != PATH=/usr/bin:/bin ]] || arg="PATH={self.bin}:/usr/bin:/bin"
        args+=("$arg")
    done
    /usr/bin/env "${{args[@]}}"
}}
load_contract
install_runtime
''', OPENAI_API_KEY="fake-provider-fixture", NODE_OPTIONS="--invalid-fixture",
                          OPENCODE_TEST_HOME="/fake", **env)

    def test_install_only_dirty_reapply_and_isolation(self):
        (self.repo / "user-edit").write_text("preserve")
        self.ok(self.install())
        self.assertEqual(os.readlink(self.prefix / "bin/opencode"), "../node_modules/.bin/opencode")
        self.assertEqual(json.loads((self.prefix / '.native-install.json').read_text()),
                         dict(package='@opencode/cli', requested='latest', version='2.3.4'))
        self.assertFalse((self.home / ".config").exists())
        self.assertEqual((self.repo / "user-edit").read_text(), "preserve")
        self.assertNotEqual(self.install("fail").returncode, 0)  # latest must resolve again
        self.assertEqual(self.ok(self.run_script("manage.sh", "version")).strip(), "2.3.4")
        self.assertNotIn(".runtime", self.git("status", "--porcelain"))

    def test_no_pin_required_or_used(self):
        for version in ("", "latest", "1.2.3;id"):
            self.ok(self.install(OPENCODE_VERSION=version))
        self.assertEqual(list(self.root.glob(".build.*")), [])

    def test_actual_v2_version_output_is_matched_to_metadata(self):
        self.assertIn('OpenCode 2.3.4 installed', self.ok(self.install('v2-output')))

    def test_install_requires_no_kdco_source_or_publication_helper(self):
        package = self.root / '.opencode/config/kdco'
        helper = self.root / 'scripts/publish-plugins.mjs'
        self.assertFalse(package.exists())
        self.assertFalse(helper.exists())
        self.ok(self.install())
        self.assertFalse(package.exists())
        self.assertFalse(helper.exists())
        self.assertFalse(any('kdco' in str(path.relative_to(self.root)) for path in self.root.rglob('*')))

    def test_failed_install_metadata_binary_and_relocation_restore(self):
        for mode in ("fail", "wrong", "v1", "binary", "relocation"):
            with self.subTest(mode=mode):
                self.package("1.0.0")
                result = self.install(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                expected = {"fail": "npm install failed", "wrong": "staged runtime verification failed", "v1": "staged runtime verification failed",
                            "binary": "staged runtime verification failed", "relocation": "previous runtime restored"}[mode]
                self.assertIn(expected, result.stderr)
                self.assertIn("1.0.0", (self.prefix / "node_modules/@opencode/cli/package.json").read_text())
                self.assertTrue(list(self.root.glob(".build.*")))

    def test_verification_uses_private_empty_home_and_all_xdg(self):
        self.package(body='''[[ $HOME != "''' + str(self.home) + '''" && $PWD == "$HOME" ]]
[[ $XDG_CONFIG_HOME == "$HOME/.config" && $XDG_DATA_HOME == "$HOME/.local/share" ]]
[[ $XDG_CACHE_HOME == "$HOME/.cache" && $XDG_STATE_HOME == "$HOME/.local/state" ]]
[[ ${OPENCODE_BIN_PATH-unset} == unset && ${OPENCODE_TEST_HOME-unset} == unset ]]
[[ ${NODE_OPTIONS-unset} == unset && ${NODE_PATH-unset} == unset ]]
[[ $OPENCODE_DISABLE_AUTOUPDATE == 1 && $1 == --version ]]
printf '2.3.4\\n' ''')
        self.ok(self.run_script("manage.sh", "version", OPENCODE_VERSION=""))

    def test_home_copy_once_formats_private_state_and_migration(self):
        config = self.home / ".config/opencode"
        config.mkdir(parents=True)
        (config / "opencode.jsonc").write_text("private-config")
        for rel in (".local/share/opencode/auth.json", ".cache/opencode/private", ".local/state/opencode/state"):
            path = self.home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake-private-fixture")
        previous = self.base / "old-checkout"
        (config / "commands").symlink_to(previous / "agent/commands")
        self.ok(self.install())  # must not initialize before migration input arrives
        self.assertNotEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        self.ok(self.run_script("entrypoint.sh", "initialize-home", OPENCODE_PREVIOUS_REPO=str(previous)))
        self.assertEqual(os.readlink(config / "commands"), str(self.repo / "agent/commands"))
        self.assertFalse((config / "opencode.json").exists())
        self.assertEqual((config / "opencode.jsonc").read_text(), "private-config")
        self.ok(self.run_script("entrypoint.sh", "initialize-home"))
        self.assertEqual((self.home / ".local/share/opencode/auth.json").read_text(), "fake-private-fixture")
        self.assertEqual((self.home / ".local/state/opencode/state").read_text(), "fake-private-fixture")
        self.assertEqual((self.home / ".cache/opencode/private").read_text(), "fake-private-fixture")

    def test_unknown_resources_and_redirected_plugins_preserved(self):
        config = self.home / ".config/opencode"
        (config / "commands").mkdir(parents=True)
        self.assertNotEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        self.assertTrue((config / "commands").is_dir())
        (config / "commands").rmdir()
        (config / "skills").symlink_to(self.workspace)
        self.assertNotEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        self.assertEqual(os.readlink(config / "skills"), str(self.workspace))
        (config / "skills").unlink()
        (config / "plugins").symlink_to(self.workspace)
        self.assertNotEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        self.assertFalse((self.workspace / "example.ts").exists())

    def test_default_format_and_known_legacy_links(self):
        legacy = self.home / ".agents"
        legacy.mkdir()
        (legacy / "commands").symlink_to(self.repo / "agent/commands")
        self.ok(self.run_script("entrypoint.sh", "initialize-home"))
        config = self.home / ".config/opencode"
        self.assertTrue((config / "opencode.json").exists())
        self.assertFalse((config / "opencode.jsonc").exists())
        self.assertFalse((legacy / "commands").is_symlink())

    def test_canonical_v2_assets_update_exact_managed_files_only(self):
        config = self.home / '.config/opencode'
        (config / 'plugins').mkdir(parents=True)
        title = config / 'plugins/first-prompt-title.js'
        title.write_text('{}')  # Exact original fixture's managed title.
        canonical = self.root / '.opencode/config/plugins/first-prompt-title.js'
        canonical.write_text('export default async () => ({ title: "V2" })')
        self.ok(self.run_script('entrypoint.sh', 'initialize-home'))
        self.assertTrue(title.is_symlink())
        self.assertEqual(title.read_text(), canonical.read_text())
        background = config / 'plugins/background-subagents.js'
        self.assertTrue(background.is_symlink())
        self.assertEqual(background.resolve(), self.root / '.opencode/config/plugins/background-subagents.js')
        self.assertTrue((config / 'cli.json').is_symlink())
        self.assertTrue((config / 'tui-plugins/session-title/tui.js').is_symlink())
        canonical.write_text('export default async () => ({ title: "updated V2" })')
        self.ok(self.run_script('entrypoint.sh', 'initialize-home'))
        self.assertEqual(title.read_text(), canonical.read_text())
        title.unlink()
        title.write_text('private modified plugin')
        self.assertIn('preserved modified title', self.run_script('entrypoint.sh', 'initialize-home').stderr)
        self.assertEqual(title.read_text(), 'private modified plugin')

    def test_background_plugin_known_links_migrate_and_unknown_content_is_preserved(self):
        config = self.home / '.config/opencode'
        (config / 'plugins').mkdir(parents=True)
        plugin = config / 'plugins/background-subagents.js'
        canonical = self.root / '.opencode/config/plugins/background-subagents.js'
        previous = self.base / 'previous-checkout'
        plugin.symlink_to(previous / 'opencode/.opencode/config/plugins/background-subagents.js')
        self.ok(self.run_script('entrypoint.sh', 'initialize-home', OPENCODE_PREVIOUS_REPO=str(previous)))
        self.assertEqual(os.readlink(plugin), str(canonical))
        canonical.write_text('export default { id: "background-subagents", setup() {} }')
        self.ok(self.run_script('entrypoint.sh', 'initialize-home'))
        self.assertEqual(plugin.read_text(), canonical.read_text())
        plugin.unlink()
        plugin.write_text('private background plugin')
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('preserved private V2 asset', result.stderr)
        self.assertEqual(plugin.read_text(), 'private background plugin')
        plugin.unlink()
        plugin.symlink_to(self.workspace / 'unknown.js')
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('preserved unknown asset', result.stderr)
        self.assertEqual(os.readlink(plugin), str(self.workspace / 'unknown.js'))

    def test_kdco_wrappers_and_private_cli_preserved_with_actionable_failure(self):
        config = self.home / '.config/opencode'
        (config / 'plugins').mkdir(parents=True)
        wrapper = config / 'plugins/kdco-worktree.ts'
        wrapper.symlink_to(self.base / 'old-kdco.ts')  # Even broken links must fail closed.
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertIn('retire it explicitly', result.stderr)
        self.assertTrue(wrapper.is_symlink())
        wrapper.unlink()
        cli = config / 'cli.json'
        cli.write_text('{"private":true}')
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertIn('preserved private V2 asset', result.stderr)
        self.assertEqual(cli.read_text(), '{"private":true}')

    def test_previous_release_home_promotes_exact_public_defaults_and_retires_owned_wrappers(self):
        # Immutable public release blobs, not synthetic empty config/re-exports.
        release = {
            'opencode.json': '128c14ec20beadf55d02eb2090ec3f485f6e9326',
            'plugins/kdco-background-agents.ts': 'cd4cba74209be01138a80d4ea2b4b86bd53d11f7',
            'plugins/kdco-worktree.ts': '87e7a38f724d8f37daf1daf6f0fff78f5ae6dffc',
            'plugins/kdco-notify.ts': '3558148fb56c9e1bfea671e12f80dbab54c0cdd1',
            'plugins/first-prompt-title.js': 'cfb2dc99bc6a0e9b71c2b62cee5804fc470d0ed9',
            'tui-plugins/session-title.mjs': 'dc3b5be5f0d2a4c0942a21f901a8ea5f48d0b524',
        }
        public = {name: subprocess.check_output(['git', '-C', str(COMPONENT), 'show', blob])
                  for name, blob in release.items()}
        self.assertIn('agent', json.loads(public['opencode.json']))
        canonical = self.root / '.opencode/config'
        for name in ('opencode.json', 'plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                     'tui-plugins/session-title.mjs'):
            shutil.copyfile(COMPONENT / '.opencode/config' / name, canonical / name)
        self.assertIn('agents', json.loads((canonical / 'opencode.json').read_text()))
        private = {}
        for relative in ('.local/share/opencode/auth.json', '.local/share/opencode/opencode.db',
                         '.local/state/opencode/private.json'):
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            private[path] = b'private-native-fixture\x00\xff'
            path.write_bytes(private[path])
        config = self.home / '.config/opencode'
        previous = self.base / 'previous-checkout'
        for format in ('opencode.json', 'opencode.jsonc'):
            with self.subTest(format=format):
                if config.exists():
                    shutil.rmtree(config)
                (config / 'plugins').mkdir(parents=True)
                (config / 'tui-plugins').mkdir()
                (config / format).write_bytes(public['opencode.json'])
                (config / 'plugins/kdco-background-agents.ts').write_bytes(public['plugins/kdco-background-agents.ts'])
                (config / 'plugins/kdco-worktree.ts').symlink_to(canonical / 'plugins/kdco-worktree.ts')
                (config / 'plugins/kdco-notify.ts').symlink_to(previous / 'opencode/.opencode/config/plugins/kdco-notify.ts')
                # Legacy helper package data is not auto-loaded and is not ours to delete.
                (config / 'kdco').mkdir()
                (config / 'kdco/private-package-data').write_bytes(b'leave me')
                for name in ('plugins/first-prompt-title.js', 'tui-plugins/session-title.mjs'):
                    (config / name).write_bytes(public[name])
                (config / 'tui.json').write_text('{"theme":"private-theme"}')
                self.ok(self.run_script('entrypoint.sh', 'initialize-home', OPENCODE_PREVIOUS_REPO=str(previous)))
                self.assertEqual((config / format).read_bytes(), (canonical / 'opencode.json').read_bytes())
                other = 'opencode.jsonc' if format == 'opencode.json' else 'opencode.json'
                self.assertFalse((config / other).exists())
                self.assertEqual(list((config / 'plugins').glob('kdco-*')), [])
                for name in ('plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                             'tui-plugins/session-title.mjs', 'cli.json'):
                    self.assertTrue((config / name).is_symlink())
                    self.assertEqual((config / name).resolve(), canonical / name)
                self.assertEqual((config / 'kdco/private-package-data').read_bytes(), b'leave me')
                self.assertEqual((config / 'tui.json').read_text(), '{"theme":"private-theme"}')
                self.ok(self.run_script('entrypoint.sh', 'initialize-home'))
                self.assertFalse(list(config.rglob('.opencode-default.*')))
                for path, content in private.items():
                    self.assertEqual(path.read_bytes(), content)

    def test_modified_previous_release_config_cli_and_wrapper_are_never_overwritten(self):
        public = subprocess.check_output(['git', '-C', str(COMPONENT), 'show',
                                          '128c14ec20beadf55d02eb2090ec3f485f6e9326'])
        config = self.home / '.config/opencode'
        (config / 'plugins').mkdir(parents=True)
        modified = public + b'\n '  # Even whitespace differs from the managed bytes.
        (config / 'opencode.jsonc').write_bytes(modified)
        wrapper = config / 'plugins/kdco-worktree.ts'
        wrapper.write_text('export { default } from "../kdco/worktree"\n// user customization\n')
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('modified V1 KDCO wrapper preserved', result.stderr)
        self.assertIn('user customization', wrapper.read_text())
        self.assertEqual((config / 'opencode.jsonc').read_bytes(), modified)
        wrapper.unlink()
        self.ok(self.run_script('entrypoint.sh', 'initialize-home'))
        self.assertEqual((config / 'opencode.jsonc').read_bytes(), modified)
        self.assertFalse((config / 'opencode.json').exists())
        cli = config / 'cli.json'
        cli.unlink()
        cli.write_text('{"theme":{"name":"private-theme"}}')
        result = self.run_script('entrypoint.sh', 'initialize-home')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cli.read_text(), '{"theme":{"name":"private-theme"}}')

    def test_runtime_prefix_redirect_preserved(self):
        self.prefix.symlink_to(self.workspace)
        result = self.install()
        self.assertIn('paths must be canonical', result.stderr)
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_service_session_argv_and_overrides_without_version(self):
        self.package(body='''printf 'cwd=%s\\nhome=%s\\nstate=%s\\nauto=%s\\n' "$PWD" "$HOME" "$XDG_STATE_HOME" "$OPENCODE_DISABLE_AUTOUPDATE"
[[ ${OPENCODE_BIN_PATH-unset} == unset && ${OPENCODE_TEST_HOME-unset} == unset && ${NODE_OPTIONS-unset} == unset && ${NODE_PATH-unset} == unset ]]
[[ $OPENCODE_PASSWORD == fake-service-fixture ]]
printf 'arg=%s\\n' "$@"''')
        env = dict(OPENCODE_VERSION="", OPENCODE_BIN_PATH="/fake", OPENCODE_TEST_HOME="/fake",
                   NODE_OPTIONS="--fake", NODE_PATH="/fake")
        out = self.ok(self.run_script("start.sh", "service", **env))
        self.assertIn("arg=serve\narg=--hostname\narg=127.0.0.1\narg=--port\narg=4096\n", out)
        self.assertIn(f"cwd={self.workspace}", out)
        self.assertIn(f"state={self.home}/.local/state", out)
        self.assertNotIn("fake-service-fixture", out)
        out = self.ok(self.run_script("start.sh", "session", "--prompt", "two words", "", **env))
        self.assertIn("arg=--server\narg=http://127.0.0.1:4096\n", out)
        self.assertIn("arg=--prompt\narg=two words\narg=\n", out)
        for mode in ("service", "session"):
            for port in ("", "80", "04096", "65536", "1;id"):
                self.assertNotEqual(self.run_script("start.sh", mode, OPENCODE_PORT=port).returncode, 0)
            self.assertNotEqual(self.run_script("start.sh", mode, OPENCODE_PASSWORD="", OPENCODE_SERVER_PASSWORD="").returncode, 0)
            self.assertNotEqual(self.run_script("start.sh", mode, OPENCODE_SERVER_USERNAME="custom").returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "session", "--server=http://other").returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", "extra").returncode, 0)

    def test_v2_password_env_takes_precedence_without_entering_argv(self):
        self.package(body='''[[ $OPENCODE_PASSWORD == native-v2-secret ]]
printf 'arg=%s\\n' "$@"''')
        for mode in ('service', 'session'):
            out = self.ok(self.run_script('start.sh', mode, OPENCODE_PASSWORD='native-v2-secret'))
            self.assertNotIn('secret', out)

    def prepare_update(self, collision=False):
        self.git("branch", "incoming")
        self.git("checkout", "-q", "incoming")
        if collision:
            self.package()
            self.git("add", "-f", "opencode/.runtime")
        else:
            (self.repo / "new-file").write_text("new")
        self.commit("incoming")
        target = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "assigned")
        # Separate local bare remote with assigned branch; no network involved.
        remote = self.base / "remote.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(remote)], check=True)
        subprocess.run(["git", "--git-dir", str(remote), "update-ref", "refs/heads/assigned", target], check=True)
        self.git("remote", "add", "origin", str(remote))
        return target

    def test_updates_real_git_ff_clean_branch_and_ignored_collision(self):
        target = self.prepare_update()
        self.package()
        self.ok(self.run_script("manage.sh", "update-check", target))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.first)
        self.ok(self.run_script("manage.sh", "update", target))
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "assigned")
        self.assertEqual(self.git("rev-parse", "HEAD"), target)
        (self.repo / "dirty").write_text("local")
        self.assertNotEqual(self.run_script("manage.sh", "update", target).returncode, 0)
        self.assertNotEqual(self.run_script("manage.sh", "update-check", target, OPENCODE_BRANCH="wrong").returncode, 0)

    def test_ignored_collision_refused(self):
        target = self.prepare_update(collision=True)
        self.package("1.0.0")
        result = self.run_script("manage.sh", "update", target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.first)
        self.assertIn("1.0.0", (self.prefix / "node_modules/@opencode/cli/package.json").read_text())

    def test_divergence_and_detached_refused(self):
        target = self.prepare_update()
        (self.repo / "local").write_text("local")
        self.commit("local")
        local = self.git("rev-parse", "HEAD")
        self.assertNotEqual(self.run_script("manage.sh", "update", target).returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD"), local)
        self.git("checkout", "-q", "--detach")
        self.assertNotEqual(self.run_script("manage.sh", "update-check", target).returncode, 0)

    def test_identity_home_layout_and_service_control_rejected(self):
        self.mock("stat", "printf '999999\\n'")
        self.assertIn("must own", self.run_script("entrypoint.sh", "initialize-home").stderr)
        (self.bin / "stat").unlink()
        self.assertNotEqual(self.run_script("entrypoint.sh", "install", OPENCODE_ROOT=str(self.base)).returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "session", OPENCODE_REPO=str(self.root)).returncode, 0)
        for command in ("start", "stop", "restart", "logs"):
            self.assertNotEqual(self.run_script("manage.sh", command).returncode, 0)
        self.mock("getent", f"printf '{self.user}:x:999999:999999::{self.home}:/bin/bash\\n'")
        self.assertIn("exact account UID", self.run_script("entrypoint.sh", "install").stderr)
        self.mock("getent", "printf 'root:x:0:0::/root:/bin/bash\\n'")
        self.assertIn("non-root account", self.run_script("entrypoint.sh", "install", OPENCODE_USER="root").stderr)

    def test_seed_failure_and_concurrent_file_preserved(self):
        config = self.home / ".config/opencode"
        for mode in ("failure", "concurrent"):
            body = f'''source "{SCRIPTS / 'entrypoint.sh'}"
load_contract
opencode_git() {{
    case "$1" in
        ls-files) printf '%s\\0' opencode/.opencode/config/opencode.json ;;
    esac
}}
cp() {{
    printf partial > "$3"
    [[ {mode} != failure ]] || return 42
    printf user-content > "$OPENCODE_CONFIG_DIR/opencode.json"
}}
initialize_home
'''
            result = self.shell(body)
            if mode == "failure":
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertFalse((config / "opencode.json").exists())
            else:
                self.ok(result)
                self.assertEqual((config / "opencode.json").read_text(), "user-content")
            self.assertEqual(list(config.glob(".opencode-default.*")), [])

    def test_status_is_read_only_and_preserves_failure(self):
        self.mock("systemctl-fixture", '''[[ $* == '--no-pager show --property=Id,LoadState,ActiveState,SubState opencode.service' ]]
[[ ${OPENCODE_SERVER_PASSWORD-unset} == unset ]]
printf 'ActiveState=inactive\\n'
exit 3''')
        # exec requires an executable env adapter, rather than a shell function.
        self.mock("env", f'''args=()
for arg in "$@"; do
    [[ $arg != /usr/bin/systemctl ]] || arg="{self.bin / 'systemctl-fixture'}"
    args+=("$arg")
done
exec /usr/bin/env "${{args[@]}}"''')
        result = self.run_script("manage.sh", "status")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout, "ActiveState=inactive\n")

    def test_busy_lock_and_redirected_state_refused(self):
        body = f'''source "{SCRIPTS / 'entrypoint.sh'}"
load_contract
deployment_lock
if /bin/bash "{SCRIPTS / 'entrypoint.sh'}" initialize-home; then exit 0; else exit $?; fi
'''
        self.assertIn("another lifecycle operation", self.shell(body).stderr)
        (self.home / ".local").mkdir()
        (self.home / ".local/state").symlink_to(self.workspace)
        result = self.run_script("entrypoint.sh", "initialize-home")
        self.assertIn("redirected private state", result.stderr)
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_promotion_rename_failure_restores_runtime(self):
        self.package("1.0.0")
        self.mock("mv", '''if [[ $2 == */runtime && $3 == */.runtime ]]; then exit 17; fi
exec /usr/bin/mv "$@"''')
        result = self.install()
        self.assertIn("runtime promotion failed", result.stderr)
        self.assertIn("1.0.0", (self.prefix / "node_modules/@opencode/cli/package.json").read_text())

    def test_global_layout_reapply_preserves_failure_then_rebuilds(self):
        self.package()
        (self.prefix / "lib").mkdir()
        (self.prefix / "node_modules").rename(self.prefix / "lib/node_modules")
        binary = self.prefix / "bin/opencode"
        binary.unlink()
        binary.symlink_to("../lib/node_modules/.bin/opencode")
        self.assertNotEqual(self.install("fail").returncode, 0)
        self.assertEqual(os.readlink(binary), "../lib/node_modules/.bin/opencode")
        self.assertEqual(self.ok(self.run_script("manage.sh", "version")).strip(), "2.3.4")
        self.ok(self.install())
        self.assertFalse((self.prefix / "lib").exists())
        self.assertEqual(os.readlink(binary), "../node_modules/.bin/opencode")
        self.ok(self.install())

    @unittest.skipUnless(shutil.which("npm") and shutil.which("node"), "requires real npm and Node")
    def test_real_npm_nested_fallback_global_fails_local_install_passes(self):
        # Two tiny tarballs, no registry dependencies. Real parent npm runs a
        # postinstall whose child install/read sequence mirrors the vendor's.
        fixture = self.base / "npm-fixture"
        fixture.mkdir()
        child = fixture / "child"
        child.mkdir()
        (child / "package.json").write_text(json.dumps(dict(name="fixture-platform", version="2.3.4")))
        (child / "opencode").write_text("#!/bin/bash\nprintf '2.3.4\\n'\n")
        (child / "opencode").chmod(0o755)
        child_tar = fixture / "child.tgz"
        with tarfile.open(child_tar, "w:gz") as archive:
            archive.add(child, arcname="package")
        parent = fixture / "parent"
        parent.mkdir()
        (parent / "package.json").write_text(json.dumps(dict(
            name="@opencode/cli", version="2.3.4", bin=dict(opencode="bin/opencode.exe"),
            scripts=dict(postinstall="node postinstall.cjs"))))
        # npm links declared bins before postinstall. Like the published parent,
        # include the bin file that postinstall will replace with the child binary.
        (parent / "bin").mkdir()
        (parent / "bin/opencode.exe").write_text("#!/bin/bash\nexit 99\n")
        (parent / "bin/opencode.exe").chmod(0o755)
        report = fixture / "report.json"
        (parent / "postinstall.cjs").write_text('''
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const {spawnSync} = require("node:child_process");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "fallback-"));
try {
    const child = spawnSync("npm", ["install", "--ignore-scripts", "--no-save",
        "--loglevel=error", "--prefix", temp, CHILD_TAR], {encoding: "utf8"});
    const expected = path.join(temp, "node_modules/fixture-platform/opencode");
    const globalPath = path.join(temp, "lib/node_modules/fixture-platform/opencode");
    fs.writeFileSync(REPORT, JSON.stringify({global: process.env.npm_config_global || "unset",
        childStatus: child.status, expected: fs.existsSync(expected),
        globalPath: fs.existsSync(globalPath), uid: process.getuid()}));
    if (child.status !== 0) throw Error(child.stderr);
    if (!fs.existsSync(expected)) throw Error("vendor-expected node_modules binary missing");
    fs.mkdirSync(path.join(__dirname, "bin"), {recursive: true});
    fs.copyFileSync(expected, path.join(__dirname, "bin/opencode.exe"));
    fs.chmodSync(path.join(__dirname, "bin/opencode.exe"), 0o755);
} finally { fs.rmSync(temp, {recursive: true, force: true}); }
'''.replace("CHILD_TAR", json.dumps(str(child_tar))).replace("REPORT", json.dumps(str(report))))
        parent_tar = fixture / "parent.tgz"
        with tarfile.open(parent_tar, "w:gz") as archive:
            archive.add(parent, arcname="package")

        npm, node = shutil.which("npm"), shutil.which("node")
        assert npm is not None and node is not None
        toolpath = f"{Path(npm).parent}:{Path(node).parent}:/usr/bin:/bin"
        userrc, globalrc = fixture / "userrc", fixture / "globalrc"
        userrc.touch()
        globalrc.touch()
        clean = dict(HOME=str(fixture), TMPDIR=str(fixture), PATH=toolpath,
                     NPM_CONFIG_USERCONFIG=str(userrc), NPM_CONFIG_GLOBALCONFIG=str(globalrc),
                     NPM_CONFIG_CACHE=str(fixture / "cache"), NPM_CONFIG_OFFLINE="true",
                     NPM_CONFIG_UPDATE_NOTIFIER="false",
                     NPM_CONFIG_AUDIT="false", NPM_CONFIG_FUND="false",
                     NPM_CONFIG_REGISTRY="https://registry.npmjs.org")
        # Negative control: global only inside this temporary prefix, never the
        # controller's global package store. No config files are modified.
        old = subprocess.run([npm, "install", "--global", "--prefix", str(fixture / "old"),
                              "--ignore-scripts=false", str(parent_tar)], cwd=fixture,
                             env=clean, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn("vendor-expected node_modules binary missing", old.stderr)
        self.assertEqual(json.loads(report.read_text()), dict(
            globalPath=True, expected=False, childStatus=0, uid=os.getuid(), **{"global": "true"}))

        # Exercise production install/verification/promotion. Adapt only the
        # runner's tool locations and the exact package spec to a local fixture;
        # keep npm mode, lifecycle, config and prefix flags from production.
        result = self.shell(f'''source "{SCRIPTS / 'entrypoint.sh'}"
env() {{
    local -a args=(); local arg
    for arg in "$@"; do
        case "$arg" in
            /usr/bin/npm) arg="{npm}" ;;
            /usr/bin/node) arg="{node}" ;;
            @opencode/cli@latest) arg="{parent_tar}" ;;
            PATH=/usr/bin:/bin) arg="PATH={toolpath}" ;;
        esac
        args+=("$arg")
        [[ $arg != -i ]] || args+=(NPM_CONFIG_OFFLINE=true NPM_CONFIG_UPDATE_NOTIFIER=false)
    done
    /usr/bin/env "${{args[@]}}"
}}
load_contract
install_runtime
''')
        logs = "\n".join(p.read_text() for p in self.root.glob(".build.*/*.log"))
        self.assertEqual(result.returncode, 0, result.stderr + logs)
        observed = json.loads(report.read_text())
        self.assertNotEqual(observed["global"], "true")
        self.assertEqual((observed["childStatus"], observed["expected"], observed["globalPath"]), (0, True, False))
        self.assertEqual(observed["uid"], os.getuid())
        self.assertEqual(os.readlink(self.prefix / "bin/opencode"), "../node_modules/.bin/opencode")
        self.assertEqual(self.ok(self.run_script("manage.sh", "version")).strip(), "2.3.4")

    @unittest.skipUnless(shutil.which("npm"), "requires npm; no install performed")
    def test_real_npm_distinct_empty_configs(self):
        userrc, globalrc = self.base / "userrc", self.base / "globalrc"
        userrc.touch()
        globalrc.touch()
        npm, node = shutil.which("npm"), shutil.which("node")
        assert npm is not None and node is not None
        result = subprocess.run([npm, "config", "get", "registry",
                                 f"--userconfig={userrc}", f"--globalconfig={globalrc}",
                                 "--registry=https://registry.npmjs.org"], cwd=self.home,
                                 env=dict(HOME=str(self.home), PATH=f"{Path(node).parent}:/usr/bin:/bin"), capture_output=True, text=True)
        self.assertEqual(self.ok(result).strip().rstrip("/"), "https://registry.npmjs.org")

    @unittest.skipUnless(os.environ.get('OPENCODE_NATIVE_TEST_BINARY'), 'opt-in isolated real V2 binary')
    def test_real_v2_server_password_and_explicit_client_connection(self):
        binary = Path(os.environ['OPENCODE_NATIVE_TEST_BINARY']).resolve()
        clean = dict(HOME=str(self.home), USER=self.user, LOGNAME=self.user, PATH='/usr/bin:/bin',
                     XDG_CONFIG_HOME=str(self.home / '.config'), XDG_DATA_HOME=str(self.home / '.local/share'),
                     XDG_CACHE_HOME=str(self.home / '.cache'), XDG_STATE_HOME=str(self.home / '.local/state'),
                     OPENCODE_CONFIG_DIR=str(self.home / '.config/opencode'), OPENCODE_DISABLE_AUTOUPDATE='1',
                     OPENCODE_PASSWORD='disposable-native-auth-fixture')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryFile() as logs:
            server = subprocess.Popen([str(binary), 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
                                      cwd=self.workspace, env=clean, stdout=logs, stderr=logs)
            try:
                url = f'http://127.0.0.1:{port}/api/info'

                def request(password):
                    auth = base64.b64encode(f'opencode:{password}'.encode()).decode()
                    return urllib.request.urlopen(urllib.request.Request(
                        url, headers={'Authorization': 'Basic ' + auth}), timeout=2)

                deadline = time.monotonic() + 45
                while True:
                    try:
                        with request(clean['OPENCODE_PASSWORD']) as response:
                            info = json.load(response)
                        break
                    except (OSError, urllib.error.URLError):
                        if server.poll() is not None or time.monotonic() >= deadline:
                            self.fail('isolated real V2 server failed readiness')
                        time.sleep(.2)
                self.assertTrue(info['version'].startswith('2.'))
                self.assertEqual(info['pid'], server.pid)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('wrong-password')
                self.assertEqual(error.exception.code, 401)
                # --help parses the real client's explicit connection flag without
                # opening a TUI, creating a conversation or spawning a local server.
                client = subprocess.run([str(binary), '--server', f'http://127.0.0.1:{port}', '--help'],
                                        cwd=self.workspace, env=clean, capture_output=True, text=True, timeout=15)
                self.ok(client)
                self.assertIn('--server', client.stdout)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


class RootGuard(unittest.TestCase):
    def test_root_guard_precedes_account_lookup(self):
        source = (SCRIPTS / "entrypoint.sh").read_text().split("load_contract() {", 1)[1]
        self.assertLess(source.index("$EUID != 0"), source.index("getent passwd"))
        if os.getuid() == 0:
            for script, command in (("entrypoint.sh", "install"), ("entrypoint.sh", "initialize-home"),
                                    ("start.sh", "session"), ("manage.sh", "status")):
                result = subprocess.run(["bash", str(SCRIPTS / script), command], env={"PATH": "/usr/bin:/bin"},
                                        capture_output=True, text=True)
                self.assertIn("never root", result.stderr)


if __name__ == "__main__":
    unittest.main()
