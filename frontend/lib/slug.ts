import sections from '@/content/sections.json';

export function sectionToSlug(section: string): string | null {
  return (sections as Record<string, string>)[section] ?? null;
}
