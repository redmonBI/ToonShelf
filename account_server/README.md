# Private account service

The application synchronizes metadata only: preferences, lists, favorites, reading progress,
work metadata and download records. Images are never uploaded. Records should use a chosen
device label and relative work/episode folder, not a full computer path. Registration explicitly
discloses that the master can inspect synced lists and usage. Personal tables must never be
committed to GitHub, included in release files or served as static resources.

Build from the project root with `docker build -f account_server/Dockerfile -t toonshelf-accounts .`.
Run with a persistent `/data` volume and an HTTPS reverse proxy. Inject
`TOONSHELF_MASTER_USER` and `TOONSHELF_MASTER_PASSWORD` as operator environment secrets.
There is no default master password. First boot creates the master with a salted PBKDF2 hash;
later boots do not replace its password. A normal user's existing name cannot be promoted by
changing environment variables. Keep database backups private. Do not expose port 8080
directly to the internet. Add reverse-proxy IP limits for login/register (for example 10 requests
per minute), request body limit 4 MB and a network timeout before public deployment.

For PostgreSQL use schema.sql through a trusted operator connection. The hosted service must
use its server database credential, never a browser anonymous key. No RLS policies expose
account tables. Times are Unix seconds; passwords are PBKDF2-HMAC-SHA256, 260000 iterations,
16 random salt bytes serialized in hex, 32 output bytes in hex. Sessions are 48 random bytes
base64url encoded; store only their SHA256 hex digest; expire after 30 days and revoke at logout.

API paths are appended to the configured HTTPS base endpoint. POST /v1/register requires
username, password (8+ characters), display_name and admin_visibility_consent=true. POST
/v1/login returns token, expires and user. All later requests use Authorization: Bearer token.
GET /v1/me, POST /v1/logout, GET/PUT /v1/snapshot, GET/PUT /v1/config and master-only
GET /v1/admin/users?q= plus GET/DELETE /v1/admin/users/{id}. Snapshot PUT requires
{revision,payload}, responds 409 on revision conflict. Config PUT takes {revision,menu_labels}.
Payload permits preferences/lists/favorites/history/works/reading only. Non-master calls to
administration/config PUT return 403; master deletion is prohibited. Deleting other accounts
cascades sessions and synced metadata. It does not delete their local files.

The Qt host contract is host.account_client = AccountClient(state_path, endpoint),
host.account_snapshot() -> allowed payload, host.account_apply(payload) -> update local
metadata for the logged-in account. Optional account_apply_labels(labels), account_signed_out()
and account_import_works(works) are invoked from the UI thread. Client network operations run
in AccountTask threads. Auto-login: call restore(), pull(), config() in a worker then apply on
the UI thread. Account switching must export the previous local profile privately first and
apply an empty/new account profile without copying old metadata into the new account. The
client caches snapshots under an opaque per-user ID. Never automatically push before pull.
Conflicts should offer a new pull or explicitly reviewed merge; no automatic overwrites.

This repository includes deployable server code, not an already running account service.
When offline, cached and local functions remain available. Logout revokes remotely when the
server is reachable and always clears local remembered sessions. If the server is unreachable,
the remote session can remain valid until expiry; the user must be informed of this condition.
