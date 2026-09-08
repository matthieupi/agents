"""One-shot POSIX helper, bundled as static `python3 -u -c` source (no install).

stdin MUST stay open after its one JSON line until the response; EOF cancels.
UTF-8 regular files only, no NUL, symlink components or hard-link aliases. Paths
are cwd-relative or canonical absolute; '..' is always rejected. cwd may be '/'.
Directory descriptors plus O_NOFOLLOW avoid following swapped symlink parents.
Optimistic hashes are not locks/CAS against concurrent writers. Patches validate
fully before effects, but replacements are atomic PER FILE, not a transaction.
Ordinary permission bits are preserved; ownership/ACLs/xattrs are not copied.
New parent directories must already exist. Staged patches are capped at 16 MiB
and 128 paths. Timeout fields are required on the wire (caller default 120000
ms, hard maximum 600000); request ingestion itself has a 120000 ms deadline.

Bash is NOT containment: it has the remote account's authority (including sudo
if authorized), can leave cwd, and runs login startup files. Owned process groups
are terminated on exit/cancel; intentionally setsid-detached children escape.
rg uses its own regex/glob engine, local ignore rules, no global ignore/config,
and does not follow symlinks. Search output is informational, not a read hash.

max_output_bytes bounds UTF-8 output; the entire encoded JSON line is also capped
at 128 KiB (including escaping/metadata). Reads set truncated for omitted lines,
offset > 1 (even beyond EOF on empty files), or byte/frame clipping. Only an
unclipped offset-1 read covering all lines reports truncated:false. Truncated
reads still hash the WHOLE file; callers MUST NOT cache that hash as a complete
read and must invalidate any prior cached hash for that path. expected must
explicitly include null for every newly created destination.
Patch hunks accept bare @@ or @@ exact anchor, not unified-diff numeric ranges;
context is exact/unique, no fuzzy matching. LF patch lines adapt to uniform CRLF
files. Mixed line endings are rejected for patches, preserved by exact edits.
No source text, command or regex is included in error diagnostics.
"""

import errno
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time

MAX_REQUEST = 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FRAME = 128 * 1024
MAX_PATCH_FILES = 128
MAX_STAGED = 16 * 1024 * 1024
DEFAULT_TIMEOUT = 120000
MAX_TIMEOUT = 600000


class Rejected(Exception):
    """Safe, constant diagnostic only."""


def require(condition, message):
    if not condition:
        raise Rejected(message)


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "invalid numeric bound")
    return value


def text(value):
    require(isinstance(value, str) and '\x00' not in value, "expected NUL-free text")
    try:
        data = value.encode('utf-8')
    except UnicodeError:
        raise Rejected("invalid UTF-8 text") from None
    require(len(data) <= MAX_FILE, "file size limit exceeded")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def canonical(value, cwd):
    require(isinstance(value, str) and value and '\x00' not in value,
            "invalid path")
    require('..' not in value.split('/'), "parent traversal rejected")
    path = os.path.normpath(os.path.join(cwd, value))
    require(path.startswith('/') and not path.startswith('//'), "invalid absolute path")
    require(os.path.commonpath([cwd, path]) == cwd, "path outside cwd")
    require(len(os.fsencode(path)) <= 4096, "path too long")
    return path


