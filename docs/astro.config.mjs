import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mdx from '@astrojs/mdx';

// Site URL — override via `SITE_URL` env var at build time (used in CI).
// Default to a placeholder that's obviously not a real URL so anyone
// previewing locally sees the issue if they read the meta tags.
const SITE = process.env.SITE_URL ?? 'https://strata.dev';

// `base` only set if explicitly building for a sub-path (e.g.
// gideondk.github.io/strata). GitHub Pages with the default
// `<org>.github.io/<repo>` URL needs base = "/<repo>/"; a custom
// domain or root pages site uses base = "/".
const BASE = process.env.SITE_BASE ?? undefined;

export default defineConfig({
  site: SITE,
  base: BASE,
  integrations: [
    starlight({
      title: 'Strata',
      description:
        'Typed, local-first memory for Claude Code: decisions, domain ' +
        'rules, and runbooks, kept as plain markdown Claude reads on its own.',
      // Default first-time visitors to dark — basalt + amber is the
      // canonical Strata look. Toggle still works; user choice is sticky.
      head: [
        {
          tag: 'script',
          content: `
            (function () {
              try {
                if (!localStorage.getItem('starlight-theme')) {
                  localStorage.setItem('starlight-theme', 'dark');
                  document.documentElement.dataset.theme = 'dark';
                }
              } catch (_) {}
            })();
          `,
        },
      ],
      logo: {
        src: './src/assets/strata-glyph.svg',
        replacesTitle: false,
      },
      customCss: [
        '@fontsource-variable/fraunces/index.css',
        '@fontsource-variable/inter/index.css',
        '@fontsource-variable/jetbrains-mono/index.css',
        '@fontsource-variable/bricolage-grotesque/index.css',
        './src/styles/strata.css',
      ],
      expressiveCode: {
        themes: ['github-dark-default', 'github-light'],
        styleOverrides: {
          borderRadius: '6px',
          borderColor: 'var(--sl-color-bg-nav)',
          codeFontFamily: 'JetBrains Mono Variable, ui-monospace, monospace',
        },
      },
      pagefind: true,
      lastUpdated: true,
      editLink: {
        baseUrl: 'https://github.com/gideondk/strata/edit/main/docs/',
      },
      pagination: true,
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/gideondk/strata',
        },
      ],
      components: {
        // Add a thin amber scroll-progress bar above the header.
        Header: './src/overrides/Header.astro',
      },
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'What is Strata', link: '/guide/what-is-strata/' },
            { label: 'Getting started', link: '/guide/getting-started/' },
            { label: 'FAQ', link: '/guide/faq/' },
            { label: 'Memory architecture', link: '/guide/memory-architecture/' },
            { label: 'Concepts', link: '/guide/concepts/' },
          ],
        },
        {
          label: 'Capabilities',
          items: [
            { label: 'Skills', link: '/guide/skills/' },
            { label: 'MCP tools', link: '/guide/mcp-tools/' },
            { label: 'Code graph', link: '/guide/code-graph/' },
            { label: 'Strata for teams', link: '/guide/teams/' },
          ],
        },
        {
          label: 'Workflows',
          items: [
            { label: 'Bootstrap', link: '/guide/bootstrap/' },
            { label: 'Correcting the vault', link: '/guide/correcting/' },
          ],
        },
        {
          label: 'Under the hood',
          items: [
            { label: 'Architecture', link: '/guide/architecture/' },
          ],
        },
      ],
    }),
    mdx(),
  ],
});
