#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'fs' );
const path = require( 'path' );
const cloudRoot = path.resolve( __dirname, '..' );
const workspaceRoot = cloudRoot;
const manifestPath = path.join(
	cloudRoot,
	'config',
	'cloud-anti-drift-high-risk-surfaces-v1.json'
);
const validChangeClassification = new Set( [
	'local truth',
	'cloud runtime',
	'cloud detail',
	'forbidden',
] );
const metadataProjectionPath = path.join(
	cloudRoot,
	'app',
	'domain',
	'agent_workflow_metadata.py'
);
const metadataProjectionBoundaryDocPath = path.join(
	cloudRoot,
	'docs',
	'cloud-agent-workflow-metadata-projection-v1.md'
);
const metadataProjectionBoundaryDocRequiredPhrases = [
	'not become a second ability registry, workflow registry, approval system, or',
	'WordPress write owner',
	'The preferred product term is metadata projection',
	'not allowed to be a Cloud control-plane truth',
	'no WordPress writes',
	'no approval or auto-apply state',
	'no workflow execution engine',
	'no local ability registry replacement',
	'no prompt, preset, router, MCP, or OpenClaw truth',
	'static UI metadata and redacted boundary projection',
	'metadata projection only supplies static UI metadata',
	'not as authority for running or approving work',
];

function readText( filePath ) {
	return fs.readFileSync( filePath, 'utf8' );
}

function readJson( filePath ) {
	return JSON.parse( readText( filePath ) );
}

function exists( filePath ) {
	return fs.existsSync( filePath );
}

function readTextIfExists( filePath ) {
	if ( ! exists( filePath ) ) {
		return '';
	}

	return readText( filePath );
}

function orderedUniq( values ) {
	return Array.from( new Set( values.filter( Boolean ) ) );
}

function normalizePath( value ) {
	return String( value || '' ).replace( /\\/gu, '/' ).replace( /\/+/gu, '/' );
}

function listChangedFiles( root ) {
	const { execFileSync } = require( 'child_process' );
	const commands = [
		[ 'diff', '--name-only', '--cached', '--diff-filter=ACMR' ],
		[ 'diff', '--name-only', '--diff-filter=ACMR' ],
		[ 'ls-files', '--others', '--exclude-standard' ],
	];
	const files = [];
	for ( const args of commands ) {
		const output = execFileSync( 'git', args, { cwd: root, encoding: 'utf8' } );
		output.split( /\r?\n/u ).forEach( ( line ) => {
			if ( line.trim() ) {
				files.push( normalizePath( line.trim() ) );
			}
		} );
	}
	return orderedUniq( files );
}

function toWorkspaceValue( value ) {
	if ( ! value ) {
		return '';
	}

	let normalized = normalizePath( value );

	if ( path.isAbsolute( normalized ) ) {
		const relative = path.relative( workspaceRoot, normalized );
		if ( relative && ! relative.startsWith( '..' ) ) {
			normalized = normalizePath( relative );
		}
	}

	normalized = normalized.replace( /^(\.\.\/)+/u, '' );

	return normalized;
}

function globToRegExp( pattern ) {
	const escaped = pattern
		.replace( /[.+^${}()|[\]\\]/gu, '\\$&' )
		.replace( /\*\*/gu, '::double-star::' )
		.replace( /\*/gu, '[^/]*' )
		.replace( /::double-star::/gu, '.*' );

	return new RegExp( `^${ escaped }$`, 'u' );
}

function matchesPattern( file, pattern ) {
	return globToRegExp( pattern ).test( file );
}

function isAdminPortalFrontendSource( file ) {
	return (
		/^frontend\/src\/app\/(?:admin|portal)\//u.test( file ) &&
		/\.(?:js|jsx|ts|tsx)$/u.test( file )
	);
}

function loadAgentWorkflowMetadataProjectionTokens() {
	const source = readTextIfExists( metadataProjectionPath );
	const tokens = [];
	const patterns = [
		/(?:METADATA_PROJECTION_VERSION|COMPATIBILITY_REGISTRY_VERSION|[A-Z0-9_]*(?:AGENT_ID|WORKFLOW_ID))\s*=\s*"([^"]+)"/gu,
		/(?:agent_version|workflow_version)\s*=\s*"([^"]+)"/gu,
	];

	for ( const pattern of patterns ) {
		let match = pattern.exec( source );
		while ( match ) {
			tokens.push( String( match[ 1 ] || '' ).trim() );
			match = pattern.exec( source );
		}
	}

	return orderedUniq( tokens );
}

