#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'fs' );
const path = require( 'path' );

const cloudRoot = path.resolve( __dirname, '..' );

const allowedRuntimeGuardrailKeys = new Set( [
	'NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TIMEOUT_SECONDS',
] );

const forbiddenProviderAssignmentPattern =
	/^\s*(?:export\s+)?(NPCINK_CLOUD_(?:(?:WEB_SEARCH|IMAGE_SOURCE)_[A-Z0-9_]+|(?:OPENAI|OPENAI_COMPATIBLE|MINIMAX|ANTHROPIC|OPENROUTER|SILICONFLOW|TEI)_[A-Z0-9_]+|SITE_KNOWLEDGE_(?:EMBEDDING|JINA|ZILLIZ|RERANK_PROVIDER|VECTOR_BACKEND)[A-Z0-9_]*))\s*=/u;

function normalizePath( value ) {
	return String( value || '' ).replace( /\\/gu, '/' ).replace( /\/+/gu, '/' );
}

function listFilesRecursive( directory ) {
	if ( ! fs.existsSync( directory ) ) {
		return [];
	}

	return fs.readdirSync( directory, { withFileTypes: true } ).flatMap( ( entry ) => {
		const fullPath = path.join( directory, entry.name );
		if ( entry.isDirectory() ) {
			return listFilesRecursive( fullPath );
		}
		return [ fullPath ];
	} );
}

function defaultFiles( root ) {
	const deployFiles = listFilesRecursive( path.join( root, 'deploy' ) ).filter(
		( filePath ) =>
			/\.(?:md|sh|env|yml|yaml|template)$/u.test( filePath ) ||
			path.basename( filePath ).includes( 'Caddyfile' )
	);

	return [
		path.join( root, '.env.example' ),
		path.join( root, 'frontend', '.env.example' ),
		path.join( root, 'README.md' ),
		...deployFiles,
	].filter( ( filePath ) => fs.existsSync( filePath ) );
}

function toDisplayPath( root, filePath ) {
	const relative = path.relative( root, filePath );
	return normalizePath( relative && ! relative.startsWith( '..' ) ? relative : filePath );
}

function checkProviderEnvRetirement( options = {} ) {
	const root = options.root ? path.resolve( options.root ) : cloudRoot;
	const files = ( options.files && options.files.length > 0
		? options.files.map( ( file ) => path.resolve( root, file ) )
		: defaultFiles( root )
	).filter( ( filePath ) => fs.existsSync( filePath ) );

	const violations = [];

	for ( const filePath of files ) {
		const source = fs.readFileSync( filePath, 'utf8' );
		source.split( /\r?\n/u ).forEach( ( line, index ) => {
			const match = line.match( forbiddenProviderAssignmentPattern );
			if ( ! match ) {
				return;
			}

			const envKey = String( match[ 1 ] || '' );
			if ( allowedRuntimeGuardrailKeys.has( envKey ) ) {
				return;
			}

			violations.push( {
				file: toDisplayPath( root, filePath ),
				line: index + 1,
				envKey,
			} );
		} );
	}

	return {
		files: files.map( ( filePath ) => toDisplayPath( root, filePath ) ),
		violations,
	};
}

function parseArgs( args ) {
	let root = cloudRoot;
	const files = [];
	for ( let index = 0; index < args.length; index += 1 ) {
		const value = args[ index ];
		if ( value === '--root' ) {
			root = path.resolve( String( args[ index + 1 ] || '' ) );
			index += 1;
			continue;
		}
		if ( value === '--' ) {
			continue;
		}
		files.push( value );
	}
	return { root, files };
}

if ( require.main === module ) {
	const { root, files } = parseArgs( process.argv.slice( 2 ) );
	const result = checkProviderEnvRetirement( { root, files } );

	if ( result.violations.length > 0 ) {
		console.error( '[provider-env-retirement] provider env assignments found.' );
		result.violations.forEach( ( item ) => {
			console.error( `- ${ item.file }:${ item.line } ${ item.envKey }` );
		} );
		console.error(
			'Move provider credentials/configuration to /admin/ai-resources provider connections. Keep only runtime guardrails in env files.'
		);
		process.exit( 1 );
	}

	console.log(
		`[ok] provider env retirement passed (${ result.files.length } files scanned).`
	);
}

module.exports = {
	checkProviderEnvRetirement,
};
