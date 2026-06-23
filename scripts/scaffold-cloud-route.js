#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require( 'fs' );
const path = require( 'path' );

const cloudRoot = path.resolve( __dirname, '..' );
const defaultOutputRoot = path.join(
	cloudRoot,
	'examples',
	'cloud-route-templates',
	'generated'
);
const validSurfaces = new Set( [ 'internal', 'public' ] );
const validModes = new Set( [ 'read', 'write' ] );

/**
 * @param {string[]} argv
 * @return {{
 *   routeId:string,
 *   outputDir:string,
 *   surface:string,
 *   mode:string,
 *   force:boolean
 * }}
 */
function parseArgs( argv ) {
	const options = {
		routeId: '',
		outputDir: '',
		surface: 'internal',
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
		if ( arg === '--surface' ) {
			options.surface = argv[ index + 1 ] || '';
			index += 1;
			continue;
		}
		if ( arg.startsWith( '--surface=' ) ) {
			options.surface = arg.slice( '--surface='.length );
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
	console.log( 'Scaffold one Cloud route pack (route module + api/contract tests + mount snippet).' );
	console.log( '' );
	console.log(
		'Usage: node scripts/scaffold-cloud-route.js --route-id=<route_id> [--surface=internal|public] [--mode=read|write] [--output-dir=<path>] [--force]'
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
 * @return {{
 *   routeSlug:string,
 *   tag:string,
 *   label:string,
 *   moduleName:string,
 *   functionBase:string,
 *   classBase:string,
 *   prefix:string,
 *   endpointPath:string,
 *   requiredScope:string
 * }}
 */
function deriveTokens( routeId, surface, mode ) {
	const routeSlug = routeId
		.split( '/' )
		.map( ( part ) => part.replace( /_/gu, '-' ) )
		.join( '/' );
	const tag = routeSlug.replace( /\//gu, '-' );
	const label = routeSlug
		.split( /[\/_-]+/u )
		.filter( Boolean )
		.map( ( part ) => part.charAt( 0 ).toUpperCase() + part.slice( 1 ) )
		.join( ' ' );
	const moduleName = routeId.replace( /[\/-]+/gu, '_' );
	const functionBase = moduleName;
	const classBase = label.replace( /[^A-Za-z0-9]+/gu, '' ) || 'CloudRoute';
	const basePrefix = surface === 'internal' ? '/internal' : '/v1';

	return {
		routeSlug,
		tag,
		label: label || 'Cloud Route',
		moduleName,
		functionBase,
		classBase,
		prefix: `${ basePrefix }/${ routeSlug }`,
		endpointPath: mode === 'read' ? '/status' : '/dispatch',
		requiredScope: `${ tag }:${ mode === 'read' ? 'read' : 'write' }`,
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
const surface = String( options.surface || 'internal' ).trim().toLowerCase();
const mode = String( options.mode || 'read' ).trim().toLowerCase();

if ( ! routeId ) {
	fail( '--route-id is required.' );
}
if ( ! isValidRouteId( routeId ) ) {
	fail( '--route-id must match [a-z0-9][a-z0-9/_-]{1,127}.' );
}
if ( ! validSurfaces.has( surface ) ) {
	fail( '--surface must be internal or public.' );
}
if ( ! validModes.has( mode ) ) {
	fail( '--mode must be read or write.' );
}

const tokens = deriveTokens( routeId, surface, mode );
const shouldGenerateContract = surface === 'public';
const outputDir = options.outputDir
	? path.resolve( cloudRoot, options.outputDir )
	: path.join( defaultOutputRoot, tokens.tag );
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
	`test_${ tokens.moduleName }_routes.py`
);
const contractTestPath = path.join(
	outputDir,
	'cloud',
	'tests',
	'contract',
	`test_${ tokens.moduleName }_contract.py`
);
const mountSnippetPath = path.join( outputDir, 'cloud', 'mount-snippet.py' );
const readmePath = path.join( outputDir, 'README.md' );

const routeContent = mode === 'read'
	? `from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth import ${ surface === 'internal' ? 'authorize_internal_request' : 'authorize_public_request' }
from app.api.envelope import build_envelope

router = APIRouter(prefix="${ tokens.prefix }", tags=["${ tokens.tag }"])

${ surface === 'public' ? `REQUIRED_SCOPE = "${ tokens.requiredScope }"\n` : '' }

@router.get("${ tokens.endpointPath }")
async def get_${ tokens.functionBase }_status(request: Request) -> Any:
${ surface === 'internal'
	? `    auth = await authorize_internal_request(
        request,
        require_idempotency=False,
    )
    if auth is not None:
        return auth`
	: `    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope=REQUIRED_SCOPE,
    )
    if isinstance(auth, JSONResponse):
        return auth` }

    return build_envelope(
        status="ok",
        message="${ tokens.tag } status loaded",
        data={
${ surface === 'public' ? '            "site_id": auth.site_id,\n' : '' }            "route": "${ tokens.prefix }${ tokens.endpointPath }",
            "surface": "${ surface }",
            "mode": "${ mode }",
        },
        revision="scaffold",
    )
`
	: `from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.auth import ${ surface === 'internal' ? 'authorize_internal_request' : 'authorize_public_request' }
from app.api.envelope import build_envelope

router = APIRouter(prefix="${ tokens.prefix }", tags=["${ tokens.tag }"])

${ surface === 'public' ? `REQUIRED_SCOPE = "${ tokens.requiredScope }"\n` : '' }


class ${ tokens.classBase }DispatchPayload(BaseModel):
    subject_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("${ tokens.endpointPath }")
async def dispatch_${ tokens.functionBase }(
    request: Request,
    payload: ${ tokens.classBase }DispatchPayload,
) -> Any:
${ surface === 'internal'
	? `    auth = await authorize_internal_request(
        request,
        require_idempotency=True,
    )
    if auth is not None:
        return auth`
	: `    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope=REQUIRED_SCOPE,
    )
    if isinstance(auth, JSONResponse):
        return auth` }

    return build_envelope(
        status="ok",
        message="${ tokens.tag } dispatch accepted",
        data={
${ surface === 'public' ? '            "site_id": auth.site_id,\n' : '' }            "route": "${ tokens.prefix }${ tokens.endpointPath }",
            "surface": "${ surface }",
            "mode": "${ mode }",
            "subject_id": payload.subject_id,
            "metadata_keys": sorted(payload.metadata.keys()),
        },
        revision="scaffold",
    )
`;

const apiTestContent = surface === 'internal'
	? mode === 'read'
		? `from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers


class StubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        )


def test_${ tokens.functionBase }_status_returns_ok_envelope() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="${ tokens.functionBase }000100000000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["route"] == "${ tokens.prefix }${ tokens.endpointPath }"


def test_${ tokens.functionBase }_status_requires_internal_token() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get("${ tokens.prefix }${ tokens.endpointPath }")

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.internal_token_required"
`
		: `from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers


class StubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        )


def test_${ tokens.functionBase }_dispatch_returns_ok_envelope() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        json={
            "subject_id": "${ tokens.tag }-001",
            "metadata": {"source": "scaffold"},
        },
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="${ tokens.functionBase }000200000000000000000000",
            idempotency_key="${ tokens.functionBase }-dispatch-001",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["subject_id"] == "${ tokens.tag }-001"


def test_${ tokens.functionBase }_dispatch_requires_internal_token() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        json={"subject_id": "${ tokens.tag }-001"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.internal_token_required"
`
	: mode === 'read'
		? `from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from tests.conftest import build_auth_headers, merge_json_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / '${ tokens.moduleName }-routes.sqlite3'}"


def test_${ tokens.functionBase }_status_returns_ok_envelope(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_${ tokens.moduleName }",
        scopes=["${ tokens.requiredScope }"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_auth_headers(
            "GET",
            "${ tokens.prefix }${ tokens.endpointPath }",
            site_id="site_${ tokens.moduleName }",
            trace_id="${ tokens.functionBase }000300000000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["site_id"] == "site_${ tokens.moduleName }"

    dispose_engine(database_url)
`
		: `from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from tests.conftest import build_auth_headers, merge_json_headers, seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / '${ tokens.moduleName }-routes.sqlite3'}"


def test_${ tokens.functionBase }_dispatch_returns_ok_envelope(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_${ tokens.moduleName }",
        scopes=["${ tokens.requiredScope }"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))

    request_payload = {
        "subject_id": "${ tokens.tag }-001",
        "metadata": {"source": "scaffold"},
    }
    body = json.dumps(request_payload).encode("utf-8")
    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "${ tokens.prefix }${ tokens.endpointPath }",
                site_id="site_${ tokens.moduleName }",
                trace_id="${ tokens.functionBase }000400000000000000000000",
                idempotency_key="${ tokens.functionBase }-dispatch-001",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["subject_id"] == "${ tokens.tag }-001"

    dispose_engine(database_url)
`;

const contractTestContent = mode === 'read'
	? `from __future__ import annotations

${ surface === 'public' ? 'from pathlib import Path\n\n' : '' }from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
${ surface === 'public' ? 'from app.core.db import dispose_engine, init_schema\n' : '' }from app.core.services import CloudServices${ surface === 'internal' ? '' : '\n' }${ surface === 'public' ? 'from tests.conftest import build_auth_headers, seed_site_auth\n' : 'from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers\n' }

${ surface === 'internal'
	? `class StubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        )
`
	: `def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / '${ tokens.moduleName }-contract.sqlite3'}"
` }


def test_${ tokens.functionBase }_contract_uses_standard_envelope(${ surface === 'public' ? 'tmp_path: Path' : '' }) -> None:
${ surface === 'internal'
	? `    client = TestClient(create_app(StubServices()))
    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="${ tokens.functionBase }000500000000000000000000",
        ),
    )`
	: `    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_${ tokens.moduleName }",
        scopes=["${ tokens.requiredScope }"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))
    response = client.get(
        "${ tokens.prefix }${ tokens.endpointPath }",
        headers=build_auth_headers(
            "GET",
            "${ tokens.prefix }${ tokens.endpointPath }",
            site_id="site_${ tokens.moduleName }",
            trace_id="${ tokens.functionBase }000500000000000000000000",
        ),
    )` }

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {"route", "surface", "mode"${ surface === 'public' ? ', "site_id"' : '' }}
${ surface === 'public' ? '\n    dispose_engine(database_url)' : '' }
`
	: `from __future__ import annotations

import json
${ surface === 'public' ? 'from pathlib import Path\n\n' : '\n' }from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
${ surface === 'public' ? 'from app.core.db import dispose_engine, init_schema\n' : '' }from app.core.services import CloudServices${ surface === 'internal' ? '' : '\n' }${ surface === 'public' ? 'from tests.conftest import build_auth_headers, merge_json_headers, seed_site_auth\n' : 'from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers\n' }

${ surface === 'internal'
	? `class StubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Npcink AI Cloud Test",
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        )
`
	: `def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / '${ tokens.moduleName }-contract.sqlite3'}"
