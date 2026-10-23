---
name: web-artifacts-builder
description: Suite of tools for creating elaborate, multi-component portable browser HTML applications using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for complex applications requiring state management, routing, or shadcn/ui components - not for simple single-file HTML/JSX pages.
license: Complete terms in LICENSE.txt
---

# Web Artifacts Builder

> Local adaptation (2026-10-23): use OpenCode V2 file tools and `shell`; deliver browser HTML on disk rather than a hosted conversation artifact. Resolve scripts relative to this skill's directory. Check local Node/pnpm availability and get appropriate permission before dependency installs; OpenCode does not provide a preinstalled frontend sandbox. For organization branding consult local `brand-guidelines`.

To build portable frontend HTML applications, follow these steps:
1. Initialize the frontend repo using `scripts/init-artifact.sh`
2. Develop your artifact by editing the generated code
3. Bundle all code into a single HTML file using `scripts/bundle-artifact.sh`
4. Test the generated HTML when browser tooling is available
5. Share the saved file path with the user

**Stack**: React 18 + TypeScript + Vite + Parcel (bundling) + Tailwind CSS + shadcn/ui

## Design & Style Guidelines

VERY IMPORTANT: To avoid what is often referred to as "AI slop", avoid using excessive centered layouts, purple gradients, uniform rounded corners, and Inter font.

## Quick Start

### Step 1: Initialize Project

Resolve this skill's absolute directory as `SKILL_DIR`, then use `shell` with the user's project root as `workdir`. Create a dedicated output workspace before initialization:
```bash
mkdir -p .project/web-artifacts
# Set SKILL_DIR to the actual loaded skill directory, not a guessed install path.
bash "$SKILL_DIR/scripts/init-artifact.sh" .project/web-artifacts/my-app
```

Use `.project/web-artifacts/my-app` as `workdir` for subsequent build commands. Choose a fresh name rather than overwriting an existing project.

This creates a fully configured project with:
- ✅ React + TypeScript (via Vite)
- ✅ Tailwind CSS 3.4.1 with shadcn/ui theming system
- ✅ Path aliases (`@/`) configured
- ✅ 40+ shadcn/ui components pre-installed
- ✅ All Radix UI dependencies included
- ✅ Parcel configured for bundling (via .parcelrc)
- ✅ Node 18+ compatibility (auto-detects and pins Vite version)

### Step 2: Develop Your Artifact

To build the application, edit the generated files with the available editing tools.

### Step 3: Bundle to Single HTML File

To bundle the React app into a single HTML artifact:
```bash
bash "$SKILL_DIR/scripts/bundle-artifact.sh"
```

This creates `bundle.html` in the generated project. The bundler inlines local assets; remote URLs, API calls, and externally hosted fonts may still need network access. Inspect the result before claiming offline support. Share the resolved `.project/web-artifacts/my-app/bundle.html` path for opening in a browser.

**Requirements**: Your project must have an `index.html` in the root directory.

**What the script does**:
- Installs bundling dependencies (parcel, @parcel/config-default, parcel-resolver-tspaths, html-inline)
- Creates `.parcelrc` config with path alias support
- Builds with Parcel (no source maps)
- Inlines all assets into single HTML using html-inline

### Step 4: Share Artifact with User

Finally, share the bundled HTML file's path so the user can open it in a browser. Do not assume the OpenCode client has an embedded artifact viewer.

### Testing/Visualizing Before Delivery

Use installed Playwright/Puppeteer through `shell`, the `webapp-testing` skill, or an exposed OpenCode browser integration. These are capabilities to check, not guaranteed built-in tools. Verify loading, key interactions, and console errors before delivery when possible. Otherwise state that browser behavior was not tested and provide manual opening instructions. Use hash routing or verify a local server path if client-side routing requires one.

## Reference

- **shadcn/ui components**: https://ui.shadcn.com/docs/components
