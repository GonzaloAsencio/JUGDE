export interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

export interface TocSection {
  header: TocEntry;
  children: TocEntry[];
}

/** Groups a flat TOC into depth-1 sections, each owning its deeper children. */
export function groupToc(toc: TocEntry[]): TocSection[] {
  const sections: TocSection[] = [];
  let current: TocSection | null = null;
  for (const entry of toc) {
    if (entry.depth === 1) {
      current = { header: entry, children: [] };
      sections.push(current);
    } else if (current) {
      current.children.push(entry);
    }
  }
  return sections;
}
