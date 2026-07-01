import { redirect } from 'next/navigation';

export default function AdminHostedModelsRedirectPage() {
  redirect('/admin/ai-resources?view=diagnostics');
}
