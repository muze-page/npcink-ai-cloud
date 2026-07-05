import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const unitDir = dirname(fileURLToPath(import.meta.url));

export const frontendRoot = resolve(unitDir, '../..');

export function fromFrontendRoot(...segments) {
  return resolve(frontendRoot, ...segments);
}
