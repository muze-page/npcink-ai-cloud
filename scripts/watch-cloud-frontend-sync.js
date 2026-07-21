#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'node:fs' );
const path = require( 'node:path' );
const { spawn } = require( 'node:child_process' );

const cloudRoot = path.resolve( __dirname, '..' );
const frontendRoot = path.join( cloudRoot, 'frontend' );
const frontendUrl = 'http://127.0.0.1:8010';
const composeArgs = [ 'compose', '-f', 'docker-compose.dev.yml' ];
const debounceMs = 900;

const defaultChecks = [ 'pnpm type-check' ];
const recreateFiles = new Set( [
	'.env',
	'docker-compose.dev.yml',
	'deploy/nginx.dev.conf',
	'frontend/.env',
	'frontend/next.config.mjs',
	'frontend/postcss.config.mjs',
	'frontend/tailwind.config.ts',
	'frontend/tsconfig.json',
] );
const rebuildFiles = new Set( [
	'.dockerignore',
	'package.json',
	'pnpm-lock.yaml',
	'pnpm-workspace.yaml',
	'frontend/Dockerfile.dev',
	'frontend/package.json',
] );

function parseArgs( argv ) {
	const options = {
		checks: [],
		noCheck: false,
		once: false,
	};

	for ( let index = 0; index < argv.length; index += 1 ) {
		const value = argv[ index ];
		if ( value === '--no-check' ) {
			options.noCheck = true;
			continue;
		}
		if ( value === '--once' ) {
			options.once = true;
			continue;
		}
		if ( value === '--check' ) {
			const command = argv[ index + 1 ];
			if ( ! command ) {
				throw new Error( '--check requires a command value.' );
			}
			options.checks.push( command );
			index += 1;
			continue;
		}
		throw new Error( `Unknown argument: ${ value }` );
	}

	if ( ! options.noCheck && options.checks.length === 0 ) {
		options.checks = [ ...defaultChecks ];
	}

	return options;
}

function relPath( filePath ) {
	return path.relative( cloudRoot, filePath ).split( path.sep ).join( '/' );
}

function shouldIgnorePath( relativePath ) {
	return (
		relativePath.includes( '/node_modules/' ) ||
		relativePath.endsWith( '/node_modules' ) ||
		relativePath.includes( '/.next/' ) ||
		relativePath.endsWith( '/.next' ) ||
		relativePath.endsWith( '.tsbuildinfo' )
	);
}

function classifyPaths( changedPaths ) {
	let action = 'source';

	for ( const relativePath of changedPaths ) {
		if ( rebuildFiles.has( relativePath ) ) {
			return 'rebuild';
		}
		if ( recreateFiles.has( relativePath ) ) {
			action = 'recreate';
		}
	}

	return action;
}

function log( message ) {
	const timestamp = new Date().toLocaleTimeString( 'zh-CN', {
		hour12: false,
	} );
	console.log( `[cloud-frontend-sync ${ timestamp }] ${ message }` );
}

function runCommand( command, args, options = {} ) {
	return new Promise( ( resolve, reject ) => {
		const child = spawn( command, args, {
			cwd: options.cwd || cloudRoot,
			stdio: 'inherit',
			shell: false,
		} );
		child.on( 'error', reject );
		child.on( 'exit', ( code ) => {
			if ( code === 0 ) {
				resolve();
				return;
			}
			reject( new Error( `${ command } ${ args.join( ' ' ) } exited with code ${ code }` ) );
		} );
	} );
}

function runShellCommand( command, cwd ) {
	return new Promise( ( resolve, reject ) => {
		const child = spawn( command, {
			cwd,
			stdio: 'inherit',
			shell: true,
		} );
		child.on( 'error', reject );
		child.on( 'exit', ( code ) => {
			if ( code === 0 ) {
				resolve();
				return;
			}
			reject( new Error( `${ command } exited with code ${ code }` ) );
		} );
	} );
}

async function waitForFrontend( attempts = 20, intervalMs = 750 ) {
	for ( let index = 0; index < attempts; index += 1 ) {
		try {
			const response = await fetch( frontendUrl, {
				method: 'HEAD',
			} );
			if ( response.ok ) {
				return true;
			}
		} catch ( error ) {
			// Ignore probe errors until the final retry.
		}
		await new Promise( ( resolve ) => setTimeout( resolve, intervalMs ) );
	}

	return false;
}

async function ensureFrontendAvailable() {
	const ready = await waitForFrontend( 2, 400 );
	if ( ready ) {
		return;
	}

	log( 'Unified preview is not ready. Starting frontend and proxy in Docker.' );
	await runCommand( 'docker', [ ...composeArgs, 'up', '-d', 'frontend', 'proxy' ] );

	const available = await waitForFrontend();
	if ( ! available ) {
		throw new Error( `Frontend did not become reachable at ${ frontendUrl }.` );
	}
}