def open_directory(path):
    """Walk from / without following any symlink component, even within cwd."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.split('/'):
            if part:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=fd)
                os.close(fd)
                fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def load_at(fd, name):
    try:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None, None
    with os.fdopen(source, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "requires regular file without hard-link aliases")
        require(info.st_size <= MAX_FILE, "file size limit exceeded")
        data = stream.read(MAX_FILE + 1)
        require(len(data) <= MAX_FILE, "file size limit exceeded")
        try:
            decoded = data.decode('utf-8')
        except UnicodeError:
            raise Rejected("file is not UTF-8 text") from None
        require('\x00' not in decoded, "binary file rejected")
        return data, stat.S_IMODE(info.st_mode) & 0o777


def load(path):
    fd = open_directory(os.path.dirname(path))
    try:
        return load_at(fd, os.path.basename(path))
    finally:
        os.close(fd)


def checked(path, expected):
    require(path in expected, "read required: missing expected hash")
    data, mode = load(path)
    require(digest(data) == expected[path], "conflict: expected hash differs")
    return data, mode


def atomic_change(path, data, expected, mode):
    """Recheck immediately before replacement; never truncate a live file."""
    fd = open_directory(os.path.dirname(path))
    temporary = None
    try:
        name = os.path.basename(path)
        current, _ = load_at(fd, name)
        require(digest(current) == expected[path], "conflict: expected hash differs")
        if data is None:
            os.unlink(name, dir_fd=fd)
            return
        # Random exclusive name in the already-open parent, not a path alias.
        for _ in range(10):
            candidate = '.opencode-' + os.urandom(16).hex()
            try:
                out = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                              0o600, dir_fd=fd)
                temporary = candidate
                break
            except FileExistsError:
                continue
        else:
            raise Rejected("unable to create atomic replacement")
        with os.fdopen(out, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode if mode is not None else 0o600)
            os.fsync(stream.fileno())
        current, _ = load_at(fd, name)
        require(digest(current) == expected[path], "conflict: expected hash differs")
        if expected[path] is None:
            # link rather than replace ensures a concurrently created file wins.
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd,
                    follow_symlinks=False)
            os.unlink(temporary, dir_fd=fd)
        else:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        temporary = None
        os.fsync(fd)
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=fd)
        os.close(fd)


def unique_index(lines, wanted, start=0):
    require(wanted, "patch requires nonempty exact context")
    match = None
    for i in range(start, len(lines) - len(wanted) + 1):
        if lines[i:i + len(wanted)] == wanted:
            require(match is None, "ambiguous patch context")
            match = i
    require(match is not None, "patch context not found")
    return match


def patch_update(data, hunks):
    source = data.decode('utf-8')
    crlf = '\r\n' in source
    require(not crlf or ('\n' not in source.replace('\r\n', '') and
                         '\r' not in source.replace('\r\n', '')),
            "mixed line endings unsupported in patch")
    require(crlf or '\r' not in source, "unsupported patch line endings")
    newline = '\r\n' if crlf else '\n'
    ended = source.endswith(newline)
    lines = source.split(newline)
    if ended:
        lines.pop()
    if not source:
        lines = []
    cursor = 0
    i = 0
    require(hunks, "update requires hunks")
    while i < len(hunks):
        header = hunks[i]
        require(header == '@@' or header.startswith('@@ '), "unsupported patch hunk")
        if header != '@@':
            anchor = header[3:]
            require(not re.match(r'[-+]\d', anchor), "numeric diff ranges unsupported")
            cursor = unique_index(lines, [anchor], cursor) + 1
        i += 1
        old, new = [], []
        changed = False
        at_end = False
        while i < len(hunks) and not hunks[i].startswith('@@'):
            line = hunks[i]
            i += 1
            if line == '*** End of File':
                require(i == len(hunks), "invalid end-of-file marker")
                at_end = True
                break
            require(line and line[0] in ' +-', "unsupported patch line")
            if line[0] in ' -':
                old.append(line[1:])
            if line[0] in ' +':
                new.append(line[1:])
            changed |= line[0] in '+-'
        require(changed, "empty patch hunk")
        index = unique_index(lines, old, cursor)
        require(not at_end or index + len(old) == len(lines), "EOF context not at EOF")
        lines[index:index + len(old)] = new
        cursor = index + len(new)
    return text(newline.join(lines) + (newline if ended and lines else ''))


def plan_patch(patch, cwd, expected):
    text(patch)
    require('\r' not in patch, "patch framing must use LF")
    lines = patch.split('\n')
    if lines[-1] == '':
        lines.pop()
    require(len(lines) >= 3 and lines[0] == '*** Begin Patch' and
            lines[-1] == '*** End Patch', "invalid patch framing")
    changes = {}
    i = 1

    def add(path, data, mode):
        require(path not in changes, "duplicate patch path")
        require(len(changes) < MAX_PATCH_FILES, "too many patch paths")
        changes[path] = (data, mode)
        require(sum(len(item[0]) for item in changes.values() if item[0] is not None)
                <= MAX_STAGED, "patch staged size limit exceeded")

    while i < len(lines) - 1:
        match = re.fullmatch(r'\*\*\* (Add|Delete|Update) File: (.+)', lines[i])
        require(match is not None, "unsupported patch section")
        kind, raw = match.groups()
        path = canonical(raw, cwd)
        original, mode = checked(path, expected)
        i += 1
        destination = None
        if i < len(lines) - 1 and lines[i].startswith('*** Move to: '):
            require(kind == 'Update', "move requires update")
            destination = canonical(lines[i][13:], cwd)
            dest_data, _ = checked(destination, expected)
            require(dest_data is None and destination != path, "move destination must be absent")
            i += 1
        body = []
        while i < len(lines) - 1:
            if lines[i].startswith('*** ') and lines[i] != '*** End of File':
                break
            body.append(lines[i])
            i += 1
        if kind == 'Add':
            require(original is None, "add target already exists")
            require(all(line.startswith('+') for line in body), "invalid add body")
            add(path, text(''.join(line[1:] + '\n' for line in body)), None)
        elif kind == 'Delete':
            require(original is not None and not body, "invalid delete section")
            add(path, None, mode)
        else:
            require(original is not None, "update target missing")
            updated = patch_update(original, body)
            if destination:
                add(destination, updated, mode)
                add(path, None, mode)
            else:
                add(path, updated, mode)
    require(changes, "empty patch")
    return changes


def stop_group(process):
    """Always clean the group, even when its leader already exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    time.sleep(0.15)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def run_process(argv, cwd, cap, timeout_ms):
    deadline = time.monotonic() + timeout_ms / 1000
    process = None
    selector = selectors.DefaultSelector()
    output = bytearray()
    truncated = False
    try:
        # One-shot process: inherit the validated directory by descriptor rather
        # than having Popen resolve a potentially swapped pathname a second time.
        directory = open_directory(cwd)
        try:
            os.fchdir(directory)
        finally:
            os.close(directory)
        # Defer Python exceptions until we own the returned process. Do NOT mask
        # OS signals: that mask would be inherited by the executed child.
        pending = []
        previous = {s: signal.signal(s, lambda signum, _: pending.append(signum)) for s in
                    (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP, signal.SIGUSR1)}
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
        if pending:
            raise Rejected('operation timed out' if signal.SIGALRM in pending
                           else 'operation cancelled')
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            require(time.monotonic() < deadline, "operation timed out")
            for key, _ in selector.select(0.05):
                chunk = os.read(key.fd, 16384)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                # Never expose rg stderr: it can reproduce private regex/input.
                if key.fileobj is process.stderr and argv[0] == 'rg':
                    continue
                room = cap - len(output)
                output.extend(chunk[:room])
                truncated |= len(chunk) > room
        return output.decode('utf-8', errors='replace'), process.wait(), truncated
    finally:
        selector.close()
        if process is not None:
            # Cleanup cannot itself be interrupted by the deadline/cancel signal.
            deferred = []
            old = {s: signal.signal(s, lambda signum, _: deferred.append(signum)) for s in
                   (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP, signal.SIGUSR1)}
            try:
                stop_group(process)
                process.stdout.close()
                process.stderr.close()
            finally:
                for s, handler in old.items():
                    signal.signal(s, handler)
            if deferred:
                raise Rejected('operation timed out' if signal.SIGALRM in deferred
                               else 'operation cancelled')


