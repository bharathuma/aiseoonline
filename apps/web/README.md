# Web

Astro + React + Tailwind frontend. The site includes a responsive homepage, tool directory, planned-tool detail pages, audit overview, guides, project documentation and a small component reference. It does not submit an audit or claim tools are available yet.

From the repository root (Node 22.12+ and pnpm 10 required):

```bash
corepack enable
pnpm install
pnpm dev:web
```

Open http://127.0.0.1:4321. Run `pnpm test:web`, `pnpm check:web`, and `pnpm build:web` to validate the web workspace.

Run `pnpm e2e:web` from the repository root for Playwright browser checks; install Chromium first with `pnpm --filter @aiseoonline/web exec playwright install chromium`. Browser tests build and preview the static site and cover navigation, interactive discovery, dialogs and common screen widths.

Tailwind 4 uses the `@tailwindcss/vite` plugin. React is hydrated only in the interactive tool directory. Public page content and planned tool descriptions are server-rendered; the native mobile navigation works without JavaScript.
