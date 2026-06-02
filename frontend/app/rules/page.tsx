import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { RulesContent } from '@/components/rules/RulesContent';

interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

/**
 * Merges standalone number headings (e.g. "# 100.") with the immediately
 * following heading of the same level (e.g. "# Game Concepts") into one
 * combined heading ("# 100. Game Concepts"). Handles blank lines between them.
 */
function mergeNumberHeadings(md: string): string {
  const lines = md.split('\n');
  const result: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const numMatch = line.match(/^(#{1,3}) (\d+\.)$/);

    if (numMatch) {
      const hashes = numMatch[1];
      const num = numMatch[2];
      // Skip blank lines to find the next non-empty line
      let j = i + 1;
      while (j < lines.length && lines[j].trim() === '') j++;

      if (j < lines.length) {
        const nextMatch = lines[j].match(new RegExp(`^${hashes} (.+)$`));
        if (nextMatch && !/^\d+\.$/.test(nextMatch[1].trim())) {
          // Push merged heading, skip the blank lines + consumed heading
          result.push(`${hashes} ${num} ${nextMatch[1]}`);
          i = j + 1;
          continue;
        }
      }
    }

    result.push(line);
    i++;
  }

  return result.join('\n');
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
  const raw = await readFile(join(process.cwd(), 'content', 'rulebook.md'), 'utf8');
  const normalized = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const markdown = mergeNumberHeadings(normalized);
  const toc = buildToc(markdown);
  return <RulesContent markdown={markdown} toc={toc} />;
}
