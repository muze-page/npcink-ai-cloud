import { redirect } from 'next/navigation';

export default async function AdminModelIntelligenceDetailRedirectPage(
  props: {
    params: Promise<{ providerId: string; modelPath: string[] }>;
  }
) {
  const { providerId, modelPath } = await props.params;
  const modelId = modelPath.join('/');
  redirect(
    `/admin/model-intelligence?provider_id=${encodeURIComponent(providerId)}&model_id=${encodeURIComponent(modelId)}`
  );
}
