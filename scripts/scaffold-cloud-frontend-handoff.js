#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require( 'fs' );
const path = require( 'path' );
const cloudRoot = path.resolve( __dirname, '..' );
const workspaceRoot = path.resolve( cloudRoot, '..' );
function parseArgs( args ) { const parsed = { taskId: '', scope: 'ui-plus-tests', owner: 'frontend-ai', outputPath: '' }; for ( let i = 0; i < args.length; i += 1 ) { const v = String( args[ i ] || '' ).trim(); if ( v === '--' ) { continue; } if ( v === '--task-id' ) { parsed.taskId = String( args[ i + 1 ] || '' ).trim(); i += 1; continue; } if ( v === '--scope' ) { parsed.scope = String( args[ i + 1 ] || '' ).trim() || parsed.scope; i += 1; continue; } if ( v === '--owner' ) { parsed.owner = String( args[ i + 1 ] || '' ).trim() || parsed.owner; i += 1; continue; } if ( v === '--write' ) { parsed.outputPath = String( args[ i + 1 ] || '' ).trim(); i += 1; } } return parsed; }
function toOutputPath( taskId, outputPath ) { if ( outputPath ) { if ( path.isAbsolute( outputPath ) ) { return outputPath; } if ( outputPath.startsWith( 'scripts/' ) || outputPath.startsWith( 'frontend/' ) || outputPath.startsWith( 'app/' ) ) { return path.resolve( workspaceRoot, outputPath ); } return path.resolve( cloudRoot, outputPath ); } return path.resolve( cloudRoot, '.ai-cache', 'frontend-handoffs', `${ taskId }.md` ); }
function render( taskId, scope, owner ) {
	const payload = {
		task_id: taskId,
		owner,
		module: 'cloud-frontend',
		scope,
		allowed_files: [
			'frontend/src/app/(marketing)/page.tsx',
			'frontend/src/components/ui/Navbar.tsx',
			'frontend/src/app/globals.css',
		],
		forbidden_files: [
			'app/**',
			'deploy/**',
			'frontend/src/app/api/**',
			'frontend/src/lib/**',
			'frontend/src/proxy.ts',
			'frontend/next.config.mjs',
			'frontend/package.json',
			'frontend/.env.example',
		],
		required_docs: [
			'frontend/README.md',
			'frontend/DEVELOPMENT.md',
		],
		required_gates: [
			'pnpm run frontend:type-check',
			'pnpm run frontend:lint',
			'pnpm run check:frontend-scope -- --handoff <handoff.md> frontend/src/app/(marketing)/page.tsx frontend/src/components/ui/Navbar.tsx frontend/src/app/globals.css',
		],
		backend_followup_needed: 'no',
		backend_touchpoints: [],
		deliverables: [ 'UI-only patch inside allowed files', 'Recorded gate results and backend follow-up items' ],
	};
	return [ '# Cloud Frontend Handoff', '', '> Status: draft', '> 用途：冻结 `frontend` 前端 AI 的 UI-only 任务边界。', '', '## Machine-Readable Handoff', '', '```json', JSON.stringify( payload, null, 2 ), '```', '' ].join( '\n' );
}
const { taskId, scope, owner, outputPath } = parseArgs( process.argv.slice( 2 ) );
if ( ! taskId ) { console.error( '[error] scaffold cloud frontend handoff failed: missing --task-id <task-id>.' ); process.exit( 1 ); }
const content = `${ render( taskId, scope, owner ) }\n`;
if ( ! outputPath ) { console.log( content ); process.exit( 0 ); }
const absoluteOutputPath = toOutputPath( taskId, outputPath );
fs.mkdirSync( path.dirname( absoluteOutputPath ), { recursive: true } );
fs.writeFileSync( absoluteOutputPath, content, 'utf8' );
const relative = path.relative( workspaceRoot, absoluteOutputPath );
console.log( `Cloud frontend handoff written to ${ relative && ! relative.startsWith( '..' ) ? relative : absoluteOutputPath }` );
