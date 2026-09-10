"""Real non-root shell/Git/env tests; fake packages only, no network or host changes."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import unittest

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
        shutil.copyfile(SCRIPTS / 'publish-plugins.mjs', self.root / 'scripts/publish-plugins.mjs')
        self.workspace = self.base / "project with spaces"
        self.workspace.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / 'node').symlink_to(shutil.which('node'))
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
        (defaults / 'kdco').mkdir()
        (defaults / 'kdco/package.json').write_text('{"name":"fixture","version":"1.0.0","private":true}')
        (defaults / 'kdco/package-lock.json').write_text('{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture","version":"1.0.0"}}}')
        for name in ('background-agents', 'worktree', 'notify'):
            (defaults / f'plugins/kdco-{name}.ts').write_text('export default async () => ({})')
        for name in ("opencode.json", "opencode.jsonc", "tui.json", "plugins/example.ts"):
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
        package = self.prefix / "node_modules/opencode-ai"
        package.mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(json.dumps(dict(name="opencode-ai", version=version)))
        binary = package / "opencode"
        binary.write_text("#!/bin/bash\nset -eu\n" + (body or f"printf '%s\\n' '{version}'") + "\n")
        binary.chmod(0o755)
        (self.prefix / "node_modules/.bin").mkdir(exist_ok=True)
        for link, target in ((self.prefix / "node_modules/.bin/opencode", "../opencode-ai/opencode"),
                             (self.prefix / "bin/opencode", "../node_modules/.bin/opencode")):
            if not link.is_symlink():
                link.symlink_to(target)

    def install(self, mode="good", **env):
        # Intercept env only to substitute npm's executable AFTER production has
        # constructed its actual env -i arguments. Node, env, Git and shell are real.
        self.mock("npm-fixture", r'''
if [[ $1 == ci ]]; then
    [[ " $* " == *" --ignore-scripts "* ]]
    prefix=''
    while (($#)); do if [[ $1 == --prefix ]]; then prefix=$2; shift; fi; shift; done
    [[ -f "$prefix/package-lock.json" ]] || exit 42
    mkdir -p "$prefix/node_modules"
    if [[ -f "$prefix/fail-install" ]]; then
        printf partial > "$prefix/node_modules/fixture"
        exit 42
    fi
    printf locked > "$prefix/node_modules/fixture"
    exit 0
fi
[[ $EUID != 0 && $HOME == "$PWD" && $HOME == */.build.*/home ]]
[[ ${OPENCODE_SERVER_PASSWORD-unset} == unset && ${NODE_OPTIONS-unset} == unset ]]
[[ ${OPENCODE_TEST_HOME-unset} == unset && ${OPENAI_API_KEY-unset} == unset ]]
[[ $XDG_STATE_HOME == "$HOME/.local/state" && $XDG_CACHE_HOME == "$HOME/.cache" ]]
[[ $NPM_CONFIG_REGISTRY == https://registry.npmjs.org ]]
[[ $NPM_CONFIG_USERCONFIG != "$NPM_CONFIG_GLOBALCONFIG" ]]
[[ -f $NPM_CONFIG_USERCONFIG && ! -s $NPM_CONFIG_USERCONFIG && -f $NPM_CONFIG_GLOBALCONFIG && ! -s $NPM_CONFIG_GLOBALCONFIG ]]
[[ " $* " == *" --ignore-scripts=false "* && " $* " == *" --include=optional "* ]]
[[ " $* " != *" --global "* && " $* " == *" --no-save "* && " $* " == *" --package-lock=false "* ]]
[[ ${!#} == opencode-ai@2.3.4 ]]
prefix=''
while (($#)); do if [[ $1 == --prefix ]]; then prefix=$2; shift; fi; shift; done
mkdir -p "$prefix/node_modules/.bin" "$prefix/node_modules/opencode-ai"
printf '{"name":"opencode-ai","version":"2.3.4"}' > "$prefix/node_modules/opencode-ai/package.json"
binary="$prefix/node_modules/opencode-ai/opencode"
printf '#!/bin/bash\nprintf "2.3.4\\n"\n' > "$binary"
chmod +x "$binary"
ln -s ../opencode-ai/opencode "$prefix/node_modules/.bin/opencode"
''' + ({"good": "", "fail": "exit 42", "wrong": "printf '{}' > \"$prefix/node_modules/opencode-ai/package.json\"",
        "binary": "printf '#!/bin/bash\\nprintf wrong\\n' > \"$binary\"",
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
        self.assertFalse((self.home / ".config").exists())
        self.assertEqual((self.repo / "user-edit").read_text(), "preserve")
        self.ok(self.install("fail"))  # matching runtime reused; npm must not run
        self.assertEqual(list(self.root.glob(".build.*")), [])
        self.assertNotIn(".runtime", self.git("status", "--porcelain"))

    def test_bad_pins_fail_before_staging(self):
        for version in ("", "latest", "1.2", "1.2.3-beta", "01.2.3", "1.2.3;id"):
            self.assertNotEqual(self.run_script("entrypoint.sh", "install", OPENCODE_VERSION=version).returncode, 0)
        self.assertEqual(list(self.root.glob(".build.*")), [])

    def test_missing_or_damaged_plugin_dependencies_reinstall_without_binary_rebuild(self):
        for damaged in (False, True):
            self.package()
            marker = self.root / '.opencode/config/kdco/node_modules/fixture'
            marker.parent.mkdir(exist_ok=True)
            marker.write_text('locked')
            if damaged:
                marker.write_text("broken")
            else:
                marker.unlink()
            self.ok(self.install("fail"))
            self.assertTrue((self.prefix / "bin/opencode").exists())
            self.ok(self.install())
            self.assertEqual(marker.read_text(), "locked")

    def test_plugin_install_failure_reports_only_executable_preservation(self):
        self.package("1.0.0")
        (self.root / '.opencode/config/kdco/package-lock.json').unlink()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("executable unchanged, dependencies may be incomplete", result.stderr)
        self.assertNotIn("existing runtime preserved", result.stderr)
        self.assertIn('1.0.0', (self.prefix / "node_modules/opencode-ai/package.json").read_text())

    def test_redirected_plugin_source_refused_before_dependency_install(self):
        package = self.root / '.opencode/config/kdco'
        outside = self.base / 'private-package'
        package.rename(outside)
        package.symlink_to(outside)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('preserved redirected', result.stderr)
        self.assertFalse((outside / 'node_modules').exists())

    def test_failed_in_place_dependency_update_is_not_reported_as_runtime_rollback(self):
        self.ok(self.install())
        package = self.root / '.opencode/config/kdco'
        lock = package / 'package-lock.json'
        lock.write_text(lock.read_text() + '\n')
        (package / 'fail-install').touch()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('executable unchanged, dependencies may be incomplete', result.stderr)
        self.assertEqual((package / 'node_modules/fixture').read_text(), 'partial')
        self.assertFalse((package / '.kdco-install.json').exists())
        self.assertEqual(json.loads((self.prefix / 'node_modules/opencode-ai/package.json').read_text())['version'], '2.3.4')
        (package / 'fail-install').unlink()
        self.ok(self.install())
        self.assertEqual((package / 'node_modules/fixture').read_text(), 'locked')

    def test_failed_install_metadata_binary_and_relocation_restore(self):
        for mode in ("fail", "wrong", "binary", "relocation"):
            with self.subTest(mode=mode):
                self.package("1.0.0")
                result = self.install(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                expected = {"fail": "npm install failed", "wrong": "staged runtime verification failed",
                            "binary": "staged runtime verification failed", "relocation": "previous runtime restored"}[mode]
                self.assertIn(expected, result.stderr)
                self.assertIn("1.0.0", (self.prefix / "node_modules/opencode-ai/package.json").read_text())
                self.assertTrue(list(self.root.glob(".build.*")))

    def test_verification_uses_private_empty_home_and_all_xdg(self):
        self.package(body='''[[ $HOME != "''' + str(self.home) + '''" && $PWD == "$HOME" ]]
[[ $XDG_CONFIG_HOME == "$HOME/.config" && $XDG_DATA_HOME == "$HOME/.local/share" ]]
[[ $XDG_CACHE_HOME == "$HOME/.cache" && $XDG_STATE_HOME == "$HOME/.local/state" ]]
[[ ${OPENCODE_BIN_PATH-unset} == unset && ${OPENCODE_TEST_HOME-unset} == unset ]]
[[ ${NODE_OPTIONS-unset} == unset && ${NODE_PATH-unset} == unset ]]
[[ $OPENCODE_DISABLE_AUTOUPDATE == 1 && $1 == --version ]]
printf '2.3.4\\n' ''')
        self.ok(self.install("fail"))
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

    def test_service_session_argv_and_overrides_without_version(self):
        self.package(body='''printf 'cwd=%s\\nhome=%s\\nstate=%s\\nauto=%s\\n' "$PWD" "$HOME" "$XDG_STATE_HOME" "$OPENCODE_DISABLE_AUTOUPDATE"
[[ ${OPENCODE_BIN_PATH-unset} == unset && ${OPENCODE_TEST_HOME-unset} == unset && ${NODE_OPTIONS-unset} == unset && ${NODE_PATH-unset} == unset ]]
printf 'arg=%s\\n' "$@"''')
        env = dict(OPENCODE_VERSION="", OPENCODE_BIN_PATH="/fake", OPENCODE_TEST_HOME="/fake",
                   NODE_OPTIONS="--fake", NODE_PATH="/fake")
        out = self.ok(self.run_script("start.sh", "service", **env))
        self.assertIn("arg=web\narg=--hostname\narg=127.0.0.1\narg=--port\narg=4096\narg=--mdns\narg=false", out)
        self.assertIn(f"cwd={self.workspace}", out)
        self.assertIn(f"state={self.home}/.local/state", out)
        self.assertNotIn("fake-service-fixture", out)
        out = self.ok(self.run_script("start.sh", "session", "--prompt", "two words", "", **env))
        self.assertIn("arg=--prompt\narg=two words\narg=\n", out)
        for port in ("80", "04096", "65536", "1;id"):
            self.assertNotEqual(self.run_script("start.sh", "service", OPENCODE_PORT=port).returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", OPENCODE_SERVER_PASSWORD="").returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", "extra").returncode, 0)

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
        self.assertIn("1.0.0", (self.prefix / "node_modules/opencode-ai/package.json").read_text())

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
        ls-files) printf '%s\\0' opencode/.opencode/config/tui.json ;;
        show)
            printf partial
            [[ {mode} != failure ]] || return 42
            printf user-content > "$OPENCODE_CONFIG_DIR/tui.json" ;;
    esac
}}
initialize_home
'''
            result = self.shell(body)
            if mode == "failure":
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertFalse((config / "tui.json").exists())
            else:
                self.ok(result)
                self.assertEqual((config / "tui.json").read_text(), "user-content")
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
        self.assertIn("1.0.0", (self.prefix / "node_modules/opencode-ai/package.json").read_text())

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
        self.ok(self.install("fail"))  # local layout is now reusable

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
            name="opencode-ai", version="2.3.4", bin=dict(opencode="bin/opencode"),
            scripts=dict(postinstall="node postinstall.cjs"))))
        # npm links declared bins before postinstall. Like the published parent,
        # include the bin file that postinstall will replace with the child binary.
        (parent / "bin").mkdir()
        (parent / "bin/opencode").write_text("#!/bin/bash\nexit 99\n")
        (parent / "bin/opencode").chmod(0o755)
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
    fs.copyFileSync(expected, path.join(__dirname, "bin/opencode"));
    fs.chmodSync(path.join(__dirname, "bin/opencode"), 0o755);
} finally { fs.rmSync(temp, {recursive: true, force: true}); }
'''.replace("CHILD_TAR", json.dumps(str(child_tar))).replace("REPORT", json.dumps(str(report))))
        parent_tar = fixture / "parent.tgz"
        with tarfile.open(parent_tar, "w:gz") as archive:
            archive.add(parent, arcname="package")

        npm, node = shutil.which("npm"), shutil.which("node")
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
            opencode-ai@2.3.4) arg="{parent_tar}" ;;
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
        result = subprocess.run([shutil.which("npm"), "config", "get", "registry",
                                 f"--userconfig={userrc}", f"--globalconfig={globalrc}",
                                 "--registry=https://registry.npmjs.org"], cwd=self.home,
                                env=dict(HOME=str(self.home), PATH=f"{Path(shutil.which('node')).parent}:/usr/bin:/bin"), capture_output=True, text=True)
        self.assertEqual(self.ok(result).strip().rstrip("/"), "https://registry.npmjs.org")


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
