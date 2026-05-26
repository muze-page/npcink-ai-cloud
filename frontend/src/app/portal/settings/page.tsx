import { redirect } from 'next/navigation';

export default async function PortalSettingsCompatibilityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        query.append(key, item);
      }
      continue;
    }
    if (typeof value === 'string') {
      query.set(key, value);
    }
  }

  redirect(`/portal/preferences${query.toString() ? `?${query.toString()}` : ''}`);
}