` }


def test_${ tokens.functionBase }_dispatch_contract_uses_standard_envelope(${ surface === 'public' ? 'tmp_path: Path' : '' }) -> None:
${ surface === 'internal'
	? `    client = TestClient(create_app(StubServices()))
    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        json={"subject_id": "${ tokens.tag }-001"},
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="${ tokens.functionBase }000600000000000000000000",
            idempotency_key="${ tokens.functionBase }-contract-001",
        ),
    )`
	: `    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_${ tokens.moduleName }",
        scopes=["${ tokens.requiredScope }"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    client = TestClient(create_app(CloudServices(settings=settings)))
    request_payload = {"subject_id": "${ tokens.tag }-001"}
    body = json.dumps(request_payload).encode("utf-8")
    response = client.post(
        "${ tokens.prefix }${ tokens.endpointPath }",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "${ tokens.prefix }${ tokens.endpointPath }",
                site_id="site_${ tokens.moduleName }",
                trace_id="${ tokens.functionBase }000600000000000000000000",
                idempotency_key="${ tokens.functionBase }-contract-001",
                body=body,
            )
        ),
    )` }

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {"route", "surface", "mode", "subject_id", "metadata_keys"${ surface === 'public' ? ', "site_id"' : '' }}
${ surface === 'public' ? '\n    dispose_engine(database_url)' : '' }
`;

