import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { RulesContent } from '@/components/RulesContent';

interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

function buildToc(markdown: string): TocEntry[] {
  const lines = markdown.split('\n');
  const toc: TocEntry[] = [];
  const seen: Record<string, number> = {};

  for (const line of lines) {
    const m = line.match(/^(#{1,3})\s+(.+)/);
    if (!m) continue;
    const depth = m[1].length;
    const text = m[2].trim();
    // generate slug matching rehype-slug (lowercase, replace non-alphanumeric with -)
    let id = text
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    if (seen[id] !== undefined) {
      seen[id]++;
      id = `${id}-${seen[id]}`;
    } else {
      seen[id] = 0;
    }
    toc.push({ id, text, depth });
  }
  return toc;
}

export default async function RulesPage() {
  const markdown = await readFile(join(process.cwd(), 'content', 'rulebook.md'), 'utf8');
  const toc = buildToc(markdown);
  return (
    <div className="py-4">
      <RulesContent markdown={markdown} toc={toc} />
    </div>
  );
}
