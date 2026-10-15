/** Original editorial guidance for the ten implemented public tools. No generated results. */
export interface ToolEditorial {
  title: string;
  description: string;
  intro: string;
  steps: readonly string[];
  example: { title: string; input: string; finding: string; action: string };
  troubleshooting: readonly { title: string; body: string }[];
  faqs: readonly { question: string; answer: string }[];
  limitations: string;
  related: readonly string[];
}
export const toolGuides: Readonly<Record<string, ToolEditorial>> = {
  robots: {
    title: 'Robots.txt validator: check crawler directives',
    description:
      'Check robots.txt groups, directives and warnings for one public site. Understand what crawler restrictions do—and what they cannot protect.',
    intro:
      'Robots.txt is a crawler instruction file, not a security boundary. This check helps spot malformed directives and confusing groups before crawlers encounter them.',
    steps: [
      "Enter a site's public homepage URL so the checker can locate its robots.txt file.",
      'Read the parsed user-agent groups and directives; note any syntax warnings alongside the actual text.',
      "Test important paths separately in the search engine's own tools before changing production crawl rules.",
    ],
    example: {
      title: 'Example: an overbroad disallow',
      input: 'User-agent: *\\nDisallow: /',
      finding:
        'A site-wide disallow may prevent cooperating crawlers from exploring otherwise public pages.',
      action:
        'Review whether blocking every path is intentional. Remove or narrow the rule only if those URLs should be crawled.',
    },
    troubleshooting: [
      {
        title: 'The robots file cannot be fetched',
        body: "Confirm that /robots.txt is publicly reachable from the site's host and is not blocked by a firewall or login. A timeout is not evidence that robots rules are valid.",
      },
      {
        title: 'A disallowed URL still appears in search',
        body: 'A crawl disallow does not reliably remove known URLs from search results. Use access controls for sensitive content and search-engine guidance for removals.',
      },
    ],
    faqs: [
      {
        question: 'Does robots.txt prevent indexing?',
        answer:
          'Not necessarily. It primarily tells cooperating crawlers which paths not to fetch; a URL can still be discovered elsewhere.',
      },
      {
        question: 'Can I hide passwords with Disallow?',
        answer:
          'No. Robots.txt is public and not a substitute for authentication or server access controls.',
      },
    ],
    limitations:
      'The checker reads the currently available robots file and cannot predict how every crawler will handle special extensions or past cached rules.',
    related: ['xml-sitemap-validator', 'meta-tag-checker'],
  },
  sitemap: {
    title: 'XML sitemap validator: review sitemap structure',
    description:
      "Validate a public XML sitemap's structure, declared URLs and formatting warnings without assuming listed URLs will be indexed.",
    intro:
      'A sitemap supplies discovery hints. Valid XML is useful, but inclusion in a sitemap does not require a search engine to crawl or index any URL.',
    steps: [
      'Paste the full public URL of an XML sitemap, usually ending in /sitemap.xml.',
      'Review XML parsing errors and the URLs actually declared in the response.',
      'Correct malformed elements and recheck; verify indexing independently in search engine webmaster tools.',
    ],
    example: {
      title: 'Example: a URL outside its intended host',
      input: '<loc>https://other.example/page</loc>',
      finding:
        "A loc entry pointing somewhere unexpected deserves review of the sitemap's host and scope.",
      action:
        'Confirm intended ownership and sitemap scope; correct the URL rather than assuming its presence means it will be indexed.',
    },
    troubleshooting: [
      {
        title: 'The page returns HTML instead of XML',
        body: 'Check for login redirects, proxy errors or an incorrect sitemap path. The checker cannot validate an HTML error page as a sitemap.',
      },
      {
        title: 'Valid sitemap, but pages are not indexed',
        body: 'Inspect URL accessibility, canonical signals, content quality and search engine coverage separately. Sitemap validity is not an indexing guarantee.',
      },
    ],
    faqs: [
      {
        question: 'Does a valid sitemap guarantee indexing?',
        answer:
          'No. Search engines decide what to crawl and index, regardless of sitemap inclusion.',
      },
      {
        question: 'Should I include canonical URLs?',
        answer:
          'Generally, list the URLs you intend search engines to consider canonical, and keep site signals consistent.',
      },
    ],
    limitations:
      'The tool performs a bounded XML inspection; it is not a full crawl or a live search-console coverage report.',
    related: ['robots-txt-validator', 'canonical-url-checker'],
  },
  metadata: {
    title: 'Meta tag checker: inspect titles and descriptions',
    description:
      "Inspect one page's HTML title, meta description and robots directives. Get source-backed warnings and practical edits.",
    intro:
      'A descriptive title and useful snippet text help people understand a result. Search engines may rewrite displayed titles and snippets, so this tool reports what the fetched HTML declares.',
    steps: [
      'Enter a publicly accessible page URL and run the check.',
      'Inspect the extracted title, description, robots metadata and any conflicts.',
      'Revise missing or misleading tags in your CMS, publish changes and check the page again.',
    ],
    example: {
      title: 'Example: missing page description',
      input: '<title>Shipping information</title> (no meta description)',
      finding: 'The page declares a title but has no meta description.',
      action:
        'Write a helpful description that summarizes the page rather than stuffing repeated keywords.',
    },
    troubleshooting: [
      {
        title: 'Your CMS editor shows a tag the checker missed',
        body: 'Confirm the tag exists in the raw HTTP HTML, not only after client-side JavaScript runs. The tool does not render a browser page.',
      },
      {
        title: 'Search results show a different snippet',
        body: 'Search engines can choose query-specific snippets even when the declared description is accurate.',
      },
    ],
    faqs: [
      {
        question: 'Is there one perfect title length?',
        answer:
          'No. Width and query context affect how titles display. Prefer unique, readable wording over a rigid character count.',
      },
      {
        question: 'Will editing my description improve rankings?',
        answer:
          "No ranking improvement is guaranteed. Descriptions primarily help communicate a page's relevance to people.",
      },
    ],
    limitations:
      'A single-response HTML inspection cannot assess search engine rendering, personalization or sitewide duplicate tags.',
    related: ['heading-structure-analyzer', 'social-metadata-checker', 'ai-meta-suggestions'],
  },
  redirects: {
    title: 'Redirect chain checker: trace URL hops',
    description:
      'Inspect HTTP redirects from a public URL, including status codes and destinations. Identify unexpected or overly long chains.',
    intro:
      'Redirects connect old addresses with new ones. Extra hops can add network work and make it harder to understand the final destination.',
    steps: [
      'Paste the starting URL, including its original protocol and path.',
      'Inspect each observed status code, Location header and final URL.',
      'Update internal links to the correct destination and remove unnecessary intermediate hops where practical.',
    ],
    example: {
      title: 'Example: two hops before the final page',
      input: '/old → 301 /middle → 302 /new → 200',
      finding: 'Visitors and crawlers follow multiple responses before reaching the content.',
      action:
        'If appropriate, point /old directly at /new and change your own internal links to the final URL.',
    },
    troubleshooting: [
      {
        title: 'A redirect destination is refused',
        body: 'The crawler will not follow destinations that violate the public-network safety policy. That is a protective limit, not proof of a broken public site.',
      },
      {
        title: 'Browser works but the checker times out',
        body: 'A page may require cookies, JavaScript or longer network timeouts. Recheck the public server response separately.',
      },
    ],
    faqs: [
      {
        question: 'Is 301 always better than 302?',
        answer:
          'Use permanent redirects for lasting moves and temporary redirects for genuinely temporary changes. Choose based on intent.',
      },
      {
        question: 'Does every redirect cause a ranking loss?',
        answer:
          'No fixed ranking-loss percentage can be inferred from redirect counts. Reduce avoidable hops for clarity and efficiency.',
      },
    ],
    limitations:
      'The checker traces a bounded HTTP chain; it does not run browser JavaScript or guarantee how a search engine processes every move.',
    related: ['canonical-url-checker', 'internal-link-checker'],
  },
  canonical: {
    title: 'Canonical URL checker: inspect preferred URL hints',
    description:
      "Read a page's declared canonical links and identify conflicting or ambiguous hints, with evidence from its HTML.",
    intro:
      'Canonical links communicate the preferred address among substantially similar pages. They are hints, not commands that force search engines to choose a particular URL.',
    steps: [
      'Run the check on a page with a public canonical address.',
      'Compare the declared canonical URL with the final response URL and other versions of the page.',
      'Resolve contradictory canonical tags and align internal links and sitemaps with the preferred page.',
    ],
    example: {
      title: 'Example: two competing canonicals',
      input: '<link rel="canonical" href="/a"> and <link rel="canonical" href="/b">',
      finding: "Two distinct preferred destinations make the page's intent ambiguous.",
      action:
        'Select one appropriate canonical, remove the duplicate and verify the rendered server HTML.',
    },
    troubleshooting: [
      {
        title: 'Your canonical is relative',
        body: 'The tool resolves URLs against the page URL for inspection. An absolute canonical is often clearer when templates are reused.',
      },
      {
        title: 'Search engines select another URL',
        body: 'Canonicalization also depends on redirects, internal links, content similarity and other signals beyond a single tag.',
      },
    ],
    faqs: [
      {
        question: 'Does rel=canonical guarantee my selected URL?',
        answer:
          'No. A search engine can select a different canonical based on its overall assessment.',
      },
      {
        question: 'Is a self-referencing canonical required?',
        answer:
          "Not universally. It can make your preferred address explicit, but implementation should fit the site's URL strategy.",
      },
    ],
    limitations:
      "This is a one-page HTML inspection, not a search engine's reported canonical or a duplicate-content comparison.",
    related: ['redirect-chain-checker', 'xml-sitemap-validator'],
  },
  schema: {
    title: 'Structured data checker: parse page JSON-LD',
    description:
      "Check a page's JSON-LD blocks for syntax and basic structure, without promising eligibility for rich results.",
    intro:
      'Structured data is machine-readable context embedded in HTML. A valid JSON-LD block is only the beginning; search engines apply their own vocabulary and feature requirements.',
    steps: [
      'Enter the URL of a page that includes JSON-LD markup.',
      'Review extracted blocks, parsed types and any JSON syntax errors.',
      "Correct errors in the page's source and verify feature-specific requirements in the appropriate search engine tools.",
    ],
    example: {
      title: 'Example: trailing comma breaks JSON',
      input: '{"@context":"https://schema.org","@type":"Article",}',
      finding:
        'The trailing comma makes this string invalid JSON, so it cannot be parsed as JSON-LD.',
      action: 'Remove the trailing comma, publish valid JSON and rerun the check.',
    },
    troubleshooting: [
      {
        title: 'JSON-LD is injected after page load',
        body: 'The checker reads the HTTP HTML and may not find scripts added only by client-side JavaScript.',
      },
      {
        title: 'Valid JSON-LD produces no rich result',
        body: 'Syntax correctness does not mean a page meets a specific rich-result policy or content requirement.',
      },
    ],
    faqs: [
      {
        question: 'Does valid JSON-LD guarantee a rich result?',
        answer:
          'No. Search engines determine eligibility and presentation separately from basic JSON syntax.',
      },
      {
        question: 'Does the checker validate every Schema.org type?',
        answer:
          'No. It checks syntax and selected structural issues, not exhaustive semantic type validation.',
      },
    ],
    limitations:
      'No search-engine certification or live rich-result preview is performed by this utility.',
    related: ['meta-tag-checker', 'heading-structure-analyzer'],
  },
  headings: {
    title: 'Heading structure analyzer: review H1–H6',
    description:
      'Inspect heading order and page outlines from public HTML. Find missing or skipped levels and improve readability.',
    intro:
      'Headings introduce sections and make a document easier to scan. A useful outline helps readers and assistive technology, without enforcing a mythical ranking formula.',
    steps: [
      'Run a single-page heading scan against the public URL.',
      'Read H1 through H6 in source order, checking whether labels match the content underneath.',
      'Fix confusing or missing section headings and check the rendered page with keyboard and screen-reader tools.',
    ],
    example: {
      title: 'Example: a level jump',
      input: '<h1>Support</h1><h4>Returns</h4>',
      finding: 'The page jumps from H1 to H4 without intermediate section structure.',
      action:
        'Use a heading level that reflects the intended section hierarchy, without styling headings solely by their number.',
    },
    troubleshooting: [
      {
        title: 'Visible headings do not appear in results',
        body: 'Text added after page load may be absent from the server HTML. Review whether the page uses client-side rendering.',
      },
      {
        title: 'The report mentions multiple H1 headings',
        body: 'Multiple H1 elements can be valid HTML. Focus on a coherent outline rather than an arbitrary count.',
      },
    ],
    faqs: [
      {
        question: 'Does every page need exactly one H1?',
        answer:
          'No. HTML permits multiple H1 elements; a clear content structure matters more than a strict count.',
      },
      {
        question: 'Are skipped levels a ranking penalty?',
        answer:
          'Not a fixed penalty. The check highlights an outline or accessibility concern worth reviewing.',
      },
    ],
    limitations:
      'The analyzer inspects source heading tags, not visual styling or the full accessibility tree after scripts run.',
    related: ['meta-tag-checker', 'structured-data-checker'],
  },
  links: {
    title: 'Internal link checker: inspect page navigation',
    description:
      "Review one page's internal and external anchor links, with bounded checks of selected same-origin targets.",
    intro:
      'Internal links help people and crawlers discover useful content. This check distinguishes links actually inspected from destinations that were not tested.',
    steps: [
      'Enter a public page URL that contains ordinary HTML anchor links.',
      'Review the extracted link destinations and whether each is internal or external.',
      'Inspect the limited target checks and repair known errors, prioritizing important navigation paths.',
    ],
    example: {
      title: 'Example: outdated internal link',
      input: '<a href="/old-contact">Contact us</a>',
      finding:
        'An important navigation link may point to a removed destination or an avoidable redirect.',
      action: 'Update the link to the current destination after verifying it exists.',
    },
    troubleshooting: [
      {
        title: 'Most links show not checked',
        body: 'The tool probes only a small bounded number of same-origin destinations—currently three. Untested does not mean healthy or broken.',
      },
      {
        title: 'A menu link is not found',
        body: 'JavaScript-generated links can be absent from the raw HTML. Check the actual response as well as the rendered browser UI.',
      },
    ],
    faqs: [
      {
        question: 'Does this scan the whole website?',
        answer:
          'No. It inspects one page and probes up to three same-origin destinations within resource limits.',
      },
      {
        question: 'Will it open external links?',
        answer:
          'No. External destinations may be classified, but this checker does not fetch them.',
      },
    ],
    limitations:
      'This is not a sitewide broken-link audit. Neither external links nor every internal destination are tested.',
    related: ['redirect-chain-checker', 'canonical-url-checker'],
  },
  social: {
    title: 'Social metadata checker: inspect sharing tags',
    description:
      "Inspect Open Graph and other social metadata and see an approximate preview based on the fetched page's HTML.",
    intro:
      'Social networks may build link cards from Open Graph and other metadata. A page can declare useful fields, but each platform may crop, cache or replace them.',
    steps: [
      'Enter a public page URL with its social metadata in HTML.',
      'Review the extracted title, description, image URL and any missing common fields.',
      'Update template tags and use a platform-specific sharing debugger to confirm the real card.',
    ],
    example: {
      title: 'Example: missing Open Graph description',
      input: '<meta property="og:title" content="New collection">',
      finding: 'A social title is supplied but the matching Open Graph description may be missing.',
      action:
        'Write a plain-language preview description and ensure social image URLs lead to public assets.',
    },
    troubleshooting: [
      {
        title: 'The preview image looks different on a platform',
        body: "The built-in preview is only approximate. This checker does not download social images or reproduce each network's crop and cache.",
      },
      {
        title: 'A corrected preview does not appear immediately',
        body: 'Social platforms may retain cached link-card data until refreshed in their own tools.',
      },
    ],
    faqs: [
      {
        question: 'Is the preview identical to Facebook or other platforms?',
        answer:
          "No. Actual cards depend on each platform's parsing, cached metadata and image handling.",
      },
      {
        question: 'Does this tool download social images?',
        answer: 'No. Image addresses are inspected as text; remote images are not fetched.',
      },
    ],
    limitations:
      'A generated preview cannot reproduce platform-specific crawlers or prove that the linked image is reachable.',
    related: ['meta-tag-checker', 'structured-data-checker'],
  },
  'ai-meta': {
    title: 'AI title and meta description suggestions',
    description:
      'Generate editable AI title and meta description drafts from supplied page text or a public URL. Review evidence and usage limits.',
    intro:
      'AI drafts can help brainstorm concise on-page text, but they can also be inaccurate. This generator checks source evidence and budget limits; it does not promise traffic or rankings.',
    steps: [
      'Provide your own representative page text or a reachable public URL.',
      'Request drafts and inspect the associated source evidence and warnings.',
      'Edit every suggestion for factual accuracy, natural tone, uniqueness and editorial fit before publishing.',
    ],
    example: {
      title: 'Example: a descriptive product title',
      input: 'A page explains how to repair a loose bicycle chain.',
      finding:
        "A useful title should describe the page's actual repair guidance, not invent a guarantee.",
      action:
        'A human-reviewed draft could be "How to Fix a Loose Bicycle Chain | Repair Guide" if it accurately matches the page.',
    },
    troubleshooting: [
      {
        title: 'The provider is unavailable',
        body: 'AI output requires configured provider credentials, budgets and service capacity. The interface should show an explicit error rather than fabricate text.',
      },
      {
        title: 'A suggested claim is not in your source',
        body: 'Discard or rewrite unsupported claims. Source checks cannot guarantee semantic truth for every generated statement.',
      },
    ],
    faqs: [
      {
        question: 'Are AI-generated titles guaranteed to improve SEO?',
        answer: 'No. These are editable writing suggestions, not a search ranking prediction.',
      },
      {
        question: 'What does it read from a public URL?',
        answer:
          'A bounded fetch uses extracted page title, descriptions and headings, not a full browser rendering or deep site crawl.',
      },
    ],
    limitations:
      'Paid API credentials and rate budgets may be required. Outputs are nondeterministic and always need human review.',
    related: ['meta-tag-checker', 'heading-structure-analyzer'],
  },
};
