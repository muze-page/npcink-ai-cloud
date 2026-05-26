#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require( 'fs' );
const path = require( 'path' );
const cloudRoot = path.resolve( __dirname, '..' );
const workspaceRoot = cloudRoot;
const lanePatterns = [
	'frontend/src/app/(marketing)/**',
	'frontend/src/app/portal/**',
	'frontend/src/components/**',
	'frontend/src/contexts/**',
	'frontend/src/hooks/useTheme.ts',
	'frontend/src/hooks/useTranslation.ts',
	'frontend/src/app/globals.css',
];
function readText( f ) { return fs.readFileSync( f, 'utf8' ); }
function exists( f ) { return fs.existsSync( f ); }
function orderedUniq( v ) { return Array.from( new Set( v.filter( Boolean ) ) ); }
function normalizePath( value ) { return String( value || '' ).replace( /\\/gu, '/' ).replace( /\/+/gu, '/' ); }
function listChangedFiles( root ) { const { execFileSync } = require( 'child_process' ); const out = [ [ 'diff', '--name-only', '--cached', '--diff-filter=ACMR' ], [ 'diff', '--name-only', '--diff-filter=ACMR' ], [ 'ls-files', '--others', '--exclude-standard' ] ].flatMap( ( args ) => execFileSync( 'git', args, { cwd: root, encoding: 'utf8' } ).split( /\r?\n/u ) ); return orderedUniq( out.map( ( v ) => normalizePath( v.trim() ) ) ); }
function toWorkspaceValue( value ) { let n = normalizePath( value || '' ); if ( ! n ) { return ''; } if ( path.isAbsolute( n ) ) { const r = path.relative( workspaceRoot, n ); if ( r && ! r.startsWith( '..' ) ) { n = normalizePath( r ); } } return n.replace( /^(\.\.\/)+/u, '' ); }
function globToRegExp( p ) { const e = p.replace( /[.+^${}()|[\]\\]/gu, '\\$&' ).replace( /\*\*/gu, '::double-star::' ).replace( /\*/gu, '[^/]*' ).replace( /::double-star::/gu, '.*' ); return new RegExp( `^${ e }$`, 'u' ); }
function matchesPattern( v, p ) { return globToRegExp( p ).test( v ); }
function parseArtifactFile( filePath ) { const s = readText( filePath ); if ( filePath.endsWith( '.json' ) ) { return JSON.parse( s ); } try { return JSON.parse( s ); } catch ( error ) {} const m = s.match( /```json\s*([\s\S]*?)```/u ); if ( ! m ) { throw new Error( 'frontend handoff must be JSON or contain a fenced ```json block.' ); } return JSON.parse( String( m[ 1 ] || '' ).trim() ); }
function parseArgs( args ) { let handoffPath = ''; let wantsJson = false; const files = []; for ( let i = 0; i < args.length; i += 1 ) { const v = args[ i ]; if ( v === '--' ) { continue; } if ( v === '--json' ) { wantsJson = true; continue; } if ( v === '--handoff' ) { handoffPath = String( args[ i + 1 ] || '' ).trim(); i += 1; continue; } files.push( v ); } return { handoffPath, wantsJson, files }; }
function printSection( t, i ) { if ( ! i.length ) { return; } console.log( `\n${ t }` ); i.forEach( ( item ) => console.log( `- ${ item }` ) ); }
const { handoffPath, wantsJson, files: explicitFiles } = parseArgs( process.argv.slice( 2 ) );
if ( ! handoffPath ) { console.error( '[error] cloud frontend scope failed: missing --handoff <path-to-json-or-markdown>.' ); process.exit( 1 ); }
const absoluteHandoffPath = path.isAbsolute( handoffPath ) ? handoffPath : path.resolve( workspaceRoot, handoffPath );
if ( ! exists( absoluteHandoffPath ) ) { console.error( `[error] cloud frontend scope failed: handoff file not found: ${ absoluteHandoffPath }` ); process.exit( 1 ); }
const handoff = parseArtifactFile( absoluteHandoffPath );
const allowedPatterns = orderedUniq( ( Array.isArray( handoff.allowed_files ) ? handoff.allowed_files : [] ).map( toWorkspaceValue ) );
const forbiddenPatterns = orderedUniq( ( Array.isArray( handoff.forbidden_files ) ? handoff.forbidden_files : [] ).map( toWorkspaceValue ) );
const changedFiles = orderedUniq( ( explicitFiles.length > 0 ? explicitFiles : listChangedFiles( workspaceRoot ) ).map( toWorkspaceValue ) );
const errors = [];
if ( String( handoff.module || '' ).trim() !== 'cloud-frontend' ) { errors.push( 'handoff module must be `cloud-frontend`.' ); }
const forbiddenMatches = [];
const outOfScopeFiles = [];
const laneViolations = [];
changedFiles.forEach( ( file ) => {
	if ( forbiddenPatterns.some( ( pattern ) => matchesPattern( file, pattern ) ) ) { forbiddenMatches.push( file ); }
	if ( ! allowedPatterns.some( ( pattern ) => matchesPattern( file, pattern ) ) ) { outOfScopeFiles.push( file ); }
	if ( ! lanePatterns.some( ( pattern ) => matchesPattern( file, pattern ) ) ) { laneViolations.push( file ); }
} );
const result = { changed_files: changedFiles, allowed_files: allowedPatterns, forbidden_files: forbiddenPatterns, violations: { handoff_errors: errors, forbidden_matches: forbiddenMatches, out_of_scope_files: outOfScopeFiles, frontend_lane_violations: laneViolations } };
if ( wantsJson ) { console.log( JSON.stringify( result, null, 2 ) ); process.exit( errors.length > 0 || forbiddenMatches.length > 0 || outOfScopeFiles.length > 0 || laneViolations.length > 0 ? 1 : 0 ); }
printSection( 'Changed files', changedFiles ); printSection( 'Allowed files', allowedPatterns ); printSection( 'Forbidden files', forbiddenPatterns );
if ( errors.length > 0 ) { printSection( 'Errors', errors ); }
if ( forbiddenMatches.length > 0 ) { printSection( 'Forbidden matches', forbiddenMatches ); }
if ( outOfScopeFiles.length > 0 ) { printSection( 'Out-of-scope changed files', outOfScopeFiles ); }
if ( laneViolations.length > 0 ) { printSection( 'Frontend lane violations', laneViolations ); }
if ( changedFiles.length === 0 ) { console.log( '\n[ok] cloud frontend scope: no changed files detected.' ); process.exit( 0 ); }
if ( errors.length === 0 && forbiddenMatches.length === 0 && outOfScopeFiles.length === 0 && laneViolations.length === 0 ) { console.log( `\n[ok] cloud frontend scope passed: ${ changedFiles.length } changed file(s) stayed within the handoff lane.` ); process.exit( 0 ); }
console.error( '\n[error] cloud frontend scope failed: shrink the diff or return backend seam changes to Codex.' );
process.exit( 1 );
