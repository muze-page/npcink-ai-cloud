#!/usr/bin/env node
/* eslint-disable no-console */

const assert = require( 'assert' );
const fs = require( 'fs' );
const path = require( 'path' );

const {
	checkProviderEnvRetirement,
} = require( './check-provider-env-retirement.js' );

const cloudRoot = path.resolve( __dirname, '..' );
const tempRoot = path.join( cloudRoot, '.tmp', 'provider-env-retirement-test' );

function writeFile( filePath, contents ) {
	fs.mkdirSync( path.dirname( filePath ), { recursive: true } );
	fs.writeFileSync( filePath, contents );
}

try {
	writeFile(
		path.join( tempRoot, '.env.example' ),
		[
			'NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TIMEOUT_SECONDS=10',
			'# NPCINK_CLOUD_WEB_SEARCH_TAVILY_API_KEY is a retired provider env key.',
			'AI provider channels are managed in /admin/ai-resources.',
		].join( '\n' )
	);
	writeFile(
		path.join( tempRoot, 'deploy', 'README.md' ),
		'export NPCINK_CLOUD_OPENAI_API_KEY=replace-me\n'
	);

	const failingResult = checkProviderEnvRetirement( { root: tempRoot } );
	assert.deepStrictEqual(
		failingResult.violations.map( ( item ) => item.envKey ),
		[ 'NPCINK_CLOUD_OPENAI_API_KEY' ]
	);

	writeFile(
		path.join( tempRoot, 'deploy', 'README.md' ),
		'Provider secrets are configured through provider connections.\n'
	);
	const passingResult = checkProviderEnvRetirement( { root: tempRoot } );
	assert.deepStrictEqual( passingResult.violations, [] );

	const workspaceResult = checkProviderEnvRetirement( { root: cloudRoot } );
	assert.deepStrictEqual( workspaceResult.violations, [] );

	console.log( '[ok] provider env retirement tests passed.' );
} finally {
	fs.rmSync( tempRoot, { recursive: true, force: true } );
}
