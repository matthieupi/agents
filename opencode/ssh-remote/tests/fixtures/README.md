# Pinned OpenCode loader excerpts

The `loader-*-1.18.29.txt` files are verbatim excerpts from OpenCode v1.18.29,
commit `16747470f976aca3d362ad730bcd3fe82ecc2c9a`:

- `loader-functions` and `loader-catch`: `packages/opencode/src/plugin/index.ts`.
- `loader-detect`: `packages/opencode/src/plugin/shared.ts`.

`../pinned-loader.js` uses Node 22's built-in type erasure and the SDK's already
installed Effect dependency to run `applyPlugin` plus the actual catch-and-continue
loop. Only legacy default-function exports are exercised. It supplies record/error
utilities; it does not emulate package installation or the entire instance bootstrap.
`npm run test:loader` verifies the excerpts against the immutable public source.
`npm run test:engine` separately exercises the real CLI when an explicitly selected
`OPENCODE_TEST_BINARY` is available: startup-lockdown tests and a positive scripted
model/SSE read through the localhost SSH helper (`../native-engine.test.js`). The
positive test uses the real registry and SDK client, not the extracted loader adapter.
No engine dependencies are installed by those tests:
its isolated global config directory is read-only, causing pinned `core/src/npm.ts`
`Npm.install` to return at its writable-directory guard.

## Upstream license

MIT License

Copyright (c) 2025 opencode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
