/** Public tool catalog; only deployed implementations are marked available. */
export type ToolCategory = 'Technical SEO' | 'Content' | 'Links';
export type CategoryFilter = ToolCategory | 'All';

export interface ToolPreview {
  readonly id: string;
  readonly slug: string;
  readonly name: string;
  readonly summary: string;
  readonly category: ToolCategory;
  readonly details: readonly string[];
  readonly status: 'planned' | 'available';
}

export const toolCategories: readonly ToolCategory[] = ['Technical SEO', 'Content', 'Links'];

export const plannedTools: readonly ToolPreview[] = [
  {
    id: 'robots',
    slug: 'robots-txt-validator',
    name: 'Robots.txt validator',
    summary: 'Review crawler instructions and common configuration issues.',
    category: 'Technical SEO',
    status: 'available',
    details: [
      'Review robots.txt syntax and group structure.',
      'Explain common directive conflicts and limitations.',
      'Display warnings without guessing search-engine behavior.',
    ],
  },
  {
    id: 'sitemap',
    slug: 'xml-sitemap-validator',
    name: 'XML sitemap validator',
    summary: 'Inspect sitemap XML, URL entries and common formatting issues.',
    category: 'Technical SEO',
    status: 'available',
    details: [
      'Validate XML structure and namespace usage.',
      'Identify malformed or unexpected URL entries.',
      'Explain issues and actionable corrections.',
    ],
  },
  {
    id: 'metadata',
    slug: 'meta-tag-checker',
    name: 'Meta tag checker',
    summary: 'Review page titles, descriptions and robots metadata.',
    category: 'Content',
    status: 'available',
    details: [
      'Extract metadata from a real page response.',
      'Highlight missing or conflicting elements.',
      'Provide page-level evidence for each finding.',
    ],
  },
  {
    id: 'redirects',
    slug: 'redirect-chain-checker',
    name: 'Redirect chain checker',
    summary: 'Trace redirect hops, loops and final destinations.',
    category: 'Technical SEO',
    status: 'available',
    details: [
      'List HTTP redirects in their original order.',
      'Identify loops and long chains.',
      'Show actual status codes and destinations.',
    ],
  },
  {
    id: 'canonical',
    slug: 'canonical-url-checker',
    name: 'Canonical URL checker',
    summary: 'Inspect canonical hints and conflicting declarations.',
    category: 'Technical SEO',
    status: 'available',
    details: [
      'Read canonical links from page HTML.',
      'Highlight ambiguous or conflicting hints.',
      'Explain common canonicalization mistakes.',
    ],
  },
  {
    id: 'schema',
    slug: 'structured-data-checker',
    name: 'Structured data checker',
    summary: 'Validate JSON-LD syntax and basic document structure.',
    category: 'Content',
    status: 'available',
    details: [
      'Extract JSON-LD blocks from HTML.',
      'Parse JSON safely and report syntax errors.',
      'Explain structural warnings without claiming rich-result eligibility.',
    ],
  },
  {
    id: 'headings',
    slug: 'heading-structure-analyzer',
    name: 'Heading structure analyzer',
    summary: 'Inspect the H1–H6 outline and page structure.',
    category: 'Content',
    status: 'available',
    details: [
      'Display headings in document order.',
      'Highlight missing or unclear structure.',
      'Provide relevant examples for improvements.',
    ],
  },
  {
    id: 'links',
    slug: 'internal-link-checker',
    name: 'Internal link checker',
    summary: 'Find important internal links and broken destinations.',
    category: 'Links',
    status: 'available',
    details: [
      'Classify links by destination.',
      'Check a bounded number of internal targets.',
      'Report verified errors without over-crawling.',
    ],
  },
  {
    id: 'social',
    slug: 'social-metadata-checker',
    name: 'Social metadata checker',
    summary: 'Inspect Open Graph and social preview fields.',
    category: 'Content',
    status: 'available',
    details: [
      'Extract social metadata from a page.',
      'Highlight missing common fields.',
      'Show clearly labeled approximate previews.',
    ],
  },
  {
    id: 'ai-meta',
    slug: 'ai-meta-suggestions',
    name: 'AI meta suggestions',
    summary: 'Generate page-relevant title and description alternatives.',
    category: 'Content',
    status: 'planned',
    details: [
      'Use supplied page content as source material.',
      'Generate multiple editable suggestions.',
      'Flag unsupported or overly long suggestions.',
    ],
  },
];

export function filterTools(
  query: string,
  tools: readonly ToolPreview[] = plannedTools,
  category: CategoryFilter = 'All',
): ToolPreview[] {
  const search = query.trim().toLocaleLowerCase();
  return tools.filter((tool) => {
    const matchesCategory = category === 'All' || tool.category === category;
    const matchesSearch =
      !search ||
      (tool.name + ' ' + tool.summary + ' ' + tool.category).toLocaleLowerCase().includes(search);
    return matchesCategory && matchesSearch;
  });
}

export function toolBySlug(slug: string): ToolPreview | undefined {
  return plannedTools.find((tool) => tool.slug === slug);
}

export function toolPath(tool: ToolPreview): string {
  return '/tools/' + tool.slug + '/';
}
