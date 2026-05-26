#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'fs' );
const path = require( 'path' );

const cloudRoot = path.resolve( __dirname, '..' );
const defaultOutputRoot = path.join(
	cloudRoot,
	'examples',
	'cloud-portal-route-templates',
	'generated'
);
const validModes = new Set( [ 'read', 'write' ] );

/**
 * @param {string[]} argv
 * @return {{
 *   routeId:string,
 *   outputDir:string,
 *   mode:string,
 *   force:boolean
 * }}
 */
function parseArgs( argv ) {
	const options = {
		routeId: '',
		outputDir: '',
		mode: 'read',
		force: false,
	};

	for ( let index = 0; index < argv.length; index += 1 ) {
		const arg = argv[ index ];

		if ( arg === '--' ) {
			continue;
		}
		if ( arg === '--force' ) {
			options.force = true;
			continue;
		}
		if ( arg === '--route-id' ) {
			options.routeId = argv[ index + 1 ] || '';
			index += 1;
			continue;
		}
		if ( arg.startsWith( '--route-id=' ) ) {
			options.routeId = arg.slice( '--route-id='.length );
			continue;
		}
		if ( arg === '--output-dir' ) {
			options.outputDir = argv[ index + 1 ] || '';
			index += 1;
			continue;
		}
		if ( arg.startsWith( '--output-dir=' ) ) {
			options.outputDir = arg.slice( '--output-dir='.length );
			continue;
		}
		if ( arg === '--mode' ) {
			options.mode = argv[ index + 1 ] || '';
			index += 1;
			continue;
		}
		if ( arg.startsWith( '--mode=' ) ) {
			options.mode = arg.slice( '--mode='.length );
			continue;
		}
		if ( arg === '--help' || arg === '-h' ) {
			printHelp();
			process.exit( 0 );
		}
	}

	return options;
}

/**
 * @return {void}
 */
function printHelp() {
	console.log( 'Scaffold one Cloud portal route pack (route module + API test + mount snippet).' );
	console.log( '' );
	console.log(
		'Usage: node scripts/scaffold-cloud-portal-route.js --route-id=<route_id> [--mode=read|write] [--output-dir=<path>] [--force]'
	);
}

/**
 * @param {string} message
 * @return {never}
 */
function fail( message ) {
	console.error( `Error: ${ message }` );
	process.exit( 1 );
}

/**
 * @param {string} value
 * @return {string}
 */
function normalizeRouteId( value ) {
	return String( value || '' )
		.trim()
		.toLowerCase()
		.replace( /[^a-z0-9/_-]+/gu, '-' )
		.replace( /-+/gu, '-' )
		.replace( /\/+/gu, '/' )
		.replace( /^[-/]+|[-/]+$/gu, '' );
}

/**
 * @param {string} routeId
 * @return {boolean}
 */
function isValidRouteId( routeId ) {
	return /^[a-z0-9][a-z0-9/_-]{1,127}$/u.test( routeId );
}

/**
 * @param {string} routeId
 * @param {'read'|'write'} mode
 * @return {{
 *   routeSlug:string,
 *   moduleName:string,
 *   functionBase:string,
 *   classBase:string,
 *   label:string,
 *   prefix:string,
 *   endpointPath:string
 * }}
 */
function deriveTokens( routeId, mode ) {
	const routeSlug = routeId
		.split( '/' )
		.map( ( part ) => part.replace( /_/gu, '-' ) )
		.join( '/' );
	const moduleName = routeId.replace( /[\/-]+/gu, '_' );
	const functionBase = moduleName;
	const label = routeSlug
		.split( /[\/_-]+/u )
		.filter( Boolean )
		.map( ( part ) => part.charAt( 0 ).toUpperCase() + part.slice( 1 ) )
		.join( ' ' );
	const classBase = label.replace( /[^A-Za-z0-9]+/gu, '' ) || 'PortalRoute';

	return {
		routeSlug,
		moduleName,
		functionBase,
		classBase,
		label: label || 'Portal Route',
		prefix: `/portal/v1/${ routeSlug }`,
		endpointPath: mode === 'read' ? '/summary' : '/action',
	};
}

