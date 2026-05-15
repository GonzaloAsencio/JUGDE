import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import GithubSlugger from 'github-slugger';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');

const md = readFileSync(join(root, 'content', 'rulebook.md'), 'utf8');
const slugger = new GithubSlugger();
const map = {};

for (const line of md.split('\n')) {
  const m = line.match(/^#{1,6}\s+(.+)/);
  if (!m) continue;
  const text = m[1].replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').trim();
  const slug = slugger.slug(text);
  // use first word/number token before a space as the key if it looks like a section number
  const keyMatch = text.match(/^([\d.]+)\s/);
  const key = keyMatch ? keyMatch[1] : text;
  map[key] = slug;
}

writeFileSync(join(root, 'content', 'sections.json'), JSON.stringify(map, null, 2));
console.log(`section map: ${Object.keys(map).length} entries written to content/sections.json`);
