#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'fs' );
const path = require( 'path' );

const cloudRoot = path.resolve( __dirname, '..' );
const docPath = path.join(
	cloudRoot,
	'docs',
	'runtime-stability-performance-evidence-v1.md'
);

const requiredPhrases = [
	'This document does not approve a rewrite.',
	'keep the current FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic, worker, and',
	'This work belongs to Cloud runtime and operator evidence only.',
	'moving WordPress approval, preflight, audit, or final writes into Cloud',
	'adding a Cloud ability registry, workflow registry, prompt editor, router',
	'introducing Temporal, Cadence, Airflow, Dagster, Celery, RabbitMQ, Kafka,',
	'treating Redis, queues, callbacks, buffers, or projection data as canonical',
	'implementing a Go or Rust sidecar before this evidence stage produces a',
	'pnpm run perf:runtime-hot-path:require-indexes',
	'worker heartbeat freshness for `runtime_queue`, `callback_dispatch`, and',
	'provider latency p50, p95, p99, error rate, and timeout rate',
	'PostgreSQL indexes and query shape for runtime hot paths',
	'Do not add new infrastructure while tuning.',
	'The detail surface must remain read-only',
	'`keep_current_stack`',
	'`tune_current_stack_next`',
	'`sidecar_candidate`',
	'a named module has repeated measured bottlenecks after current-stack tuning',
	'the bottleneck is CPU-bound or memory-bound',
	'FastAPI remains the public runtime API owner',
	'the sidecar owns no WordPress write, approval, proposal, prompt, router,',
	'rollback is a config or routing rollback to the existing Python path',
	'whole repository rewrite',
	'pnpm run check:runtime-stability-plan',
	'/Users/muze/gitee/npcink-workflow-toolbox',
	'composer quality:matrix',
];

const forbiddenApprovalPatterns = [
	/\bapprove(?:s|d)?\s+(?:a\s+)?(?:go|rust)\s+(?:rewrite|sidecar)/iu,
	/\brewrite\s+the\s+(?:api|worker|repository|backend)\b/iu,
	/\bintroduce\s+(?:Temporal|Celery|RabbitMQ|Kafka|NATS|Pulsar)\b/iu,
];

function readText( filePath ) {
	return fs.readFileSync( filePath, 'utf8' );
}

function main() {
	if ( ! fs.existsSync( docPath ) ) {
		console.error( `[error] missing required plan doc: ${ docPath }` );
		return 1;
	}

	const source = readText( docPath );
	const missing = requiredPhrases.filter( ( phrase ) => ! source.includes( phrase ) );
	const forbidden = forbiddenApprovalPatterns
		.map( ( pattern ) => pattern.exec( source ) )
		.filter( Boolean )
		.map( ( match ) => String( match[ 0 ] || '' ) );

	if ( missing.length > 0 || forbidden.length > 0 ) {
		if ( missing.length > 0 ) {
			console.error( '[error] runtime stability plan is missing required boundary phrases:' );
			for ( const phrase of missing ) {
				console.error( `- ${ phrase }` );
			}
		}

		if ( forbidden.length > 0 ) {
			console.error( '[error] runtime stability plan contains forbidden approval wording:' );
			for ( const phrase of forbidden ) {
				console.error( `- ${ phrase }` );
			}
		}

		return 1;
	}

	console.log( 'runtime_stability_evidence_plan: ok' );
	return 0;
}

process.exitCode = main();
