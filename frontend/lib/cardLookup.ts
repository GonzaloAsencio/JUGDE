import { CARD_INDEX, type CardIndexEntry } from '@/lib/cardIndex';

/** clean_name -> hyphenated slug (e.g. "Jhin Virtuoso" -> "jhin-virtuoso"). */
export function toSlug(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, '-');
}

const BY_NAME: Map<string, CardIndexEntry> = new Map(
  CARD_INDEX.map(entry => [entry.clean_name.toLowerCase(), entry]),
);

const BY_SLUG: Map<string, CardIndexEntry> = new Map(
  CARD_INDEX.map(entry => [toSlug(entry.clean_name), entry]),
);

/**
 * Resolve a tag token to a card. Cascade: exact name -> slug -> prefix (first-wins).
 * Prefix matching lets a bare `@jhin` resolve to "jhin virtuoso".
 */
export function lookupCard(name: string): CardIndexEntry | undefined {
  const key = name.trim().toLowerCase();
  if (!key) return undefined;

  const exact = BY_NAME.get(key);
  if (exact) return exact;

  const bySlug = BY_SLUG.get(key);
  if (bySlug) return bySlug;

  return CARD_INDEX.find(
    entry =>
      entry.clean_name.toLowerCase().startsWith(key) ||
      toSlug(entry.clean_name).startsWith(key),
  );
}

const byCleanName = (a: CardIndexEntry, b: CardIndexEntry) =>
  a.clean_name.localeCompare(b.clean_name);

/**
 * Cards whose name (or slug) starts with the query, for the @-mention picker.
 * Results are sorted alphabetically, then capped at `limit`. Empty query
 * returns the first `limit` cards so a bare `@` shows suggestions.
 */
export function searchCards(query: string, limit = 8): CardIndexEntry[] {
  const key = query.trim().toLowerCase();
  if (!key) return [...CARD_INDEX].sort(byCleanName).slice(0, limit);

  return CARD_INDEX
    .filter(
      entry =>
        entry.clean_name.toLowerCase().startsWith(key) ||
        toSlug(entry.clean_name).startsWith(key),
    )
    .sort(byCleanName)
    .slice(0, limit);
}

export type { CardIndexEntry };
