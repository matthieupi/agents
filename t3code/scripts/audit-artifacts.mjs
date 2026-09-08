// Read-only online audit. No package extraction, installation or lifecycle hooks.
// Uses the verifier shipped with the locally installed npm; no npx/downloaded code.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const require = createRequire(import.meta.url);
const npmRoot = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
const { verify } = require(`${npmRoot}/npm/node_modules/sigstore`);
const get = async (url) => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  return response;
};
const lock = JSON.parse(fs.readFileSync(new URL('../runtime/package-lock.json', import.meta.url)));
const pkg = lock.packages['node_modules/t3'];
const metadataUrl = `https://registry.npmjs.org/t3/${pkg.version}`;
const metadata = await (await get(metadataUrl)).json();
if (metadata.dist.integrity !== pkg.integrity || metadata.dist.tarball !== pkg.resolved) throw new Error('Registry/lock mismatch');
const bytes = Buffer.from(await (await get(pkg.resolved)).arrayBuffer());
const sha512 = crypto.createHash('sha512').update(bytes).digest('hex');
if (`sha512-${Buffer.from(sha512, 'hex').toString('base64')}` !== pkg.integrity) throw new Error('Tarball SRI mismatch');
const keys = await (await get('https://registry.npmjs.org/-/npm/v1/keys')).json();
for (const signature of metadata.dist.signatures) {
  const key = keys.keys.find((key) => key.keyid === signature.keyid);
  if (!key || !crypto.verify('sha256', Buffer.from(`t3@${pkg.version}:${pkg.integrity}`),
    { key: Buffer.from(key.key, 'base64'), format: 'der', type: 'spki' }, Buffer.from(signature.sig, 'base64'))) {
    throw new Error('Registry signature verification failed');
  }
}
const url = metadata.dist.attestations.url;
const attestation = (await (await get(url)).json()).attestations.find((a) => a.predicateType === 'https://slsa.dev/provenance/v1');
await verify(attestation.bundle, undefined, {
  certificateIssuer: 'https://token.actions.githubusercontent.com',
  certificateIdentityURI: 'https://github.com/pingdotgg/t3code/.github/workflows/release.yml@refs/heads/main',
});
const statement = JSON.parse(Buffer.from(attestation.bundle.dsseEnvelope.payload, 'base64'));
if (!statement.subject.some((s) => s.name === `pkg:npm/t3@${pkg.version}` && s.digest.sha512 === sha512)) throw new Error('Provenance subject mismatch');
console.log(JSON.stringify({ metadataUrl, tarball: pkg.resolved, integrity: pkg.integrity,
  registrySignaturesVerified: metadata.dist.signatures.length, provenanceUrl: url,
  sigstoreVerified: true, statement }, null, 2));