function checkAgentWorkflowMetadataProjectionBoundaryDoc() {
	const source = readTextIfExists( metadataProjectionBoundaryDocPath );
	const missing = metadataProjectionBoundaryDocRequiredPhrases.filter(
		( phrase ) => ! source.includes( phrase )
	);

	if ( missing.length === 0 ) {
		return [];
	}

	return missing.map(
		( phrase ) =>
			`docs/cloud-agent-workflow-metadata-projection-v1.md missing metadata projection boundary phrase: ${ phrase }`
	);
}

function parseContractFile( filePath ) {
	const source = readText( filePath );

	if ( filePath.endsWith( '.json' ) ) {
		return JSON.parse( source );
	}

	try {
		return JSON.parse( source );
	} catch ( error ) {
		// Fall through to markdown fenced json.
	}

	const match = source.match( /```json\s*([\s\S]*?)```/u );
	if ( ! match ) {
		throw new Error(
			'Task contract must be JSON or contain a fenced ```json``` block.'
		);
	}

	return JSON.parse( String( match[ 1 ] || '' ).trim() );
}

function parseArgs( args ) {
	let contractPath = '';
	let wantsJson = false;
	const files = [];

	for ( let index = 0; index < args.length; index += 1 ) {
		const value = args[ index ];

		if ( value === '--' ) {
			continue;
		}

		if ( value === '--json' ) {
			wantsJson = true;
			continue;
		}

		if ( value === '--contract' ) {
			contractPath = String( args[ index + 1 ] || '' ).trim();
			index += 1;
			continue;
		}

		files.push( value );
	}

	return { contractPath, wantsJson, files };
}

function loadManifest() {
	if ( ! exists( manifestPath ) ) {
		throw new Error( `Missing cloud anti-drift manifest: ${ manifestPath }` );
	}

	const manifest = readJson( manifestPath );
	return {
		taskTriggerPatterns: Array.isArray( manifest.task_trigger_patterns )
			? manifest.task_trigger_patterns
			: [],
		governanceExemptPatterns: Array.isArray( manifest.governance_exempt_patterns )
			? manifest.governance_exempt_patterns
			: [],
		highRiskPatterns: Array.isArray( manifest.high_risk_patterns )
			? manifest.high_risk_patterns
			: [],
		forbiddenActivePatterns: Array.isArray( manifest.forbidden_active_patterns )
			? manifest.forbidden_active_patterns
			: [],
		highRiskFieldTokens: Array.isArray( manifest.high_risk_field_tokens )
			? manifest.high_risk_field_tokens.map( ( value ) =>
					String( value || '' ).trim()
			  ).filter( Boolean )
			: [],
		executableSeamPatterns: Array.isArray( manifest.executable_seam_patterns )
			? manifest.executable_seam_patterns
			: [],
		executableSeamBackstopPatterns: Array.isArray(
			manifest.executable_seam_backstop_patterns
		)
			? manifest.executable_seam_backstop_patterns
			: [],
	};
}

function discoverContractPath() {
	try {
		const entries = fs.readdirSync( workspaceRoot );
		const candidates = entries.filter(
			( entry ) =>
				entry.startsWith( 'task-contract-' ) && entry.endsWith( '.json' )
		);
		if ( candidates.length === 1 ) {
			return path.resolve( workspaceRoot, candidates[ 0 ] );
		}
	} catch {
		// ignore
	}
	return '';
}