const mountSnippetContent = `from app.api.routes.${ tokens.moduleName } import router as ${ tokens.moduleName }_router

# In app/api/main.py
app.include_router(${ tokens.moduleName }_router)
`;

const readmeContent = `# ${ tokens.label } Cloud Route Scaffold

Generated by \`pnpm run scaffold:route -- --route-id=${ routeId } --surface=${ surface } --mode=${ mode }\`.

## Files

- \`app/api/routes/${ tokens.moduleName }.py\`
- \`tests/api/test_${ tokens.moduleName }_routes.py\`
${ shouldGenerateContract ? `- \`tests/contract/test_${ tokens.moduleName }_contract.py\`\n` : '' }- \`mount-snippet.py\`

## Promote Into Product Truth

1. Move the route module into \`app/api/routes/\`.
2. Wire the import + \`app.include_router(...)\` snippet into \`app/api/main.py\`.
3. Move the API${ shouldGenerateContract ? ' and contract' : '' } test${ shouldGenerateContract ? 's' : '' } into \`tests/api/\`${ shouldGenerateContract ? ' and `tests/contract/`' : '' }.
4. Replace scaffold payload fields, scopes, and revision values with the real route contract.

## Verify

- \`pnpm run test:api\`
${ shouldGenerateContract ? '- `pnpm run test:contract`\n' : '' }- \`pnpm run check:perimeter\`
`;

writeFile( routePath, routeContent, options.force );
writeFile( apiTestPath, apiTestContent, options.force );
if ( shouldGenerateContract ) {
	writeFile( contractTestPath, contractTestContent, options.force );
}
writeFile( mountSnippetPath, mountSnippetContent, options.force );
writeFile( readmePath, readmeContent, options.force );

console.log( `[scaffold-cloud-route] output=${ outputDir }` );
console.log( `- route=${ routePath }` );
console.log( `- api_test=${ apiTestPath }` );
if ( shouldGenerateContract ) {
	console.log( `- contract_test=${ contractTestPath }` );
}
console.log( `- mount_snippet=${ mountSnippetPath }` );
console.log( `- readme=${ readmePath }` );
