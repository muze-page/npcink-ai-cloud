#!/usr/bin/env node
/* eslint-disable no-console */

const assert = require( 'assert' );
const fs = require( 'fs' );
const path = require( 'path' );

const { checkCloudAntiDrift } = require( './check-cloud-anti-drift.js' );

const cloudRoot = path.resolve( __dirname, '..' );
const tempRoot = path.join( cloudRoot, '.tmp', 'anti-drift-test' );
const contractPath = path.join( tempRoot, 'task-contract-anti-drift-test.json' );
const hardcodedAdminFile = path.join(
	cloudRoot,
	'frontend',
	'src',
	'app',
	'admin',
	'__anti_drift_tmp__',
	'page.tsx'
);
const projectedPortalFile = path.join(
	cloudRoot,
	'frontend',
	'src',
	'app',
	'portal',
	'__anti_drift_tmp__',
	'page.tsx'
);
const testFixtureFile = path.join(
	tempRoot,
	'tests',
	'assertions',
	'metadata-projection.test.ts'
);

function writeFile( filePath, contents ) {
	fs.mkdirSync( path.dirname( filePath ), { recursive: true } );
	fs.writeFileSync( filePath, contents );
}

function relativeToCloudRoot( filePath ) {
	return path.relative( cloudRoot, filePath ).replace( /\\/gu, '/' );
}

function hasViolations( result ) {
	return Object.values( result.violations ).some( ( items ) => items.length > 0 );
}

try {
	writeFile(
		contractPath,
		JSON.stringify(
			{
				change_classification: 'cloud detail',
				truth_owner: 'cloud read-only metadata projection',
				final_write_owner: 'wordpress_local',
				fail_closed_expectation: 'block page-local metadata drift',
				human_review_required: false,
				required_docs: [],
				required_gates: [],
			},
			null,
			2
		)
	);

	writeFile(
		hardcodedAdminFile,
		"export const agentId = 'internal_ops_advisor_agent';\n"
	);
	const hardcodedResult = checkCloudAntiDrift( {
		contractPath,
		files: [ relativeToCloudRoot( hardcodedAdminFile ) ],
	} );
	assert.strictEqual( hardcodedResult.is_cloud_task, true );
	assert.match(
		hardcodedResult.violations.metadata_projection_hardcoding.join( '\n' ),
		/internal_ops_advisor_agent/u
	);

	writeFile(
		projectedPortalFile,
		"export const metadata = response.agent_metadata_projection;\n"
	);
	const projectedResult = checkCloudAntiDrift( {
		contractPath,
		files: [ relativeToCloudRoot( projectedPortalFile ) ],
	} );
	assert.strictEqual( hasViolations( projectedResult ), false );
	assert.deepStrictEqual(
		projectedResult.violations.metadata_projection_boundary_doc_missing,
		[]
	);

	writeFile(
		testFixtureFile,
		"assert.equal(data.workflow_id, 'external_web_evidence_preflight');\n"
	);
	const testResult = checkCloudAntiDrift( {
		contractPath,
		files: [ relativeToCloudRoot( testFixtureFile ) ],
	} );
	assert.strictEqual( hasViolations( testResult ), false );

	console.log( '[ok] cloud anti-drift metadata projection tests passed.' );
} finally {
	fs.rmSync( path.dirname( hardcodedAdminFile ), { recursive: true, force: true } );
	fs.rmSync( path.dirname( projectedPortalFile ), { recursive: true, force: true } );
	fs.rmSync( tempRoot, { recursive: true, force: true } );
}