def frame(response, cap):
    def encode():
        return json.dumps(response, ensure_ascii=True, separators=(',', ':')).encode() + b'\n'
    if response['ok']:
        output = response['output']
        clipped = output.encode('utf-8')[:cap].decode('utf-8', errors='ignore')
        if clipped != output:
            response['truncated'] = True
        response['output'] = clipped
        if len(encode()) > MAX_FRAME:
            response['truncated'] = True
            low, high = 0, len(clipped)
            while low < high:
                middle = (low + high + 1) // 2
                response['output'] = clipped[:middle]
                if len(encode()) <= MAX_FRAME:
                    low = middle
                else:
                    high = middle - 1
            response['output'] = clipped[:low]
    require(len(encode()) <= MAX_FRAME, "response metadata too large")
    return encode()


def dispatch(request):
    require(os.geteuid() != 0, "privileged helper execution rejected")
    require(isinstance(request, dict) and set(request) == {
        'operation', 'cwd', 'args', 'expected', 'timeout_ms', 'max_output_bytes'},
        "invalid request fields")
    timeout = integer(request['timeout_ms'], 1, MAX_TIMEOUT)
    cap = integer(request['max_output_bytes'], 1, MAX_FRAME)
    require(isinstance(request['cwd'], str) and os.path.isabs(request['cwd']), "cwd must be absolute")
    cwd = canonical(request['cwd'], '/')
    require(cwd == request['cwd'], "cwd must be canonical")
    fd = open_directory(cwd)
    os.close(fd)
    args, expected, operation = request['args'], request['expected'], request['operation']
    require(isinstance(args, dict) and isinstance(expected, dict), "invalid request objects")
    for path, hash_value in expected.items():
        require(canonical(path, cwd) == path, "expected keys must be canonical absolute paths")
        require(hash_value is None or isinstance(hash_value, str) and
                re.fullmatch('[0-9a-f]{64}', hash_value), "invalid expected hash")
    surfaces = {
        'read': ({'filePath'}, {'offset', 'limit'}),
        'write': ({'filePath', 'content'}, set()),
        'edit': ({'filePath', 'oldString', 'newString'}, {'replaceAll'}),
        'apply_patch': ({'patchText'}, set()),
        'glob': ({'pattern'}, {'path'}),
        'grep': ({'pattern'}, {'path', 'include'}),
        'bash': ({'command'}, {'workdir', 'timeout', 'description'}),
    }
    require(isinstance(operation, str) and operation in surfaces, "unsupported operation")
    required, optional = surfaces[operation]
    require(required <= set(args) <= required | optional, "invalid tool arguments")
    response = {'ok': True, 'output': '', 'files': []}
    changes = {}
    if operation == 'read':
        path = canonical(args['filePath'], cwd)
        data, _ = load(path)
        require(data is not None, "file not found")
        offset = integer(args.get('offset', 1), 1, MAX_FILE)
        limit = integer(args.get('limit', 2000), 1, MAX_FILE)
        lines = data.decode('utf-8').splitlines(keepends=True)
        response['output'] = ''.join(lines[offset - 1:offset - 1 + limit])
        response['truncated'] = offset > 1 or offset - 1 + limit < len(lines)
        response['files'] = [{'path': path, 'sha256': digest(data)}]
    elif operation in ('write', 'edit'):
        path = canonical(args['filePath'], cwd)
        data, mode = checked(path, expected)
        if operation == 'write':
            updated = text(args['content'])
        else:
            require(data is not None, "edit target missing")
            old, new = text(args['oldString']), text(args['newString'])
            replace_all = args.get('replaceAll', False)
            require(type(replace_all) is bool and old, "invalid edit arguments")
            # Adapt LF tool strings only for uniformly CRLF files, not mixed ones.
            if b'\r\n' in data and b'\n' not in data.replace(b'\r\n', b'') and b'\r' not in data.replace(b'\r\n', b''):
                if b'\r' not in old:
                    old = old.replace(b'\n', b'\r\n')
                if b'\r' not in new:
                    new = new.replace(b'\n', b'\r\n')
            count = data.count(old)
            unique = count == 1 and data.find(old, data.find(old) + 1) == -1
            require(count > 0 and (replace_all or unique), "edit context missing or ambiguous")
            require(len(data) + count * (len(new) - len(old)) <= MAX_FILE,
                    "file size limit exceeded")
            updated = data.replace(old, new, -1 if replace_all else 1)
            require(len(updated) <= MAX_FILE, "file size limit exceeded")
        changes[path] = (updated, mode)
    elif operation == 'apply_patch':
        changes = plan_patch(args['patchText'], cwd, expected)
    else:
        directory = canonical(args.get('workdir' if operation == 'bash' else 'path', cwd), cwd)
        if operation == 'bash':
            text(args['command'])
            if 'description' in args:
                text(args['description'])
            timeout = min(timeout, integer(args.get('timeout', timeout), 1, MAX_TIMEOUT))
            argv = ['/bin/bash', '-lc', args['command']]
        else:
            text(args['pattern'])
            argv = ['rg', '--no-config', '--no-ignore-global', '--no-ignore-parent',
                    '--no-follow', '--color=never']
            if operation == 'glob':
                argv += ['--files', '-g', args['pattern']]
            else:
                argv += ['--line-number', '--with-filename', '--no-heading',
                         '--max-filesize', str(MAX_FILE), '--regexp', args['pattern']]
                if 'include' in args:
                    text(args['include'])
                    argv += ['-g', args['include']]
            argv += ['--', '.']
        output, code, truncated = run_process(argv, directory, cap, timeout)
        require(operation == 'bash' or code in (0, 1), "rg failed: invalid pattern or search error")
        response.update(output=output, exit_code=code, truncated=truncated)
    if changes:
        response['files'] = [{'path': path, 'sha256': digest(data)}
                             for path, (data, _) in changes.items()]
        response['output'] = 'Applied changes.'
        frame(dict(response), cap)  # metadata must fit BEFORE effects
        # A second full preflight catches conflicts since patch parsing.
        for path in changes:
            checked(path, expected)
        for path, (data, mode) in changes.items():
            atomic_change(path, data, expected, mode)
    return response


