#!/usr/bin/env node

const fs = require( 'node:fs' );
const os = require( 'node:os' );
const path = require( 'node:path' );

const cacheRoot =
	process.env.PLAYWRIGHT_BROWSERS_PATH ||
	path.join( os.homedir(), '.local', 'share', 'magick-ai-playwright' );
const apply = process.argv.includes( '--apply' );
const families = [ 'chromium-', 'chromium_headless_shell-' ];

function parseRevision( name, prefix ) {
	const raw = name.slice( prefix.length );
	const parsed = Number.parseInt( raw, 10 );
	return Number.isFinite( parsed ) ? parsed : null;
}

if ( !fs.existsSync( cacheRoot ) ) {
	console.log( `Playwright browser cache not found: ${ cacheRoot }` );
	process.exit( 0 );
}

const entries = fs
	.readdirSync( cacheRoot, { withFileTypes: true } )
	.filter( ( entry ) => entry.isDirectory() || entry.isSymbolicLink() )
	.map( ( entry ) => entry.name );

const staleTargets = [];

for ( const prefix of families ) {
	const matching = entries
		.filter( ( name ) => name.startsWith( prefix ) )
		.map( ( name ) => ( {
			name,
			revision: parseRevision( name, prefix ),
		} ) )
		.filter( ( item ) => item.revision !== null )
		.sort( ( left, right ) => right.revision - left.revision );

	if ( matching.length <= 1 ) {
		continue;
	}

	staleTargets.push(
		...matching.slice( 1 ).map( ( item ) => path.join( cacheRoot, item.name ) )
	);
}

if ( staleTargets.length === 0 ) {
	console.log( `No stale Playwright Chromium cache entries found in ${ cacheRoot }` );
	process.exit( 0 );
}

if ( !apply ) {
	console.log( `Stale Playwright Chromium cache entries in ${ cacheRoot }:` );
	for ( const target of staleTargets ) {
		console.log( `- ${ target }` );
	}
	console.log( '\nRun with --apply to remove these directories.' );
	process.exit( 0 );
}

for ( const target of staleTargets ) {
	fs.rmSync( target, { recursive: true, force: true } );
	console.log( `Removed ${ target }` );
}
