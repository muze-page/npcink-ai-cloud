import { redirect } from 'next/navigation';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function AdminRecognitionRedirectPage(
  props: {
    searchParams?: Promise<SearchParams> | SearchParams;
  }
) {
  const searchParams = await Promise.resolve(props.searchParams || {});
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, item));
    } else if (typeof value === 'string') {
      params.set(key, value);
    }
  }
  const query = params.toString();
  redirect(query ? `/admin/model-intelligence?${query}` : '/admin/model-intelligence');
}