def main():
    completed = threading.Event()

    def interrupt(signum, _frame):
        if not completed.is_set():
            raise Rejected('operation timed out' if signum == signal.SIGALRM else 'operation cancelled')

    def monitor():
        try:
            while not completed.is_set():
                os.read(0, 4096)  # EOF or unexpected additional input cancels.
                if not completed.is_set():
                    os.kill(os.getpid(), signal.SIGUSR1)
                return
        except OSError:
            if not completed.is_set():
                os.kill(os.getpid(), signal.SIGUSR1)

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGALRM, signal.SIGUSR1):
        signal.signal(sig, interrupt)
    signal.setitimer(signal.ITIMER_REAL, DEFAULT_TIMEOUT / 1000)
    cap = MAX_FRAME
    try:
        raw = bytearray()
        while b'\n' not in raw:
            chunk = os.read(0, min(4096, MAX_REQUEST + 1 - len(raw)))
            require(chunk, "request missing or disconnected")
            raw.extend(chunk)
            require(len(raw) <= MAX_REQUEST, "request size limit exceeded")
        require(raw.endswith(b'\n') and raw.count(b'\n') == 1, "requires one JSON line")
        threading.Thread(target=monitor, daemon=True).start()

        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, "duplicate JSON key")
                result[key] = value
            return result

        request = json.loads(raw, object_pairs_hook=pairs)
        require(isinstance(request, dict), "invalid request")
        timeout = integer(request.get('timeout_ms'), 1, MAX_TIMEOUT)
        cap = integer(request.get('max_output_bytes'), 1, MAX_FRAME)
        signal.setitimer(signal.ITIMER_REAL, timeout / 1000)
        response = dispatch(request)
        encoded = frame(response, cap)
    except Rejected as exc:
        encoded = frame({'ok': False, 'error': str(exc)}, cap)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        encoded = frame({'ok': False, 'error': 'invalid request or text encoding'}, cap)
    except OSError as exc:
        message = 'filesystem or subprocess operation failed'
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            message = 'symlink or non-directory path rejected'
        encoded = frame({'ok': False, 'error': message}, cap)
    except Exception:
        encoded = frame({'ok': False, 'error': 'helper operation failed'}, cap)
    finally:
        completed.set()  # normal transport close after response is NOT cancellation
        signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    except (BrokenPipeError, OSError):
        pass


if __name__ == '__main__':
    main()
