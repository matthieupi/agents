import { readFile, open } from 'node:fs/promises';
import { constants } from 'node:fs';
import { Client } from 'ssh2';
import { StringDecoder } from 'node:string_decoder';

export const MAX_INPUT = 1024 * 1024;
export const MAX_OUTPUT = 32 * 1024;
const MAX_WIRE = MAX_OUTPUT * 8 + 65536;

// Only trusted, bundled code enters the shell command. All data travels on stdin.
export async function runRemote(target, request, { signal } = {}) {
  const payload = JSON.stringify(request) + '\n';
  if (Buffer.byteLength(payload) > MAX_INPUT) throw new Error('Remote request exceeds input budget');
  if (!Number.isInteger(request.timeout_ms) || request.timeout_ms < 1 || request.timeout_ms > 600000)
    throw new Error('Invalid remote deadline');
  if (signal?.aborted) throw new Error('Remote operation cancelled');
  const code = await readFile(new URL('./remote.py', import.meta.url), 'utf8');
  const keyFile = await open(target.identity_file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let privateKey;
  try {
    const info = await keyFile.stat();
    if (!info.isFile() || info.size > 65536 || info.uid !== process.getuid() || (info.mode & 0o077))
      throw new Error('Dedicated SSH identity must be a private, owned regular file (maximum 64 KiB)');
    const buffer = Buffer.alloc(65537);
    const { bytesRead } = await keyFile.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 65536) throw new Error('SSH identity exceeds size budget');
    privateKey = buffer.subarray(0, bytesRead);
  } finally { await keyFile.close(); }
  if (signal?.aborted) { privateKey.fill(0); throw new Error('Remote operation cancelled'); }
  return new Promise((resolve, reject) => {
    const ssh = new Client();
    const decoder = new StringDecoder('utf8');
    let channel, done = false, output = '', bytes = 0, stderrBytes = 0;
    const finish = (error, response) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      // EOF is the helper's cancellation signal; never wait for a remote acknowledgement.
      channel?.end();
      channel?.close();
      ssh.end();
      ssh.destroy();
      privateKey.fill(0);
      error ? reject(error) : resolve(response);
    };
    const cancel = () => finish(new Error('Remote operation cancelled; outcome may be uncertain, do not retry mutations automatically'));
    const timer = setTimeout(() => finish(new Error('Remote operation timed out; outcome may be uncertain')), request.timeout_ms);
    signal?.addEventListener('abort', cancel, { once: true });
    ssh.on('error', () => finish(new Error('SSH connection/authentication/host-pin failed')));
    ssh.on('close', () => { if (!done) finish(new Error('SSH disconnected before helper response')); });
    ssh.on('ready', () => {
      ssh.exec("python3 -c '" + code.replaceAll("'", "'\\''") + "'", (error, stream) => {
        if (error) return finish(new Error('SSH helper execution failed'));
        channel = stream;
        if (done) { stream.end(); stream.close(); return; }
        stream.on('error', () => finish(new Error('SSH helper channel failed')));
        stream.stderr.on('data', chunk => {
          stderrBytes += chunk.length;
          if (stderrBytes > MAX_OUTPUT) finish(new Error('SSH stderr exceeds output budget'));
        });
        stream.on('data', chunk => {
          bytes += chunk.length;
          if (bytes > MAX_WIRE) return finish(new Error('SSH response exceeds output budget'));
          output += decoder.write(chunk);
        });
        stream.on('close', () => {
          if (done) return;
          try {
            const response = JSON.parse(output + decoder.end());
            if (!response || typeof response.ok !== 'boolean') throw new Error();
            if (!response.ok) return finish(new Error('Remote helper rejected request: ' + String(response.error).slice(0, 1024)));
            if (typeof response.output !== 'string' || Buffer.byteLength(response.output) > MAX_OUTPUT || !Array.isArray(response.files)) throw new Error();
            finish(null, response);
          } catch { finish(new Error('Invalid or oversized remote helper response')); }
        });
        // Keep stdin open: EOF before completion means cancellation to remote.py.
        stream.write(payload);
      });
    });
    try {
      ssh.connect({ host: target.address, port: target.port, username: target.user,
        privateKey, hostHash: 'sha256', hostVerifier: hash => hash === target.host_key_sha256,
        authHandler: ['publickey'], tryKeyboard: false, readyTimeout: request.timeout_ms });
    } catch { finish(new Error('SSH setup failed')); }
  });
}
