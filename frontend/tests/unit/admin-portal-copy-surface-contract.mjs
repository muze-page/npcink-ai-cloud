import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = process.cwd();
const scanRoots = [
  'src/app/admin',
  'src/app/portal',
  'src/components/backoffice',
  'src/components/portal',
  'src/lib/i18n.ts',
].map((item) => join(root, item));

const blockedCopy = [
  { pattern: /\bTARGET_PACKAGE\b/, reason: 'raw request payload key' },
  { pattern: /\bEXPECTED_SITES\b/, reason: 'raw request payload key' },
  { pattern: /\bEXPECTED_USAGE\b/, reason: 'raw request payload key' },
  { pattern: /\bCURRENT_ROLE\b/, reason: 'raw request payload key' },
  { pattern: /\bPLAN_ID\b/, reason: 'raw technical field key' },
  { pattern: /Package management center/, reason: 'old package page title' },
  { pattern: /Create this package before assigning it to customers/, reason: 'stale package setup copy' },
  { pattern: /materialize missing/i, reason: 'implementation wording in user-facing copy' },
  { pattern: /canonical package shell/i, reason: 'implementation wording in user-facing copy' },
];

function listFiles(path) {
  const stat = statSync(path);
  if (stat.isFile()) {
    return [path];
  }
  return readdirSync(path).flatMap((entry) => {
    const child = join(path, entry);
    if (statSync(child).isDirectory()) {
      return listFiles(child);
    }
    return /\.(tsx|ts)$/.test(child) ? [child] : [];
  });
}

const offenders = [];

for (const file of scanRoots.flatMap(listFiles)) {
  const source = readFileSync(file, 'utf8');
  const lines = source.split('\n');
  lines.forEach((line, index) => {
    for (const rule of blockedCopy) {
      if (rule.pattern.test(line)) {
        offenders.push(`${relative(root, file)}:${index + 1} ${rule.reason}: ${line.trim()}`);
      }
    }
  });
}

if (offenders.length) {
  console.error('User-facing admin/portal copy contains raw or stale technical wording:\n');
  console.error(offenders.join('\n'));
  process.exit(1);
}

console.log('Admin/portal copy surface contract passed.');