async function runChecks( checks ) {
	for ( const checkCommand of checks ) {
		log( `Running check: ${ checkCommand }` );
		await runShellCommand( checkCommand, frontendRoot );
	}
}

async function syncDocker( action ) {
	if ( action === 'source' ) {
		await ensureFrontendAvailable();
		log( 'Source-only change detected. Bind mount + Next dev will hot-reload automatically.' );
		return;
	}

	if ( action === 'recreate' ) {
		log( 'Config change detected. Recreating frontend and proxy containers.' );
		await runCommand( 'docker', [ ...composeArgs, 'up', '-d', '--force-recreate', 'frontend', 'proxy' ] );
	} else {
		log( 'Dependency/container change detected. Rebuilding frontend container, refreshing anonymous volumes, and recreating proxy.' );
		await runCommand( 'docker', [
			...composeArgs,
			'up',
			'-d',
			'--build',
			'--force-recreate',
			'--renew-anon-volumes',
			'frontend',
			'proxy',
		] );
	}

	const available = await waitForFrontend();
	if ( ! available ) {
		throw new Error( `Frontend did not become reachable at ${ frontendUrl } after Docker sync.` );
	}
	log( `Frontend ready: ${ frontendUrl }` );
}

function createWatchTargets() {
	const targets = [];
	const recursiveDirs = [
		path.join( frontendRoot, 'src' ),
		path.join( frontendRoot, 'public' ),
		path.join( frontendRoot, 'tests' ),
	];
	const directFiles = [
		path.join( cloudRoot, '.env' ),
		path.join( cloudRoot, 'docker-compose.dev.yml' ),
		path.join( cloudRoot, 'package.json' ),
		path.join( cloudRoot, 'pnpm-lock.yaml' ),
		path.join( cloudRoot, 'pnpm-workspace.yaml' ),
		path.join( frontendRoot, '.env' ),
		path.join( cloudRoot, '.dockerignore' ),
		path.join( frontendRoot, 'Dockerfile.dev' ),
		path.join( frontendRoot, 'next.config.mjs' ),
		path.join( frontendRoot, 'package.json' ),
		path.join( frontendRoot, 'postcss.config.mjs' ),
		path.join( frontendRoot, 'tailwind.config.ts' ),
		path.join( frontendRoot, 'tsconfig.json' ),
	];

	for ( const directory of recursiveDirs ) {
		if ( fs.existsSync( directory ) ) {
			targets.push( { path: directory, recursive: true } );
		}
	}

	for ( const filePath of directFiles ) {
		if ( fs.existsSync( filePath ) ) {
			targets.push( { path: filePath, recursive: false } );
		}
	}

	return targets;
}

async function main() {
	const options = parseArgs( process.argv.slice( 2 ) );
	const changedPaths = new Set();
	let timer = null;
	let running = false;
	let rerunQueued = false;

	const processChanges = async () => {
		if ( running ) {
			rerunQueued = true;
			return;
		}

		if ( changedPaths.size === 0 ) {
			return;
		}

		const batch = [ ...changedPaths ];
		changedPaths.clear();
		running = true;
		const action = classifyPaths( batch );

		try {
			log( `Detected changes: ${ batch.join( ', ' ) }` );
			if ( ! options.noCheck ) {
				await runChecks( options.checks );
				log( 'Checks passed.' );
			} else {
				log( 'Checks skipped by --no-check.' );
			}
			await syncDocker( action );
		} catch ( error ) {
			const message = error instanceof Error ? error.message : String( error );
			log( `Sync aborted: ${ message }` );
		} finally {
			running = false;
			if ( rerunQueued || changedPaths.size > 0 ) {
				rerunQueued = false;
				void processChanges();
			}
		}
	};

	const scheduleProcessing = () => {
		if ( timer ) {
			clearTimeout( timer );
		}
		timer = setTimeout( () => {
			timer = null;
			void processChanges();
		}, debounceMs );
	};

	if ( options.once ) {
		changedPaths.add( 'frontend/src' );
		await processChanges();
		return;
	}

	const targets = createWatchTargets();
	if ( targets.length === 0 ) {
		throw new Error( 'No watch targets found for cloud frontend sync.' );
	}

	for ( const target of targets ) {
		fs.watch(
			target.path,
			{ recursive: target.recursive },
			( _eventType, fileName ) => {
				const resolvedPath = fileName
					? target.recursive
						? path.resolve( target.path, String( fileName ) )
						: path.resolve( path.dirname( target.path ), String( fileName ) )
					: target.path;
				const relativePath = relPath( resolvedPath );
				if ( shouldIgnorePath( relativePath ) ) {
					return;
				}
				changedPaths.add( relativePath );
				scheduleProcessing();
			}
		);
	}

	log( `Watching Cloud frontend changes. Preview URL: ${ frontendUrl }` );
	log( `Checks: ${ options.noCheck ? 'skipped' : options.checks.join( ' | ' ) }` );
}

main().catch( ( error ) => {
	console.error( error instanceof Error ? error.message : String( error ) );
	process.exit( 1 );
} );
