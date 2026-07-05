#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const rootDir = process.cwd();
const frontendPackagePath = path.join(rootDir, 'frontend', 'package.json');
const rootLockPath = path.join(rootDir, 'pnpm-lock.yaml');
const frontendLockPath = path.join(rootDir, 'frontend', 'pnpm-lock.yaml');

function readJson(filePath) {
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function readText(filePath) {
	return fs.readFileSync(filePath, 'utf8');
}

function escapeRegExp(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getImporterBlock(lockText, importerName) {
	const lines = lockText.split(/\r?\n/);
	const importersIndex = lines.findIndex((line) => line === 'importers:');
	if (importersIndex === -1) {
		return '';
	}

	const importerHeader = `  ${importerName}:`;
	let startIndex = -1;
	for (let index = importersIndex + 1; index < lines.length; index += 1) {
		if (lines[index] === importerHeader) {
			startIndex = index;
			break;
		}
		if (/^\S/.test(lines[index]) && lines[index] !== 'importers:') {
			break;
		}
	}

	if (startIndex === -1) {
		return '';
	}

	let endIndex = lines.length;
	for (let index = startIndex + 1; index < lines.length; index += 1) {
		if (/^  [^ ].*:$/.test(lines[index]) || (/^\S/.test(lines[index]) && lines[index] !== 'importers:')) {
			endIndex = index;
			break;
		}
	}

	return lines.slice(startIndex, endIndex).join('\n');
}

function hasDependency(importerBlock, dependencyName) {
	const escapedName = escapeRegExp(dependencyName);
	return new RegExp(`^[ \\t]{6}['"]?${escapedName}['"]?:`, 'm').test(importerBlock);
}

const frontendPackage = readJson(frontendPackagePath);
const dependencyNames = Object.keys({
	...(frontendPackage.dependencies || {}),
	...(frontendPackage.devDependencies || {}),
}).sort();

const lockChecks = [
	{
		label: 'root pnpm-lock.yaml importer frontend',
		filePath: rootLockPath,
		importerName: 'frontend',
	},
	{
		label: 'frontend/pnpm-lock.yaml importer .',
		filePath: frontendLockPath,
		importerName: '.',
	},
];

const problems = [];
for (const check of lockChecks) {
	if (!fs.existsSync(check.filePath)) {
		problems.push(`${check.label}: missing file ${path.relative(rootDir, check.filePath)}`);
		continue;
	}

	const importerBlock = getImporterBlock(readText(check.filePath), check.importerName);
	if (!importerBlock) {
		problems.push(`${check.label}: missing importer ${check.importerName}`);
		continue;
	}

	for (const dependencyName of dependencyNames) {
		if (!hasDependency(importerBlock, dependencyName)) {
			problems.push(`${check.label}: missing ${dependencyName}`);
		}
	}
}

if (problems.length > 0) {
	console.error('Frontend dependency lock mismatch detected.');
	for (const problem of problems) {
		console.error(`- ${problem}`);
	}
	console.error('');
	console.error('After changing frontend/package.json dependencies, refresh both lockfiles:');
	console.error('  pnpm install --lockfile-only --no-frozen-lockfile');
	console.error('  pnpm --dir frontend install --lockfile-only --ignore-workspace --no-frozen-lockfile');
	process.exit(1);
}

console.log(`Frontend dependency locks are in sync (${dependencyNames.length} dependencies checked).`);