function checkCloudAntiDrift( { contractPath, files } ) {
	const manifest = loadManifest();
	let absoluteContractPath = contractPath
		? path.isAbsolute( contractPath )
			? contractPath
			: path.resolve( workspaceRoot, contractPath )
		: '';

	if ( ! absoluteContractPath ) {
		absoluteContractPath = discoverContractPath();
	}

	const hasContract = absoluteContractPath && exists( absoluteContractPath );
	const contract = hasContract
		? parseContractFile( absoluteContractPath )
		: {};
	const changedFiles = orderedUniq(
		( files && files.length > 0 ? files : listChangedFiles( workspaceRoot ) ).map(
			toWorkspaceValue
		)
	);
	const changedFileContents = changedFiles.map( ( file ) => ( {
		file,
		source: readTextIfExists( path.resolve( workspaceRoot, file ) ),
	} ) );
	const functionalChangedFileContents = changedFileContents.filter(
		( item ) =>
			! manifest.governanceExemptPatterns.some( ( pattern ) =>
				matchesPattern( item.file, pattern )
			)
	);
	const contractRequiredDocs = Array.isArray( contract.required_docs )
		? contract.required_docs.map( toWorkspaceValue )
		: [];
	const contractRequiredGates = Array.isArray( contract.required_gates )
		? contract.required_gates.map( ( value ) => String( value || '' ).trim() )
		: [];

	const hasFunctionalCloudTrigger = changedFiles.some( ( file ) =>
		manifest.taskTriggerPatterns.some( ( pattern ) => matchesPattern( file, pattern ) ) &&
		! manifest.governanceExemptPatterns.some( ( pattern ) =>
			matchesPattern( file, pattern )
		)
	);
	const isCloudTask =
		String( contract.change_classification || '' ).trim() !== '' ||
		contractRequiredDocs.some( ( item ) => item.includes( 'cloud-' ) ) ||
		hasFunctionalCloudTrigger;
	const metadataProjectionHardcodingViolations = [];
	const metadataProjectionBoundaryDocViolations =
		checkAgentWorkflowMetadataProjectionBoundaryDoc();

	const result = {
		is_cloud_task: isCloudTask,
		changed_files: changedFiles,
		violations: {
			missing_contract_fields: [],
			invalid_change_classification: [],
			missing_required_gates: [],
			human_review_required_missing: [],
			executable_seam_without_backstop: [],
			forbidden_active_surfaces: [],
			metadata_projection_hardcoding: metadataProjectionHardcodingViolations,
			metadata_projection_boundary_doc_missing: metadataProjectionBoundaryDocViolations,
		},
		notes: [],
	};

	if ( ! isCloudTask ) {
		result.notes.push( 'No cloud task indicators detected; checker skipped.' );
		return result;
	}

	if ( ! hasContract ) {
		result.violations.missing_contract_fields.push(
			'task_contract_required_for_cloud_changes'
		);
		result.notes.push(
			'Cloud-related changes were detected without a task contract; CI/PR should block this merge.'
		);
		return result;
	}

	const changeClassification = String(
		contract.change_classification || ''
	).trim().toLowerCase();
	const truthOwner = String( contract.truth_owner || '' ).trim();
	const finalWriteOwner = String( contract.final_write_owner || '' ).trim();
	const failClosedExpectation = String(
		contract.fail_closed_expectation || ''
	).trim();
	const humanReviewRequired = contract.human_review_required;

	if ( ! changeClassification ) {
		result.violations.missing_contract_fields.push( 'change_classification' );
	} else if ( ! validChangeClassification.has( changeClassification ) ) {
		result.violations.invalid_change_classification.push(
			`change_classification=${ changeClassification }`
		);
	}

	if ( ! truthOwner ) {
		result.violations.missing_contract_fields.push( 'truth_owner' );
	}

	if ( ! finalWriteOwner ) {
		result.violations.missing_contract_fields.push( 'final_write_owner' );
	}

	if ( ! failClosedExpectation ) {
		result.violations.missing_contract_fields.push( 'fail_closed_expectation' );
	}

	const touchedHighRiskFieldTokens = orderedUniq(
		functionalChangedFileContents.flatMap( ( item ) =>
			manifest.highRiskFieldTokens.filter(
				( token ) => token && item.source.includes( token )
			).map( ( token ) => `${ item.file }:${ token }` )
		)
	);
	const touchesHighRisk = changedFiles.some( ( file ) =>
		manifest.highRiskPatterns.some( ( pattern ) => matchesPattern( file, pattern ) )
	) || touchedHighRiskFieldTokens.length > 0;

	if ( touchedHighRiskFieldTokens.length > 0 ) {
		result.notes.push(
			`High-risk cloud fields touched: ${ touchedHighRiskFieldTokens.join( ', ' ) }`
		);
	}

	const forbiddenActiveFiles = changedFiles.filter( ( file ) =>
		manifest.forbiddenActivePatterns.some( ( pattern ) => matchesPattern( file, pattern ) ) &&
		exists( path.resolve( workspaceRoot, file ) )
	);
	if ( forbiddenActiveFiles.length > 0 ) {
		result.violations.forbidden_active_surfaces.push(
			`active forbidden cloud surfaces present: ${ forbiddenActiveFiles.join( ', ' ) }`
		);
	}

	const metadataProjectionTokens = loadAgentWorkflowMetadataProjectionTokens();
	const hardcodedMetadataProjection = orderedUniq(
		functionalChangedFileContents.flatMap( ( item ) => {
			if ( ! isAdminPortalFrontendSource( item.file ) ) {
				return [];
			}
			return metadataProjectionTokens.filter(
				( token ) => token && item.source.includes( token )
			).map( ( token ) => `${ item.file }:${ token }` );
		} )
	);
	if ( hardcodedMetadataProjection.length > 0 ) {
		result.violations.metadata_projection_hardcoding.push(
			`Admin/Portal source hardcodes Agent/Workflow metadata projection; use the backend metadata projection instead: ${ hardcodedMetadataProjection.join( ', ' ) }`
		);
	}

	if ( touchesHighRisk && humanReviewRequired !== true ) {
		result.violations.human_review_required_missing.push(
			'high-risk cloud surface touched but human_review_required is not true'
		);
	}

	const touchesExecutableSeam = changedFiles.some( ( file ) =>
		manifest.executableSeamPatterns.some( ( pattern ) =>
			matchesPattern( file, pattern )
		)
	);
	const hasExecutableSeamBackstop = changedFiles.some( ( file ) =>
		manifest.executableSeamBackstopPatterns.some( ( pattern ) =>
			matchesPattern( file, pattern )
		)
	);

	if ( touchesExecutableSeam && ! hasExecutableSeamBackstop ) {
		result.violations.executable_seam_without_backstop.push(
			'changed executable cloud seam without touching cloud contract tests, cloud pytest, or hosted smoke'
		);
	}

	if (
		touchesExecutableSeam &&
		! contractRequiredGates.includes( 'pnpm run smoke:local-alpha' )
	) {
		result.violations.missing_required_gates.push(
			'pnpm run smoke:local-alpha'
		);
	}

	if (
		touchesExecutableSeam &&
		! contractRequiredGates.includes( 'pnpm run check:risk' ) &&
		! contractRequiredGates.includes( 'pnpm run check:founder:heavy' )
	) {
		result.violations.missing_required_gates.push(
			'pnpm run check:risk'
		);
	}

	return result;
}

