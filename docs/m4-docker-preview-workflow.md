# M4 Docker Preview Workflow

Status: development-only.

This workflow keeps the M5 working tree as source truth and uses the office M4
as a rebuildable Docker runtime for preview and validation. The public entry is
`https://cloud.mqzjmax.top`, protected by Cloudflare Access. Docker service
ports stay bound to M4 loopback and are not a second public ingress.

## Daily deployment

From the M5 repository root:

```bash
pnpm run m4:preview:deploy
```

The command packages tracked files plus non-ignored working-tree files, without
copying `.env`, `.env.local`, `.env.deploy`, `.git`, or ignored build caches. It
then:

1. synchronizes the source snapshot to M4;
2. starts PostgreSQL and Redis if needed;
3. runs `alembic upgrade head`;
4. recreates API, frontend, and preview Nginx without pulling images;
5. verifies the homepage and the hidden internal perimeter;
6. verifies that Docker ports are loopback-only;
7. verifies that the external hostname redirects through Cloudflare Access.

The deploy includes uncommitted, non-ignored development files intentionally,
so the M4 can preview work before it is committed. The deployed revision and
source bundle digest are recorded on M4 under
`~/.cache/npcink-ai-cloud-m4-preview/last-deploy.txt`.

## When dependencies change

If `Dockerfile`, Python dependency files, or frontend dependency files change,
the fast deploy fails closed and asks for an image refresh:

```bash
pnpm run m4:preview:deploy:images
```

This mode builds the API and frontend images on M5, uploads one compressed image
bundle to the relay server, starts a temporary HTTP service bound only to the
relay's Tailscale IP, downloads and verifies the bundle on M4, loads the images,
and removes the relay service and temporary files. No relay password or other
credential is stored in this repository; key-based SSH is required.

## Office LAN override

Tailscale is the stable default and will use a direct peer path when possible.
In the office, the SSH hop can explicitly use the LAN address:

```bash
NPCINK_CLOUD_M4_SSH_HOST=muze@192.168.10.200 \
  pnpm run m4:preview:deploy
```

## Configuration and rollback

The preview Compose project is `npcink-ai-cloud-m4-preview`. Its host bindings
are:

- proxy: `127.0.0.1:8010`;
- PostgreSQL: `127.0.0.1:15433`;
- Redis: `127.0.0.1:16380`.

M4 keeps `.env` and `.env.local` locally with mode `0600`; routine source sync
does not overwrite them. Docker-mounted or runtime-generated directories such
as `frontend/node_modules`, `frontend/.next`, `.runtime`, and caches are also
preserved instead of treated as source. Cloudflare Tunnel and Access
configuration are outside this deployment command.

To roll back application code, switch the M5 working tree to the desired commit
or restore the desired files, then run the same deploy command. Database
migrations are forward-only in this pre-GA development preview; do not treat
this workflow as a production rollback mechanism.

## Boundary

This is runtime deployment only. It does not move local ability, workflow,
prompt, preset, approval, WordPress write, MCP, or OpenClaw truth into Cloud. It
does not add a registry, scheduler, workflow engine, or public Docker listener.
