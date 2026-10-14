# Web

Astro + React + Tailwind frontend. The initial page shows the project and a searchable directory of **planned** tools. It does not submit an audit or claim tools are available yet.

From the repository root (Node 22.12+ and pnpm 10 required):

```bash
corepack enable
pnpm install
pnpm dev:web
```

Open http://127.0.0.1:4321. Run `pnpm test:web`, `pnpm check:web`, and `pnpm build:web` to validate the web workspace.

Tailwind 4 uses the `@tailwindcss/vite` plugin. React is hydrated only in the interactive tool directory.
