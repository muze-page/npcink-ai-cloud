#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHP_BIN="${MAGICK_WP_PHP:-$HOME/Library/Application Support/Local/lightning-services/php-8.5.3+1/bin/darwin-arm64/bin/php}"
WP_CLI="${MAGICK_WP_CLI:-/tmp/wp-cli.phar}"
WP_PATH="${MAGICK_WP_PATH:-$HOME/Local Sites/npcink/app/public}"
MYSQL_SOCKET="${MAGICK_WP_MYSQL_SOCKET:-$HOME/Library/Application Support/Local/run/NPb24Zg9g/mysql/mysqld.sock}"
POSTGRES_CONTAINER="${NPCINK_CLOUD_POSTGRES_CONTAINER:-npcink-ai-cloud-postgres-1}"
POSTGRES_USER="${NPCINK_CLOUD_POSTGRES_USER:-npcink}"
POSTGRES_DB="${NPCINK_CLOUD_POSTGRES_DB:-npcink_ai_cloud}"
FLUSH_LIMIT="${MAGICK_OBSERVABILITY_FLUSH_LIMIT:-10}"
export MAGICK_OBSERVABILITY_FLUSH_LIMIT="$FLUSH_LIMIT"

if [[ ! -x "$PHP_BIN" ]]; then
  echo "Missing PHP binary: $PHP_BIN" >&2
  exit 1
fi

if [[ ! -f "$WP_CLI" ]]; then
  echo "Missing WP-CLI phar: $WP_CLI" >&2
  exit 1
fi

if [[ ! -d "$WP_PATH" ]]; then
  echo "Missing WordPress path: $WP_PATH" >&2
  exit 1
fi

wp_eval() {
  "$PHP_BIN" \
    -d error_reporting=8191 \
    -d "mysqli.default_socket=$MYSQL_SOCKET" \
    "$WP_CLI" \
    --path="$WP_PATH" \
    eval "$1"
}

echo "== Cloud Addon observability flush =="
wp_eval '
if ( ! class_exists( "Magick_AI_Cloud_Observability_Collector" ) ) {
    fwrite( STDERR, "Magick_AI_Cloud_Observability_Collector is not loaded.\n" );
    exit( 1 );
}

$limit = max( 1, absint( getenv( "MAGICK_OBSERVABILITY_FLUSH_LIMIT" ) ?: 10 ) );
$before = Magick_AI_Cloud_Observability_Collector::get_status();
$flushes = array();

for ( $i = 0; $i < $limit; $i++ ) {
    $status = Magick_AI_Cloud_Observability_Collector::get_status();
    if ( 0 === absint( $status["buffer_count"] ?? 0 ) ) {
        break;
    }
    $flushes[] = Magick_AI_Cloud_Observability_Collector::flush_buffer();
}

$summary = Magick_AI_Cloud_Observability_Collector::refresh_summary();
$after = Magick_AI_Cloud_Observability_Collector::get_status();

echo wp_json_encode(
    array(
        "before" => array(
            "buffer_count" => absint( $before["buffer_count"] ?? 0 ),
            "total_sent" => absint( $before["total_sent"] ?? ( $before["total_uploaded"] ?? 0 ) ),
            "total_stored" => absint( $before["total_stored"] ?? 0 ),
            "total_duplicate" => absint( $before["total_duplicate"] ?? 0 ),
        ),
        "flushes" => $flushes,
        "summary_refresh_ok" => ! empty( $summary["last_refresh_ok"] ),
        "summary_refresh_error" => sanitize_text_field( (string) ( $summary["last_refresh_error"] ?? "" ) ),
        "after" => array(
            "buffer_count" => absint( $after["buffer_count"] ?? 0 ),
            "last_sent_count" => absint( $after["last_sent_count"] ?? 0 ),
            "last_stored_count" => absint( $after["last_stored_count"] ?? 0 ),
            "last_duplicate_count" => absint( $after["last_duplicate_count"] ?? 0 ),
            "total_sent" => absint( $after["total_sent"] ?? ( $after["total_uploaded"] ?? 0 ) ),
            "total_stored" => absint( $after["total_stored"] ?? 0 ),
            "total_duplicate" => absint( $after["total_duplicate"] ?? 0 ),
        ),
    ),
    JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
) . "\n";
'

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$POSTGRES_CONTAINER"; then
  echo "== Cloud PostgreSQL plugin_observability_events =="
  docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    select
      count(*) as rows_total,
      count(*) filter (where received_at >= now() - interval '24 hours') as rows_24h,
      min(received_at) as first_received_at,
      max(received_at) as last_received_at
    from plugin_observability_events;
  "
else
  echo "Skipping PostgreSQL check; container is not running: $POSTGRES_CONTAINER"
fi

echo "== Smoke URLs =="
echo "Portal: http://127.0.0.1:8010/portal/dev-entry?redirect=%2Fportal%2Fmonitoring"
echo "Admin:  http://127.0.0.1:8010/admin/dev-entry?redirect=%2Fadmin%2Fplugin-observability"
