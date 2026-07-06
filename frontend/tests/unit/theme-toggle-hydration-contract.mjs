import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = readFileSync(resolve(process.cwd(), 'src/components/ui/ThemeToggle.tsx'), 'utf8');

assert.match(
  source,
  /const handleToggleTheme = \(\) => \{[\s\S]*if \(!mounted\) \{[\s\S]*return;[\s\S]*toggleTheme\(\);[\s\S]*\};/,
  'ThemeToggle must guard theme changes until the client has mounted'
);

assert.doesNotMatch(
  source,
  /disabled=\{!mounted\}|disabled=\{mounted \? false : true\}/,
  'ThemeToggle must not bind mounted state to the disabled attribute because it causes hydration mismatches after dev refresh'
);

console.log('theme_toggle_hydration_contract: ok');