if ( require.main === module ) {
	const { contractPath, wantsJson, files } = parseArgs( process.argv.slice( 2 ) );

	const result = checkCloudAntiDrift( { contractPath, files } );
	const hasViolations =
		result.violations.missing_contract_fields.length > 0 ||
		result.violations.invalid_change_classification.length > 0 ||
		result.violations.missing_required_gates.length > 0 ||
		result.violations.human_review_required_missing.length > 0 ||
		result.violations.executable_seam_without_backstop.length > 0 ||
		result.violations.forbidden_active_surfaces.length > 0 ||
		result.violations.metadata_projection_hardcoding.length > 0 ||
		result.violations.metadata_projection_boundary_doc_missing.length > 0;

	if ( wantsJson ) {
		console.log( JSON.stringify( result, null, 2 ) );
		process.exit( hasViolations ? 1 : 0 );
	}

	console.log(
		`[cloud-anti-drift] cloud_task=${ result.is_cloud_task ? 'yes' : 'no' }`
	);

	if ( ! result.is_cloud_task && ! hasViolations ) {
		console.log( '[ok] cloud anti-drift skipped: no cloud task indicators detected.' );
		process.exit( 0 );
	}

	if ( result.notes.length > 0 ) {
		result.notes.forEach( ( note ) => console.log( `- ${ note }` ) );
	}

	Object.entries( result.violations ).forEach( ( [ key, items ] ) => {
		if ( ! items.length ) {
			return;
		}
		console.error( `\n${ key }` );
		items.forEach( ( item ) => console.error( `- ${ item }` ) );
	} );

	if ( hasViolations ) {
		process.exit( 1 );
	}

	console.log( '[ok] cloud anti-drift passed.' );
	process.exit( 0 );
}

module.exports = {
	checkCloudAntiDrift,
};
