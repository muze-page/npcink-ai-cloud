type TranslateFn = (key: string, vars?: Record<string, string>, fallback?: string) => string;

export function normalizeStatusToken(value?: string | null): string {
  return String(value || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_') || 'unknown';
}

export function humanizeStatusToken(value?: string | null): string {
  return normalizeStatusToken(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function translateStatusLabel(
  value: string | null | undefined,
  t: TranslateFn,
  fallback?: string
): string {
  const normalized = normalizeStatusToken(value);
  return t(`status.${normalized}`, undefined, fallback || humanizeStatusToken(normalized));
}