/**
 * @param {string} filePath
 * @param {string} content
 * @param {boolean} force
 * @return {void}
 */
function writeFile( filePath, content, force ) {
	if ( fs.existsSync( filePath ) && ! force ) {
		fail( `file exists: ${ filePath } (pass --force to overwrite)` );
	}

	fs.mkdirSync( path.dirname( filePath ), { recursive: true } );
	fs.writeFileSync( filePath, content, 'utf8' );
}

const options = parseArgs( process.argv.slice( 2 ) );
const routeId = normalizeRouteId( options.routeId );
const mode = String( options.mode || 'read' ).trim().toLowerCase();

if ( ! routeId ) {
	fail( '--route-id is required.' );
}
if ( ! isValidRouteId( routeId ) ) {
	fail( '--route-id must match [a-z0-9][a-z0-9/_-]{1,127}.' );
}
if ( ! validModes.has( mode ) ) {
	fail( '--mode must be read or write.' );
}

const tokens = deriveTokens( routeId, mode );
const outputDir = options.outputDir
	? path.resolve( cloudRoot, options.outputDir )
	: path.join( defaultOutputRoot, tokens.routeSlug.replace( /\//gu, '-' ) );
const routePath = path.join(
	outputDir,
	'cloud',
	'app',
	'api',
	'routes',
	`${ tokens.moduleName }.py`
);
const apiTestPath = path.join(
	outputDir,
	'cloud',
	'tests',
	'api',
	`test_${ tokens.moduleName }_portal_routes.py`
);
const mountSnippetPath = path.join( outputDir, 'cloud', 'mount-snippet.py' );
const readmePath = path.join( outputDir, 'README.md' );

const routeContent = mode === 'read'
	? `from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.envelope import build_envelope
from app.api.portal_session import resolve_portal_request_context

router = APIRouter(prefix="${ tokens.prefix }", tags=["portal"])


def _portal_envelope(*, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return build_envelope(
        status="ok",
        message=message,
        data=data,
        revision="scaffold",
    )


@router.get("${ tokens.endpointPath }")
async def get_${ tokens.functionBase }_summary(request: Request) -> Any:
    auth = await resolve_portal_request_context(
        request,
        require_idempotency=False,
        allow_preview_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth

    return _portal_envelope(
        message="${ tokens.routeSlug } summary loaded",
        data={
            "member_ref": auth.member_ref,
            "route": "${ tokens.prefix }${ tokens.endpointPath }",
            "mode": "${ mode }",
        },
    )
`
	: `from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.envelope import build_envelope
from app.api.portal_session import portal_json_error, resolve_portal_request_context

router = APIRouter(prefix="${ tokens.prefix }", tags=["portal"])


class ${ tokens.classBase }ActionPayload(BaseModel):
    site_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def _portal_envelope(*, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return build_envelope(
        status="ok",
        message=message,
        data=data,
        revision="scaffold",
    )


@router.post("${ tokens.endpointPath }")
async def post_${ tokens.functionBase }_action(
    request: Request,
    payload: ${ tokens.classBase }ActionPayload,
) -> Any:
    if not payload.site_id.strip():
        return portal_json_error(
            request,
            status_code=400,
            error_code="portal.site_invalid",
            message="site id is required",
        )

    auth = await resolve_portal_request_context(
        request,
        require_idempotency=True,
        allow_preview_cookies=True,
    )
    if isinstance(auth, JSONResponse):
        return auth

    return _portal_envelope(
        message="${ tokens.routeSlug } action accepted",
        data={
            "member_ref": auth.member_ref,
            "site_id": payload.site_id.strip(),
            "route": "${ tokens.prefix }${ tokens.endpointPath }",
            "mode": "${ mode }",
            "metadata_keys": sorted(payload.metadata.keys()),
        },
    )
`;

const apiTestContent = mode === 'read'
	? `from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.services import CloudServices
from tests.conftest import TEST_PORTAL_AUTH_TOKEN, build_portal_bearer_headers, build_portal_headers


def _build_client(*, jwt_secret: str = "") -> TestClient:
    settings_kwargs = {
        "project_name": "Magick AI Cloud Test",
        "environment": "test",
        "database_url": "sqlite+pysqlite:///:memory:",
        "redis_url": "redis://localhost:6379/0",
        "portal_auth_token": TEST_PORTAL_AUTH_TOKEN,
    }
    if jwt_secret:
        settings_kwargs["portal_jwt_secret"] = jwt_secret
        settings_kwargs["portal_auth_token"] = ""

    return TestClient(create_app(CloudServices(settings=Settings(**settings_kwargs))))


def test_${ tokens.functionBase }_summary_accepts_portal_header_auth() -> None:
    client = _build_client()

    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_portal_headers(trace_id="${ tokens.functionBase }000100000000000000000000"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["route"] == "${ tokens.prefix }${ tokens.endpointPath }"


def test_${ tokens.functionBase }_summary_accepts_portal_bearer_auth() -> None:
    client = _build_client(jwt_secret="portal-scaffold-secret")

    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_portal_bearer_headers(
            secret="portal-scaffold-secret",
            trace_id="${ tokens.functionBase }000200000000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["member_ref"] == "user:portal-admin@example.com"


def test_${ tokens.functionBase }_summary_fails_closed_without_portal_auth() -> None:
    client = _build_client()

    response = client.get("${ tokens.prefix }${ tokens.endpointPath }")

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.portal_token_required"
`
	: `from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.services import CloudServices
from tests.conftest import TEST_PORTAL_AUTH_TOKEN, build_portal_headers


def _build_client() -> TestClient:
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        portal_auth_token=TEST_PORTAL_AUTH_TOKEN,
    )
    return TestClient(create_app(CloudServices(settings=settings)))


def test_${ tokens.functionBase }_action_accepts_portal_header_auth() -> None:
    client = _build_client()

    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        json={
            "site_id": "site_portal_scaffold",
            "metadata": {"source": "scaffold"},
        },
        headers=build_portal_headers(
            idempotency_key="${ tokens.functionBase }-001",
            trace_id="${ tokens.functionBase }000300000000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["site_id"] == "site_portal_scaffold"


def test_${ tokens.functionBase }_action_requires_site_id() -> None:
    client = _build_client()

    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        json={"site_id": ""},
        headers=build_portal_headers(
            idempotency_key="${ tokens.functionBase }-002",
            trace_id="${ tokens.functionBase }000400000000000000000000",
        ),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "portal.site_invalid"
`;

const mountSnippetContent = `from app.api.routes.${ tokens.moduleName } import router as ${ tokens.moduleName }_router

# In app/api/main.py
app.include_router(${ tokens.moduleName }_router)
`;

const readmeContent = `# ${ tokens.label } Portal Route Scaffold

Generated by \`pnpm run scaffold:cloud:portal-route -- --route-id=${ routeId } --mode=${ mode }\`.

## Files

- \`app/api/routes/${ tokens.moduleName }.py\`
- \`tests/api/test_${ tokens.moduleName }_portal_routes.py\`
- \`mount-snippet.py\`

## Promote Into Product Truth

1. Move the route module into \`app/api/routes/\`.
2. Wire the import + \`app.include_router(...)\` snippet into \`app/api/main.py\`.
3. Promote the API test into \`tests/api/\` or merge it into \`test_portal_routes.py\` if you are extending the existing portal family.
4. Replace scaffold payload fields with the real member/site/session contract and write back any stable response drift to the relevant Cloud portal contract docs.

## Verify

- \`pnpm run test:api\`
- \`pnpm run check:perimeter\`
`;

writeFile( routePath, routeContent, options.force );
writeFile( apiTestPath, apiTestContent, options.force );
writeFile( mountSnippetPath, mountSnippetContent, options.force );
writeFile( readmePath, readmeContent, options.force );

console.log( `[scaffold-cloud-portal-route] output=${ outputDir }` );
console.log( `- route=${ routePath }` );
console.log( `- api_test=${ apiTestPath }` );
console.log( `- mount_snippet=${ mountSnippetPath }` );
console.log( `- readme=${ readmePath }` );
