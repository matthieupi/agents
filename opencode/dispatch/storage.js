import { open, rename, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

export const INBOX_LIMIT = 16 * 1024 * 1024;
export const RESULT_RESERVE = 128 * 1024; // Includes worst-case JSON escaping of 16000 text characters.
export const capacityError = () => Object.assign(new Error('Dispatch result storage capacity exhausted.'), { code: 'DISPATCH_CAPACITY' });
// Only operational storage errors degrade optional caching/exposure. Never permission,
// unsafe ownership/mode, corrupt JSON, invalid approval epochs or arbitrary exceptions.
export const isStorageFailure = error => ['DISPATCH_CAPACITY', 'DISPATCH_BUSY', 'ENOSPC', 'EDQUOT', 'EFBIG', 'EIO', 'EROFS', 'EMFILE', 'ENFILE'].includes(error?.code);

export async function atomicWrite(directory, name, value, filesystem = { open }) {
  const contents = JSON.stringify(value);
  if (Buffer.byteLength(contents) > INBOX_LIMIT) throw capacityError();
  const temp = path.join(directory, '.' + randomUUID());
  let fd, owned = false;
  try {
    fd = await filesystem.open(temp, 'wx', 0o600);
    owned = true;
    await fd.writeFile(contents);
    await fd.sync();
    await fd.close();
    fd = undefined;
    await rename(temp, path.join(directory, name + '.json'));
    const dir = await open(directory, 'r');
    try { await dir.sync(); } finally { await dir.close(); }
  } finally {
    // A failed close still reaches unlink. Never rename after a failed temp close.
    try { await fd?.close(); }
    finally {
      if (owned) await unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw error; });
    }
  }
}
