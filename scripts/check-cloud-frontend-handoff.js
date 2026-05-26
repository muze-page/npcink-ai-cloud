#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require( 'fs' );
const path = require( 'path' );
const cloudRoot = path.resolve( __dirname, '..' );
const workspaceRoot = cloudRoot;
const requiredDocs = [
	'frontend/README.md',
	'frontend/DEVELOPMENT.md',
];
const requiredForbiddenPatterns = [
	'app/**',
	'deploy/**',
	'frontend/src/app/api/**',
	'frontend/src/lib/**',
	'frontend/src/proxy.ts',
	'frontend/next.config.mjs',
	'frontend/package.json',
	'frontend/.env.example',
];
function readText( f ) { return fs.readFileSync( f, 'utf8' ); }
function exists( f ) { return fs.existsSync( f ); }
function orderedUniq( v ) { return Array.from( new Set( v.filter( Boolean ) ) ); }
function normalizePath( value ) { return String( value || '' ).replace( /\\/gu, '/' ).replace( /\/+/gu, '/' ); }
function globToRegExp( p ) { const e = p.replace( /[.+^${}()|[\]\\]/gu, '\\$&' ).replace( /\*\*/gu, '::double-star::' ).replace( /\*/gu, '[^/]*' ).replace( /::double-star::/gu, '.*' ); return new RegExp( `^${ e }$`, 'u' ); }
function matchesPattern( v, p ) { return globToRegExp( p ).test( v ); }
function toWorkspaceValue( value ) { let n = normalizePath( value || '' ); if ( ! n ) { return ''; } if ( path.isAbsolute( n ) ) { const r = path.relative( workspaceRoot, n ); if ( r && ! r.startsWith( '..' ) ) { n = normalizePath( r ); } } return n.replace( /^(\.\.\/)+/u, '' ); }
function parseArtifactFile( filePath ) { const s = readText( filePath ); if ( filePath.endsWith( '.json' ) ) { return JSON.parse( s ); } try { return JSON.parse( s ); } catch ( error ) {} const m = s.match( /```json\s*([\s\S]*?)```/u ); if ( ! m ) { throw new Error( 'handoff must be JSON or contain a fenced ```json block.' ); } return JSON.parse( String( m[ 1 ] || '' ).trim() ); }
function parseArgs( args ) { let handoffPath = ''; let wantsJson = false; for ( let i = 0; i < args.length; i += 1 ) { const v = args[ i ]; if ( v === '--' ) { continue; } if ( v === '--json' ) { wantsJson = true; continue; } if ( v === '--handoff' ) { handoffPath = String( args[ i + 1 ] || '' ).trim(); i += 1; } } return { handoffPath, wantsJson }; }
function printSection( t, i ) { if ( ! i.length ) { return; } console.log( `\n${ t }` ); i.forEach( ( item ) => console.log( `- ${ item }` ) ); }
const { handoffPath, wantsJson } = parseArgs( process.argv.slice( 2 ) );
if ( ! handoffPath ) { console.error( '[error] cloud frontend handoff check failed: missing --handoff <path-to-json-or-markdown>.' ); process.exit( 1 ); }
const absoluteHandoffPath = path.isAbsolute( handoffPath ) ? handoffPath : path.resolve( workspaceRoot, handoffPath );
if ( ! exists( absoluteHandoffPath ) ) { console.error( `[error] cloud frontend handoff check failed: handoff file not found: ${ absoluteHandoffPath }` ); process.exit( 1 ); }
const artifact = parseArtifactFile( absoluteHandoffPath );
const errors = [];
const allowedFiles = orderedUniq( ( Array.isArray( artifact.allowed_files ) ? artifact.allowed_files : [] ).map( toWorkspaceValue ) );
const forbiddenFiles = orderedUniq( ( Array.isArray( artifact.forbidden_files ) ? artifact.forbidden_files : [] ).map( toWorkspaceValue ) );
const requiredDocsList = orderedUniq( ( Array.isArray( artifact.required_docs ) ? artifact.required_docs : [] ).map( toWorkspaceValue ) );
const requiredGates = orderedUniq( ( Array.isArray( artifact.required_gates ) ? artifact.required_gates : [] ).map( ( v ) => String( v || '' ).trim() ).filter( Boolean ) );
if ( String( artifact.module || '' ).trim() !== 'cloud-frontend' ) { errors.push( 'module must be `cloud-frontend`.' ); }
requiredDocs.forEach( ( value ) => { if ( ! requiredDocsList.includes( value ) ) { errors.push( `required_docs must include: ${ value }` ); } } );
requiredForbiddenPatterns.forEach( ( value ) => { if ( ! forbiddenFiles.includes( value ) ) { errors.push( `forbidden_files must include: ${ value }` ); } } );
if ( ! requiredGates.includes( 'pnpm run frontend:type-check' ) ) { errors.push( 'required_gates must include `pnpm run frontend:type-check`.' ); }
if ( ! requiredGates.includes( 'pnpm run frontend:lint' ) ) { errors.push( 'required_gates must include `pnpm run frontend:lint`.' ); }
if ( ! requiredGates.some( ( command ) => command.startsWith( 'pnpm run check:frontend-scope -- ' ) ) ) { errors.push( 'required_gates must include `pnpm run check:frontend-scope -- --handoff <handoff.md> <changed-files...>`.' ); }
const result = { handoff: toWorkspaceValue( path.relative( workspaceRoot, absoluteHandoffPath ) ), allowed_files: allowedFiles, required_gates: requiredGates, errors };
if ( wantsJson ) { console.log( JSON.stringify( result, null, 2 ) ); process.exit( errors.length > 0 ? 1 : 0 ); }
printSection( 'Allowed files', allowedFiles ); printSection( 'Required gates', requiredGates );
if ( errors.length > 0 ) { printSection( 'Errors', errors ); console.error( '\n[error] cloud frontend handoff failed: tighten the UI-only scope or return the task to Codex.' ); process.exit( 1 ); }
console.log( '\ncloud_frontend_handoff: ok' );
