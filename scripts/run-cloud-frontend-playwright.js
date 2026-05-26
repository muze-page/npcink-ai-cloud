#!/usr/bin/env node

const os = require( 'node:os' );
const path = require( 'node:path' );
const { spawnSync } = require( 'node:child_process' );

const cloudRoot = path.resolve( __dirname, '..' );
const repoRoot = path.resolve( cloudRoot, '..' );
const frontendRoot = path.join( cloudRoot, 'frontend' );
const defaultBrowsersPath = path.join(
	os.homedir(),
	'.local',
	'share',
	'magick-ai-playwright'
);
const cliPath = require.resolve( '@playwright/test/cli', {
	paths: [ frontendRoot, cloudRoot, repoRoot ],
} );
const args = process.argv.slice( 2 );
const childEnv = {
	...process.env,
	PLAYWRIGHT_BROWSERS_PATH:
		process.env.PLAYWRIGHT_BROWSERS_PATH || defaultBrowsersPath,
};

if ( childEnv.NO_COLOR ) {
	delete childEnv.NO_COLOR;
}

if ( args.length === 0 ) {
	console.error(
		'Usage: node scripts/run-cloud-frontend-playwright.js test [playwright args...]'
	);
	process.exit( 1 );
}

const result = spawnSync(
	process.execPath,
	[ cliPath, ...args ],
	{
		cwd: frontendRoot,
		stdio: 'pipe',
		env: childEnv,
	}
);

if ( result.stdout ) {
	process.stdout.write( result.stdout );
}

if ( result.stderr ) {
	process.stderr.write( result.stderr );
}

const combinedOutput = `${ result.stdout || '' }\n${ result.stderr || '' }`;

if (
	( result.status ?? 1 ) !== 0 &&
	combinedOutput.includes( 'Executable doesn\'t exist' )
) {
	console.error( '\nCloud frontend Playwright browser is missing.' );
	console.error(
		`Install Chromium with: PLAYWRIGHT_BROWSERS_PATH=${ childEnv.PLAYWRIGHT_BROWSERS_PATH } pnpm --dir ${ frontendRoot } run playwright:browsers:install:chromium`
	);
	console.error(
		`Current shared browser cache path: ${ childEnv.PLAYWRIGHT_BROWSERS_PATH }`
	);
}

process.exit( result.status ?? 1 );
