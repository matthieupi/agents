#!/bin/bash
set -euo pipefail
umask 077

validate_contract() {
    [[ ${HOME:-} == /home/t3code ]] || { printf '%s\n' 'HOME must be /home/t3code.' >&2; return 64; }
    [[ ${T3CODE_UID:-} =~ ^[1-9][0-9]{0,9}$ && ${T3CODE_GID:-} =~ ^[1-9][0-9]{0,9}$ ]] || {
        printf '%s\n' 'Explicit nonzero numeric T3CODE_UID and T3CODE_GID are required.' >&2; return 64;
    }
    [[ $(id -u) == "$T3CODE_UID" && $(id -g) == "$T3CODE_GID" ]] || {
        printf '%s\n' 'Container identity does not match T3CODE_UID/T3CODE_GID.' >&2; return 64;
    }
    [[ ${T3CODE_PORT:-} =~ ^[1-9][0-9]{0,4}$ ]] && (( T3CODE_PORT <= 65535 )) || {
        printf '%s\n' 'T3CODE_PORT must be an explicit canonical integer from 1 to 65535.' >&2; return 64;
    }
    [[ ${T3CODE_PROVIDER:-} == none ]] || {
        printf '%s\n' 'Only explicit T3CODE_PROVIDER=none is supported.' >&2; return 64;
    }
    for directory in /home /home/t3code /workspace /opt /opt/agent; do
        [[ -d "$directory" && ! -L "$directory" ]] || {
            printf '%s\n' 'Required mount or ancestor is absent, not a directory, or a symlink.' >&2; return 73;
        }
    done
}

initialize_home() {
    # Inspect only component-owned roots without following links. Worktrees can
    # legitimately contain repository symlinks; never traverse/rewrite their data.
    # The home must be exclusively assigned to this instance by its host wrapper.
    node --input-type=module <<'NODE'
import fs from 'node:fs';
const uid = process.getuid();
const gid = process.getgid();
function inspect(path) {
  const stat = fs.lstatSync(path);
  if (stat.isSymbolicLink() || stat.uid !== uid || stat.gid !== gid ||
      (stat.mode & 0o077) !== 0 || (!stat.isDirectory() && !stat.isFile()) ||
      (stat.isFile() && stat.nlink !== 1)) {
    throw new Error('Unsafe private home: reconcile ownership, permissions, links or special files offline; nothing is automatically repaired.');
  }
  return stat;
}
try {
  if (!inspect('/home/t3code').isDirectory()) throw new Error('Home must be a directory.');
  for (const path of ['/home/t3code/base', '/home/t3code/logs']) {
    try { fs.mkdirSync(path, { mode: 0o700 }); } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
    if (!inspect(path).isDirectory()) throw new Error('Required private directory conflicts with an existing file.');
  }
  for (const path of ['/home/t3code/base/userdata', '/home/t3code/base/worktrees', '/home/t3code/base/caches']) {
    try {
      if (!inspect(path).isDirectory()) throw new Error('Private data root must be a directory.');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  for (const path of ['/home/t3code/logs/server.log', '/home/t3code/.server.lock']) {
    const fd = fs.openSync(path, fs.constants.O_WRONLY | fs.constants.O_APPEND |
      fs.constants.O_CREAT | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600);
    try {
      const stat = fs.fstatSync(fd);
      if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== uid || stat.gid !== gid ||
          (stat.mode & 0o077) !== 0) throw new Error('Unsafe private log or server lock.');
    } finally { fs.closeSync(fd); }
  }
} catch {
  // Never print state filenames or upstream errors that might contain secrets.
  console.error('Private home initialization refused. Reconcile ownership, private permissions and file types offline; do not recursively chown or follow links.');
  process.exitCode = 73;
}
NODE
    /bin/bash /opt/t3/scripts/provider.sh initialize-home
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    [[ $# == 1 && $1 == initialize-home ]] || {
        printf '%s\n' 'Usage: entrypoint.sh initialize-home' >&2; exit 64;
    }
    validate_contract
    initialize_home
fi
