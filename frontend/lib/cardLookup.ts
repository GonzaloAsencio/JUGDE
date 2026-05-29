import { CARD_INDEX, type CardIndexEntry } from '@/lib/cardIndex';

const BY_NAME: Map<string, CardIndexEntry> = new Map(
  CARD_INDEX.map(entry => [entry.clean_name.toLowerCase(), entry]),
);

export function lookupCard(name: string): CardIndexEntry | undefined {
  const key = name.trim().toLowerCase();
  if (!key) return undefined;
  return BY_NAME.get(key);
}

export type { CardIndexEntry };
