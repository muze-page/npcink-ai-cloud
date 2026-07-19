#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const rootDir = path.resolve(__dirname, '..');
const rootPackagePath = path.join(rootDir, 'package.json');
const frontendPackagePath = path.join(rootDir, 'frontend', 'package.json');
const rootLockPath = path.join(rootDir, 'pnpm-lock.yaml');
const frontendLockPath = path.join(rootDir, 'frontend', 'pnpm-lock.yaml');
const workspacePath = path.join(rootDir, 'pnpm-workspace.yaml');

function readJson(filePath) {
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

const problems = [];
for (const requiredPath of [rootPackagePath, frontendPackagePath, rootLockPath, workspacePath]) {
	if (!fs.existsSync(requiredPath)) {
		problems.push(`missing required workspace file: ${path.relative(rootDir, requiredPath)}`);
	}
}

if (fs.existsSync(frontendLockPath)) {
	problems.push('frontend/pnpm-lock.yaml must not exist; pnpm-lock.yaml is the only dependency lock');
}

const rootPackage = fs.existsSync(rootPackagePath) ? readJson(rootPackagePath) : {};
const packageManager = String(rootPackage.packageManager || '');
const packageManagerMatch = /^pnpm@(\d+\.\d+\.\d+)\+sha512\.([0-9a-f]{128})$/.exec(
	packageManager
);
if (!packageManagerMatch) {
	problems.push('package.json packageManager must pin pnpm with an exact sha512 integrity');
}

if (problems.length > 0) {
	console.error('Frontend dependency lock contract failed.');
	for (const problem of problems) {
		console.error(`- ${problem}`);
	}
	process.exit(1);
}

const expectedPnpmVersion = packageManagerMatch[1];
const versionCheck = spawnSync('pnpm', ['--version'], {
	cwd: rootDir,
	encoding: 'utf8',
	shell: false,
});
const actualPnpmVersion = typeof versionCheck.stdout === 'string' ? versionCheck.stdout.trim() : '';
if (versionCheck.status !== 0 || actualPnpmVersion !== expectedPnpmVersion) {
	console.error(
		`Frontend lock verification requires ${packageManager}; run \`corepack enable && corepack install\` from the repository root.`
	);
	process.exit(1);
}

const frozenCheck = spawnSync(
	'pnpm',
	['install', '--frozen-lockfile', '--lockfile-only', '--ignore-scripts'],
	{
		cwd: rootDir,
		encoding: 'utf8',
		env: { ...process.env, CI: 'true' },
		shell: false,
	}
);
if (frozenCheck.status !== 0) {
	console.error('Root pnpm-lock.yaml does not satisfy the frontend workspace package.');
	const failureOutput = [frozenCheck.stdout, frozenCheck.stderr]
		.filter((value) => typeof value === 'string' && value.trim())
		.map((value) => value.trim())
		.join('\n');
	if (failureOutput) {
		console.error(failureOutput);
	}
	console.error('Refresh the root lock from the repository root, then rerun this check.');
	process.exit(1);
}

console.log(`Frontend dependency lock is valid (${packageManager}; root pnpm-lock.yaml).`);
