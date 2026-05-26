export async function readResponsePayload<T = unknown>(
  response: Response
): Promise<T | { message: string; error_code?: string }> {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      return (await response.json()) as T;
    } catch {
      return {
        message: `HTTP ${response.status}`,
        error_code: 'proxy.invalid_json_response',
      };
    }
  }

  return {
    message: (await response.text()) || `HTTP ${response.status}`,
    error_code: 'proxy.non_json_response',
  };
}
