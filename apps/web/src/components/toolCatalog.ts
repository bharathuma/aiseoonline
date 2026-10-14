/** Upcoming public tools. Do not show these as launched products. */
export interface ToolPreview {
  readonly id: string;
  readonly name: string;
  readonly summary: string;
  readonly category: 'Technical SEO' | 'Content' | 'Links';
}

export const plannedTools: readonly ToolPreview[] = [
  { id: 'robots', name: 'Robots.txt validator', summary: 'Inspect crawler directives and common mistakes.', category: 'Technical SEO' },
  { id: 'sitemap', name: 'Sitemap validator', summary: 'Check XML sitemap structure and URLs.', category: 'Technical SEO' },
  { id: 'metadata', name: 'Meta tag checker', summary: 'Review page titles, descriptions, and robots meta tags.', category: 'Content' },
  { id: 'redirects', name: 'Redirect checker', summary: 'Follow redirect chains and identify loops.', category: 'Technical SEO' },
  { id: 'canonical', name: 'Canonical URL checker', summary: 'Inspect canonical references and conflicts.', category: 'Technical SEO' },
  { id: 'schema', name: 'Structured data checker', summary: 'Inspect JSON-LD syntax and supported structures.', category: 'Content' },
  { id: 'headings', name: 'Heading analyzer', summary: 'Review page heading hierarchy.', category: 'Content' },
  { id: 'links', name: 'Internal link checker', summary: 'Inspect on-site links and broken destinations.', category: 'Links' },
  { id: 'social', name: 'Social metadata checker', summary: 'Review Open Graph and social card metadata.', category: 'Content' },
  { id: 'ai-meta', name: 'AI meta suggestions', summary: 'Draft title and description alternatives.', category: 'Content' },
];

export function filterTools(query: string, tools: readonly ToolPreview[] = plannedTools): ToolPreview[] {
  const search = query.trim().toLocaleLowerCase();
  if (!search) return [...tools];
  return tools.filter((tool) => `${tool.name} ${tool.summary} ${tool.category}`.toLocaleLowerCase().includes(search));
}
