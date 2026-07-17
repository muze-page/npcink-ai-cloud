#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PHP_BIN="${NPCINK_WP_PHP:-/Users/muze/Library/Application Support/Local/lightning-services/php-8.2.29+0/bin/darwin-arm64/bin/php}"
WP_PATH="${NPCINK_WP_PATH:-/Users/muze/Local Sites/npcink/app/public}"
WP_EXPECTED_HOME="${NPCINK_WP_EXPECTED_HOME:-http://npcink.local/}"
MYSQL_SOCKET="${NPCINK_WP_MYSQL_SOCKET:-/Users/muze/Library/Application Support/Local/run/PvPC4seEm/mysql/mysqld.sock}"
API_CONTAINER="${NPCINK_CLOUD_API_CONTAINER:-npcink-ai-cloud-api-1}"
WORKER_CONTAINER="${NPCINK_CLOUD_WORKER_CONTAINER:-npcink-ai-cloud-worker-1}"
POSTGRES_CONTAINER="${NPCINK_CLOUD_POSTGRES_CONTAINER:-npcink-ai-cloud-postgres-1}"
POSTGRES_USER="${NPCINK_CLOUD_POSTGRES_USER:-npcink}"
POSTGRES_DB="${NPCINK_CLOUD_POSTGRES_DB:-npcink_ai_cloud}"
RUN_MIGRATIONS="${NPCINK_MEDIA_DERIVATIVE_E2E_RUN_MIGRATIONS:-0}"
RESTART_WORKER="${NPCINK_MEDIA_DERIVATIVE_E2E_RESTART_WORKER:-0}"
CLEANUP="${NPCINK_MEDIA_DERIVATIVE_E2E_CLEANUP:-1}"

# E2E source media lives below a dedicated uploads subtree. Attachments are
# purged only when both the exact smoke marker and a strict run token exist;
# unrelated media is never selected by title, slug, or a global filename glob.

fail() {
	echo "[fail] $*" >&2
	exit 1
}

if ! command -v "${PHP_BIN}" >/dev/null 2>&1 && [ ! -x "${PHP_BIN}" ]; then
	fail "Missing PHP binary: ${PHP_BIN}"
fi

if [ ! -d "${WP_PATH}" ]; then
	fail "Missing WordPress path: ${WP_PATH}"
fi

if [ ! -S "${MYSQL_SOCKET}" ]; then
	fail "Missing WordPress MySQL socket: ${MYSQL_SOCKET}"
fi

if ! command -v docker >/dev/null 2>&1; then
	fail "Docker is required for the Cloud API, worker, and evidence database checks."
fi

for required_container in "${API_CONTAINER}" "${WORKER_CONTAINER}" "${POSTGRES_CONTAINER}"; do
	if ! docker ps --format '{{.Names}}' | grep -qx "${required_container}"; then
		fail "Required Cloud container is not running: ${required_container}"
	fi
done

API_ARTIFACT_MOUNT="$(docker inspect "${API_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/npcink-ai-cloud/artifacts"}}{{.Source}}{{end}}{{end}}')"
WORKER_ARTIFACT_MOUNT="$(docker inspect "${WORKER_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/npcink-ai-cloud/artifacts"}}{{.Source}}{{end}}{{end}}')"
if [ -z "${API_ARTIFACT_MOUNT}" ] || [ -z "${WORKER_ARTIFACT_MOUNT}" ] || [ "${API_ARTIFACT_MOUNT}" != "${WORKER_ARTIFACT_MOUNT}" ]; then
	fail "Cloud API and worker must share the same mounted ArtifactStore root; recreate stale containers before smoke."
fi

if docker ps --format '{{.Names}}' | grep -qx "${API_CONTAINER}"; then
	if [ "${RUN_MIGRATIONS}" = "1" ]; then
		echo "== Cloud migrations =="
		docker exec "${API_CONTAINER}" alembic upgrade head
	fi
	if [ "${RESTART_WORKER}" = "1" ]; then
		echo "== Restart Cloud runtime worker =="
		docker restart "${WORKER_CONTAINER}" >/dev/null
	fi
fi

echo "== WordPress media derivative E2E smoke =="
cd "${WP_PATH}"
set +e
SMOKE_JSON="$(NPCINK_MEDIA_DERIVATIVE_E2E_CLEANUP="${CLEANUP}" \
	NPCINK_WP_EXPECTED_PATH="${WP_PATH}" \
	NPCINK_WP_EXPECTED_HOME="${WP_EXPECTED_HOME}" \
	"${PHP_BIN}" \
	-d error_reporting=8191 \
	-d "mysqli.default_socket=${MYSQL_SOCKET}" \
	-d "pdo_mysql.default_socket=${MYSQL_SOCKET}" \
	-r '
require "wp-load.php";
$admin_user_id = 0;
foreach ((array) get_users(array("role" => "administrator", "fields" => "ID", "number" => 20)) as $candidate_user_id) {
	wp_set_current_user((int) $candidate_user_id);
	if (current_user_can("manage_options") && current_user_can("upload_files")) {
		$admin_user_id = (int) $candidate_user_id;
		break;
	}
}
if ($admin_user_id <= 0) {
	throw new RuntimeException(wp_json_encode(array(
		"success" => false,
		"failed_stage" => "administrator_capability_missing",
		"required_capabilities" => array("manage_options", "upload_files"),
	)));
}
do_action("rest_api_init");

function mde2e_rest($method, $route, $params = array()) {
	$request = new WP_REST_Request($method, $route);
	foreach ($params as $key => $value) {
		$request->set_param($key, $value);
	}
	$response = rest_do_request($request);
	if ($response instanceof WP_Error) {
		return array(
			"ok" => false,
			"error_code" => $response->get_error_code(),
			"error_message" => $response->get_error_message(),
			"error_data" => $response->get_error_data(),
		);
	}
	return array(
		"ok" => true,
		"status" => $response->get_status(),
		"data" => $response->get_data(),
	);
}

function mde2e_assert_ability_input_field($ability_id, $field, array $required_enum_values = array()) {
	$ability = mde2e_rest("GET", "/wp-abilities/v1/abilities/" . $ability_id);
	mde2e_assert($ability["ok"] && 200 === (int) ($ability["status"] ?? 0), "ability_contract_fetch", array("ability_id" => $ability_id, "ability" => $ability));

	$schema = is_array($ability["data"]["input_schema"] ?? null) ? $ability["data"]["input_schema"] : array();
	$properties = is_array($schema["properties"] ?? null) ? $schema["properties"] : array();
	$field_schema = is_array($properties[$field] ?? null) ? $properties[$field] : array();
	mde2e_assert(!empty($field_schema), "ability_contract_field_missing", array(
		"ability_id" => $ability_id,
		"field" => $field,
		"input_properties" => array_keys($properties),
	));

	if (!empty($required_enum_values)) {
		$enum = array_values(array_map("strval", is_array($field_schema["enum"] ?? null) ? $field_schema["enum"] : array()));
		$missing = array_values(array_diff($required_enum_values, $enum));
		mde2e_assert(empty($missing), "ability_contract_enum_missing", array(
			"ability_id" => $ability_id,
			"field" => $field,
			"enum" => $enum,
			"missing" => $missing,
		));
	}
}

function mde2e_fail($stage, $data) {
	throw new RuntimeException(wp_json_encode(
		array(
			"success" => false,
			"failed_stage" => $stage,
			"data" => $data,
		),
		JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
	));
}

function mde2e_assert($condition, $stage, $data) {
	if (!$condition) {
		mde2e_fail($stage, $data);
	}
}

function mde2e_assert_wordpress_identity() {
	require_once ABSPATH . "wp-admin/includes/plugin.php";

	$expected_path = realpath((string) getenv("NPCINK_WP_EXPECTED_PATH"));
	$actual_path = realpath(ABSPATH);
	mde2e_assert(false !== $expected_path && false !== $actual_path && $expected_path === $actual_path, "wordpress_abspath_mismatch", array(
		"expected" => $expected_path,
		"actual" => $actual_path,
	));

	$expected_home = untrailingslashit((string) getenv("NPCINK_WP_EXPECTED_HOME"));
	$actual_home = untrailingslashit(home_url("/"));
	mde2e_assert("" !== $expected_home && $expected_home === $actual_home, "wordpress_home_mismatch", array(
		"expected" => $expected_home,
		"actual" => $actual_home,
	));

	$plugins = array(
		"npcink-cloud-addon/npcink-cloud-addon.php" => "NPCINK_CLOUD_ADDON_FILE",
		"npcink-abilities-toolkit/npcink-abilities-toolkit.php" => "NPCINK_ABILITIES_TOOLKIT_FILE",
		"npcink-ai-client-adapter/npcink-ai-client-adapter.php" => "NPCINK_OPENCLAW_ADAPTER_FILE",
		"npcink-governance-core/npcink-governance-core.php" => "NPCINK_GOVERNANCE_CORE_FILE",
		"npcink-workflow-toolbox/npcink-workflow-toolbox.php" => "NPCINK_TOOLBOX_FILE",
	);
	foreach ($plugins as $plugin => $file_constant) {
		$expected_file = realpath(WP_PLUGIN_DIR . "/" . $plugin);
		$actual_file = defined($file_constant) ? realpath((string) constant($file_constant)) : false;
		mde2e_assert(is_plugin_active($plugin), "required_plugin_inactive", array("plugin" => $plugin));
		mde2e_assert(false !== $expected_file && $expected_file === $actual_file, "required_plugin_source_mismatch", array(
			"plugin" => $plugin,
			"constant" => $file_constant,
			"expected" => $expected_file,
			"actual" => $actual_file,
		));
		mde2e_assert(false !== $actual_file && false !== strpos(str_replace("\\", "/", $actual_file), "/npcink-"), "required_plugin_source_not_npcink", array(
			"plugin" => $plugin,
			"actual" => $actual_file,
		));
	}
}

function mde2e_assert_no_remote_artifact_material(array $value) {
	$encoded = wp_json_encode($value, JSON_UNESCAPED_SLASHES);
	$lower = strtolower((string) $encoded);
	foreach (array("http://", "https://", "data:", "storage_key", "base64", "token") as $forbidden) {
		mde2e_assert(false === strpos($lower, $forbidden), "cloud_artifact_material_leak", array("forbidden" => $forbidden));
	}
}

function mde2e_run_governed_read_ability($ability_id, array $input, $purpose) {
	global $created_read_request_ids, $read_authorization_evidence;

	$direct = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/run-read-ability", array(
		"ability_id" => $ability_id,
		"input" => $input,
	));
	$direct_error_code = (string) ($direct["data"]["code"] ?? $direct["error_code"] ?? "");
	mde2e_assert(
		$direct["ok"]
		&& 403 === (int) ($direct["status"] ?? 0)
		&& "npcink_openclaw_adapter_core_read_authorization_required" === $direct_error_code,
		"governed_read_fail_closed",
		array("ability_id" => $ability_id, "direct" => $direct)
	);

	$read_request = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/read-requests", array(
		"ability_id" => $ability_id,
		"input" => $input,
		"requested_input_summary" => "Media derivative E2E bounded read: " . $ability_id,
		"data_classes" => array("media", "attachment_metadata"),
		"redaction_level" => "strict",
		"purpose" => $purpose,
		"caller" => array(
			"external_thread_id" => "media-derivative-e2e-smoke",
		),
		"bounds" => array(
			"denied_fields" => array("authorization", "cookie", "application_password"),
		),
	));
	mde2e_assert(
		$read_request["ok"]
		&& in_array((int) ($read_request["status"] ?? 0), array(200, 201), true)
		&& "pending" === (string) ($read_request["data"]["status"] ?? ""),
		"governed_read_request_create",
		array("ability_id" => $ability_id, "read_request" => $read_request)
	);
	$read_request_id = (string) ($read_request["data"]["request_id"] ?? "");
	mde2e_assert("" !== $read_request_id, "governed_read_request_missing_id", $read_request);
	$created_read_request_ids[$read_request_id] = true;

	$approved = mde2e_rest(
		"POST",
		"/npcink-governance-core/v1/read-requests/" . rawurlencode($read_request_id) . "/approve",
		array(
			"note" => "Media derivative E2E approval",
			"redaction_level" => "strict",
			"denied_fields" => array("authorization", "cookie", "application_password"),
		)
	);
	mde2e_assert(
		$approved["ok"]
		&& 200 === (int) ($approved["status"] ?? 0)
		&& "approved" === (string) ($approved["data"]["status"] ?? ""),
		"governed_read_request_approve",
		array("ability_id" => $ability_id, "read_request_id" => $read_request_id, "approved" => $approved)
	);

	$granted = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/run-read-ability", array(
		"ability_id" => $ability_id,
		"input" => $input,
		"read_request_id" => $read_request_id,
	));
	$core_context = is_array($granted["data"]["read_context"]["npcink_governance_core"] ?? null)
		? $granted["data"]["read_context"]["npcink_governance_core"]
		: array();
	mde2e_assert(
		$granted["ok"]
		&& 200 === (int) ($granted["status"] ?? 0)
		&& !empty($granted["data"]["read_context"]["read_authorization_granted"])
		&& $read_request_id === (string) ($core_context["read_request_id"] ?? "")
		&& "npcink_governance_core" === (string) ($core_context["core_authorization_truth"] ?? ""),
		"governed_read_adapter_preflight",
		array("ability_id" => $ability_id, "read_request_id" => $read_request_id, "granted" => $granted)
	);
	$read_authorization_evidence[] = array(
		"ability_id" => $ability_id,
		"authorization_required" => true,
		"fail_closed_code" => $direct_error_code,
		"core_preflight_granted" => true,
	);
	return $granted;
}

function mde2e_create_proposal($ability_id, array $input, array $preview, $title, $summary, array $caller) {
	global $created_proposal_ids;

	$proposal = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/proposals", array(
		"ability_id" => $ability_id,
		"title" => $title,
		"summary" => $summary,
		"input" => $input,
		"preview" => $preview,
		"caller" => $caller,
	));
	mde2e_assert($proposal["ok"] && in_array((int) ($proposal["status"] ?? 0), array(200, 201), true), "create_proposal", $proposal);
	$proposal_id = (string) ($proposal["data"]["proposal_id"] ?? "");
	mde2e_assert("" !== $proposal_id, "proposal_missing_id", $proposal);
	$created_proposal_ids[$proposal_id] = true;
	return array($proposal_id, $proposal);
}

function mde2e_execute_proposal($proposal_id) {
	$execute = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/proposals/" . rawurlencode($proposal_id) . "/approve-and-execute");
	mde2e_assert($execute["ok"] && 200 === (int) ($execute["status"] ?? 0) && !empty($execute["data"]["success"]), "approve_and_execute", array("proposal_id" => $proposal_id, "execute" => $execute));
	return $execute;
}

function mde2e_assert_core_proposal_audit($proposal_id) {
	$detail = mde2e_rest("GET", "/npcink-governance-core/v1/proposals/" . rawurlencode($proposal_id));
	mde2e_assert($detail["ok"] && 200 === (int) ($detail["status"] ?? 0), "core_proposal_detail", array("proposal_id" => $proposal_id, "detail" => $detail));
	$timeline = array_values(array_filter((array) ($detail["data"]["audit_timeline"] ?? array()), "is_array"));
	$event_names = array_map(static function (array $event) {
		return (string) ($event["event_name"] ?? "");
	}, $timeline);
	foreach (array("proposal.created", "proposal.approved", "commit.preflighted", "proposal.executed") as $required_event) {
		mde2e_assert(1 === count(array_keys($event_names, $required_event, true)), "core_proposal_audit_incomplete", array(
			"proposal_id" => $proposal_id,
			"required_event" => $required_event,
			"event_names" => $event_names,
		));
	}
	return $event_names;
}

function mde2e_proposals_from_plan($plan_ability_id, array $plan, array $plan_input, array $caller = array()) {
	global $created_proposal_ids;

	$request = array(
		"plan_ability_id" => $plan_ability_id,
		"plan" => $plan,
		"plan_input" => $plan_input,
	);
	if (!empty($caller)) {
		$request["caller"] = $caller;
	}
	$bridge = mde2e_rest("POST", "/npcink-openclaw-adapter/v1/proposals/from-plan", $request);
	mde2e_assert($bridge["ok"] && in_array((int) ($bridge["status"] ?? 0), array(200, 201), true), "proposals_from_plan", array("plan_ability_id" => $plan_ability_id, "bridge" => $bridge));
	$proposals = array();
	if (isset($bridge["data"]["proposals"]) && is_array($bridge["data"]["proposals"])) {
		$proposals = array_values(array_filter($bridge["data"]["proposals"], "is_array"));
	} elseif (isset($bridge["data"]["proposal"]) && is_array($bridge["data"]["proposal"])) {
		$proposals = array($bridge["data"]["proposal"]);
	} elseif (isset($bridge["data"]["proposal_id"])) {
		$proposals = array($bridge["data"]);
	}
	foreach ($proposals as $proposal) {
		$proposal_id = (string) ($proposal["proposal_id"] ?? "");
		if ("" !== $proposal_id) {
			$created_proposal_ids[$proposal_id] = true;
		}
	}
	return $proposals;
}

function mde2e_proposal_id(array $proposal) {
	return (string) ($proposal["proposal_id"] ?? "");
}

function mde2e_patchable_setting_targets($targets, $target_type = "", $target_name = "") {
	global $created_option_names, $created_theme_mod_names;
	unset($target_type, $target_name);
	$targets = is_array($targets) ? $targets : array();
	$targets["option"] = array_values(array_unique(array_merge(
		is_array($targets["option"] ?? null) ? $targets["option"] : array(),
		array_map("sanitize_key", $created_option_names)
	)));
	$targets["theme_mod"] = array_values(array_unique(array_merge(
		is_array($targets["theme_mod"] ?? null) ? $targets["theme_mod"] : array(),
		array_map("sanitize_key", $created_theme_mod_names)
	)));
	return $targets;
}

function mde2e_unlink_upload($relative_file) {
	$relative_file = ltrim((string) $relative_file, "/");
	if ("" === $relative_file) {
		return;
	}
	$uploads = wp_upload_dir();
	$path = trailingslashit($uploads["basedir"]) . $relative_file;
	if (is_file($path)) {
		@unlink($path);
	}
}

function mde2e_attachment_metadata_relative_files(array $metadata) {
	$main_file = ltrim(str_replace("\\", "/", (string) ($metadata["file"] ?? "")), "/");
	if ("" === $main_file || false !== strpos($main_file, "../")) {
		return array();
	}
	$files = array($main_file);
	$main_dir = dirname($main_file);
	$main_dir = "." === $main_dir ? "" : trim($main_dir, "/");
	foreach ((array) ($metadata["sizes"] ?? array()) as $size) {
		$size_file = is_array($size) ? basename((string) ($size["file"] ?? "")) : "";
		if ("" !== $size_file) {
			$files[] = "" !== $main_dir ? $main_dir . "/" . $size_file : $size_file;
		}
	}
	$original_image = basename((string) ($metadata["original_image"] ?? ""));
	if ("" !== $original_image) {
		$files[] = "" !== $main_dir ? $main_dir . "/" . $original_image : $original_image;
	}
	return array_values(array_unique($files));
}

function mde2e_attachment_history_relative_files($attachment_id) {
	$history = get_post_meta((int) $attachment_id, "_npcink_ai_media_file_replacement_history", true);
	if (!is_array($history)) {
		return array();
	}
	if (isset($history["replacement_id"])) {
		$history = array($history);
	}
	$files = array();
	foreach ($history as $record) {
		if (!is_array($record)) {
			continue;
		}
		foreach (array("before", "after", "backup", "current_backup") as $state_key) {
			$state = is_array($record[$state_key] ?? null) ? $record[$state_key] : array();
			$relative_file = ltrim(str_replace("\\", "/", (string) ($state["relative_file"] ?? "")), "/");
			if ("" !== $relative_file && false === strpos($relative_file, "../")) {
				$files[] = $relative_file;
			}
		}
	}
	return array_values(array_unique($files));
}

function mde2e_related_generated_relative_files($relative_file) {
	$relative_file = ltrim(str_replace("\\", "/", (string) $relative_file), "/");
	$basename = basename($relative_file);
	if ("" === $relative_file || false !== strpos($relative_file, "../") || 0 !== strpos($basename, "media-derivative-")) {
		return array();
	}
	$uploads = wp_upload_dir();
	$basedir = is_array($uploads) ? untrailingslashit((string) ($uploads["basedir"] ?? "")) : "";
	if ("" === $basedir) {
		return array();
	}
	$relative_dir = dirname($relative_file);
	$relative_dir = "." === $relative_dir ? "" : trim($relative_dir, "/");
	$stem = pathinfo($basename, PATHINFO_FILENAME);
	$extension = pathinfo($basename, PATHINFO_EXTENSION);
	if (1 !== preg_match("/^[A-Za-z0-9._-]+$/", $stem) || 1 !== preg_match("/^[A-Za-z0-9]+$/", $extension)) {
		return array();
	}
	$directory = $basedir . ("" !== $relative_dir ? "/" . $relative_dir : "");
	$related = array();
	foreach ((array) glob($directory . "/" . $stem . "-*." . $extension) as $path) {
		if (is_file($path)) {
			$related[] = "" !== $relative_dir ? $relative_dir . "/" . basename($path) : basename($path);
		}
	}
	return array_values(array_unique($related));
}

function mde2e_smoke_media_attachment_ids() {
	global $wpdb;

	return array_map(
		"absint",
		(array) $wpdb->get_col(
			$wpdb->prepare(
				"select distinct p.ID
				from {$wpdb->posts} p
				inner join {$wpdb->postmeta} marker
					on p.ID = marker.post_id
					and marker.meta_key = %s
					and marker.meta_value = %s
				inner join {$wpdb->postmeta} run_token
					on p.ID = run_token.post_id
					and run_token.meta_key = %s
					and run_token.meta_value regexp %s
				where p.post_type = %s",
				"_npcink_ai_cloud_media_derivative_e2e_marker",
				"media_derivative_wordpress_e2e_smoke.v1",
				"_npcink_ai_cloud_media_derivative_e2e_run_id",
				"^[0-9]{14}-[0-9a-f]{8}$",
				"attachment"
			)
		)
	);
}

function mde2e_smoke_media_file_paths() {
	$uploads = wp_upload_dir();
	$basedir = is_array($uploads) && !empty($uploads["basedir"]) ? untrailingslashit((string) $uploads["basedir"]) : "";
	if ("" === $basedir) {
		return array();
	}

	$smoke_dir = $basedir . "/npcink-media-derivative-e2e-smoke";
	$real_basedir = realpath($basedir);
	$real_smoke_dir = realpath($smoke_dir);
	if (false === $real_basedir || false === $real_smoke_dir || 0 !== strpos($real_smoke_dir . "/", $real_basedir . "/npcink-media-derivative-e2e-smoke/")) {
		return array();
	}

	$paths = array();
	$iterator = new RecursiveIteratorIterator(
		new RecursiveDirectoryIterator($real_smoke_dir, FilesystemIterator::SKIP_DOTS)
	);
	foreach ($iterator as $file_info) {
		if ($file_info->isFile()) {
			$paths[] = $file_info->getPathname();
		}
	}

	return array_values(array_filter(array_unique($paths), "is_file"));
}

function mde2e_prune_smoke_media_directories() {
	$uploads = wp_upload_dir();
	$basedir = is_array($uploads) && !empty($uploads["basedir"]) ? untrailingslashit((string) $uploads["basedir"]) : "";
	$smoke_dir = $basedir . "/npcink-media-derivative-e2e-smoke";
	$real_basedir = realpath($basedir);
	$real_smoke_dir = realpath($smoke_dir);
	if (false === $real_basedir || false === $real_smoke_dir || 0 !== strpos($real_smoke_dir . "/", $real_basedir . "/npcink-media-derivative-e2e-smoke/")) {
		return;
	}

	$iterator = new RecursiveIteratorIterator(
		new RecursiveDirectoryIterator($real_smoke_dir, FilesystemIterator::SKIP_DOTS),
		RecursiveIteratorIterator::CHILD_FIRST
	);
	foreach ($iterator as $file_info) {
		if ($file_info->isDir()) {
			@rmdir($file_info->getPathname());
		}
	}
	@rmdir($real_smoke_dir);
}

function mde2e_cleanup_stale_smoke_media() {
	$deleted_attachments = 0;
	$deleted_files = 0;
	$known_relative_files = array();

	foreach (mde2e_smoke_media_attachment_ids() as $attachment_id) {
		$known_relative_files = array_merge(
			$known_relative_files,
			mde2e_attachment_metadata_relative_files((array) wp_get_attachment_metadata($attachment_id)),
			mde2e_attachment_history_relative_files($attachment_id)
		);
		if ($attachment_id > 0 && false !== wp_delete_attachment($attachment_id, true)) {
			$deleted_attachments++;
		}
	}
	foreach (array_values(array_unique($known_relative_files)) as $relative_file) {
		$related_files = mde2e_related_generated_relative_files($relative_file);
		foreach (array_merge(array($relative_file), $related_files) as $cleanup_relative_file) {
			$uploads = wp_upload_dir();
			$cleanup_path = trailingslashit((string) ($uploads["basedir"] ?? "")) . ltrim($cleanup_relative_file, "/");
			if (is_file($cleanup_path) && @unlink($cleanup_path)) {
				$deleted_files++;
			}
		}
	}
	$uploads = wp_upload_dir();
	foreach (array_values(array_unique($known_relative_files)) as $relative_file) {
		$remaining_relative_files = array_merge(array($relative_file), mde2e_related_generated_relative_files($relative_file));
		foreach ($remaining_relative_files as $remaining_relative_file) {
			$remaining_path = trailingslashit((string) ($uploads["basedir"] ?? "")) . ltrim((string) $remaining_relative_file, "/");
			mde2e_assert(!is_file($remaining_path), "stale_cleanup_file_leak_guard", array("relative_file" => $remaining_relative_file));
		}
	}

	foreach (mde2e_smoke_media_file_paths() as $path) {
		if (@unlink($path)) {
			$deleted_files++;
		}
	}
	mde2e_prune_smoke_media_directories();

	return array(
		"attachments" => $deleted_attachments,
		"files" => $deleted_files,
	);
}

function mde2e_assert_no_smoke_media_leaks() {
	$attachment_ids = array_values(array_filter(mde2e_smoke_media_attachment_ids()));
	$file_paths = mde2e_smoke_media_file_paths();
	if (!empty($attachment_ids) || !empty($file_paths)) {
		mde2e_fail("cleanup_leak_guard", array(
			"attachment_ids" => $attachment_ids,
			"file_paths" => $file_paths,
		));
	}
}

$cleanup = "1" === (string) getenv("NPCINK_MEDIA_DERIVATIVE_E2E_CLEANUP");
mde2e_assert_wordpress_identity();
$stale_cleanup = $cleanup ? mde2e_cleanup_stale_smoke_media() : array("attachments" => 0, "files" => 0);
$created_pages = array();
$created_attachment_id = 0;
$created_option_names = array();
$created_theme_mod_names = array();
$created_relative_files = array();
$created_proposal_ids = array();
$created_read_request_ids = array();
$read_authorization_evidence = array();
$mde2e_failure_json = "";

try {
	mde2e_assert_ability_input_field("npcink-abilities-toolkit/replace-media-file", "derivative_relative_file");
	mde2e_assert_ability_input_field("npcink-abilities-toolkit/restore-media-backup", "backup_id");

	$upload = wp_upload_dir();
	$stamp = gmdate("YmdHis") . "-" . bin2hex(random_bytes(4));
	$dir = trailingslashit($upload["basedir"]) . "npcink-media-derivative-e2e-smoke/" . $stamp . "/";
	if (!is_dir($dir)) {
		wp_mkdir_p($dir);
	}

	$filename = "npcink-e2e-media-derivative-" . $stamp . "-pending.png";
	$path = $dir . $filename;
	$image = imagecreatetruecolor(800, 450);
	$bg = imagecolorallocate($image, 60, 70, 85);
	$panel = imagecolorallocate($image, 250, 250, 250);
	$accent = imagecolorallocate($image, 96, 165, 250);
	$text = imagecolorallocate($image, 20, 30, 45);
	imagefilledrectangle($image, 0, 0, 799, 449, $bg);
	imagefilledrectangle($image, 70, 80, 730, 370, $panel);
	imagefilledellipse($image, 400, 225, 260, 170, $accent);
	imagestring($image, 5, 265, 212, "Npcink AI Media Smoke", $text);
	imagepng($image, $path);
	imagedestroy($image);
	$file_hash = substr(md5_file($path), 0, 8);
	$filename = sanitize_file_name("npcink-e2e-media-derivative-" . $stamp . "-" . $file_hash . ".png");
	$hashed_path = $dir . $filename;
	if ($hashed_path !== $path) {
		rename($path, $hashed_path);
		$path = $hashed_path;
	}

	$filetype = wp_check_filetype($filename, null);
	$attachment_id = wp_insert_attachment(array(
		"post_mime_type" => $filetype["type"] ?: "image/png",
		"post_title" => "Npcink AI media derivative smoke " . $stamp,
		"post_status" => "inherit",
	), $path);
	mde2e_assert(!is_wp_error($attachment_id) && (int) $attachment_id > 0, "source_attachment_insert_failed", $attachment_id);
	$created_attachment_id = (int) $attachment_id;
	update_post_meta($created_attachment_id, "_npcink_ai_cloud_media_derivative_e2e_marker", "media_derivative_wordpress_e2e_smoke.v1");
	update_post_meta($created_attachment_id, "_npcink_ai_cloud_media_derivative_e2e_run_id", $stamp);
	require_once ABSPATH . "wp-admin/includes/image.php";
	wp_update_attachment_metadata($attachment_id, wp_generate_attachment_metadata($attachment_id, $path));

	$before_url = wp_get_attachment_url($attachment_id);
	$before_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	$before_path = get_attached_file($attachment_id, true);
	$before_image = is_string($before_path) && is_file($before_path) ? getimagesize($before_path) : false;
	$before_checksum = is_string($before_path) && is_file($before_path) ? "sha256:" . hash_file("sha256", $before_path) : "";
	mde2e_assert(is_array($before_image) && "image/png" === (string) ($before_image["mime"] ?? ""), "source_file_invalid", array("path" => $before_path, "image" => $before_image));
	$created_relative_files = array_merge(
		$created_relative_files,
		mde2e_attachment_metadata_relative_files((array) wp_get_attachment_metadata($attachment_id))
	);
	$page_id = wp_insert_post(array(
		"post_title" => "Npcink AI media derivative smoke page " . gmdate("c"),
		"post_status" => "publish",
		"post_type" => "page",
		"post_content" => "<figure class=\"wp-block-image\"><img src=\"" . esc_url($before_url) . "\" class=\"wp-image-" . (int) $attachment_id . "\" alt=\"smoke\" /></figure>",
	));
	$created_pages[] = (int) $page_id;

	$batch_plan_envelope = mde2e_run_governed_read_ability(
		"npcink-abilities-toolkit/build-media-derivative-batch-plan",
		array(
			"attachment_ids" => array($attachment_id),
			"target_format" => "webp",
			"exclude_formats" => array("gif", "svg"),
			"target_max_width" => 320,
			"quality" => 80,
			"min_width" => 0,
			"min_height" => 0,
			"max_items" => 5,
		),
		"Build the bounded media derivative batch plan for this smoke attachment."
	);
	mde2e_assert($batch_plan_envelope["ok"] && 200 === (int) ($batch_plan_envelope["status"] ?? 0), "batch_plan_build", $batch_plan_envelope);
	$batch_plan = (array) ($batch_plan_envelope["data"]["result"]["data"] ?? $batch_plan_envelope["data"]["data"] ?? array());
	$batch_candidates = array_values(array_filter((array) ($batch_plan["candidates"] ?? array()), "is_array"));
	$batch_candidate = array();
	foreach ($batch_candidates as $candidate) {
		if ((int) ($candidate["attachment_id"] ?? 0) === (int) $attachment_id) {
			$batch_candidate = $candidate;
			break;
		}
	}
	mde2e_assert(!empty($batch_candidate), "batch_plan_missing_smoke_candidate", $batch_plan);
	$batch_cloud_input = is_array($batch_candidate["cloud_request_input"] ?? null) ? $batch_candidate["cloud_request_input"] : array();
	mde2e_assert((int) ($batch_cloud_input["attachment_id"] ?? 0) === (int) $attachment_id && "webp" === (string) ($batch_cloud_input["preferred_format"] ?? ""), "batch_plan_cloud_input_invalid", $batch_candidate);
	$batch_size_recommendation = (int) ($batch_plan["execution_plan"]["batch_size_recommendation"] ?? 0);
	mde2e_assert($batch_size_recommendation >= 1, "batch_plan_missing_chunk_recommendation", $batch_plan);

	$trace_id = "wp-media-derivative-e2e-" . $attachment_id;
	$ability_envelope = mde2e_run_governed_read_ability(
		"npcink-abilities-toolkit/build-media-derivative-cloud-request",
		$batch_cloud_input,
		"Build the bounded Cloud media derivative request for this smoke attachment."
	);
	mde2e_assert($ability_envelope["ok"] && 200 === (int) ($ability_envelope["status"] ?? 0), "derivative_ability_build", $ability_envelope);
	$ability_response = is_array($ability_envelope["data"]["result"] ?? null) ? $ability_envelope["data"]["result"] : array();
	$ability_data = is_array($ability_response["data"] ?? null) ? $ability_response["data"] : array();
	mde2e_assert(
		!empty($ability_response["success"])
		&& "media_derivative_cloud_request.v1" === (string) ($ability_data["request_contract_version"] ?? "")
		&& (int) ($ability_data["attachment_id"] ?? 0) === (int) $attachment_id
		&& empty($ability_data["blocked"]),
		"derivative_ability_contract_invalid",
		$ability_response
	);
	foreach (array(
		"npcink_cloud_addon_dispatch_media_derivative_cloud_request",
		"npcink_cloud_addon_media_derivative_run_id",
		"npcink_cloud_addon_get_media_derivative_run",
		"npcink_cloud_addon_get_media_derivative_run_result",
		"npcink_cloud_addon_build_media_derivative_proposal_payload",
		"npcink_cloud_addon_receive_media_derivative_artifact",
		"npcink_cloud_addon_build_media_derivative_optimization_payload",
	) as $addon_seam) {
		mde2e_assert(function_exists($addon_seam), "cloud_addon_seam_missing", array("function" => $addon_seam));
	}

	$create = npcink_cloud_addon_dispatch_media_derivative_cloud_request(
		$ability_response,
		array(
			"path" => $before_path,
			"filename" => basename($before_path),
			"mime_type" => "image/png",
		),
		$trace_id,
		"wp-media-derivative-e2e-" . $attachment_id . "-" . time()
	);
	mde2e_assert(!is_wp_error($create) && is_array($create), "create_derivative_run", $create);
	$run_id = npcink_cloud_addon_media_derivative_run_id($create);
	mde2e_assert("" !== $run_id, "create_derivative_run_missing_run_id", $create);

	$status = array();
	$state = "";
	for ($i = 0; $i < 40; $i++) {
		usleep(0 === $i ? 250000 : 750000);
		$status = npcink_cloud_addon_get_media_derivative_run($run_id, $trace_id);
		mde2e_assert(!is_wp_error($status) && is_array($status), "poll_run", $status);
		$status_data = is_array($status["data"] ?? null) ? $status["data"] : $status;
		$state = (string) ($status_data["status"] ?? "");
		if (in_array($state, array("succeeded", "completed", "failed"), true)) {
			break;
		}
	}
	mde2e_assert(in_array($state, array("succeeded", "completed"), true), "cloud_run_not_success", $status);

	$cloud_projection = npcink_cloud_addon_get_media_derivative_run_result($run_id, $trace_id);
	mde2e_assert(!is_wp_error($cloud_projection) && is_array($cloud_projection), "poll_result", array("status" => $status, "result" => $cloud_projection));
	$expected_result_fields = array("artifact", "created_at", "error", "job_type", "run_id", "status", "updated_at", "warnings");
	$actual_result_fields = array_keys($cloud_projection);
	sort($actual_result_fields);
	mde2e_assert($expected_result_fields === $actual_result_fields, "cloud_result_fields_invalid", array("expected" => $expected_result_fields, "actual" => $actual_result_fields));
	mde2e_assert(
		(string) ($cloud_projection["run_id"] ?? "") === (string) $run_id
		&& in_array((string) ($cloud_projection["status"] ?? ""), array("succeeded", "completed"), true)
		&& is_array($cloud_projection["warnings"] ?? null)
		&& is_array($cloud_projection["error"] ?? null),
		"cloud_result_projection_invalid",
		$cloud_projection
	);
	$artifact = is_array($cloud_projection["artifact"] ?? null) ? (array) $cloud_projection["artifact"] : array();
	$expected_artifact_fields = array("artifact_id", "artifact_reference", "checksum", "expires_at", "filename_basis", "filesize_bytes", "format", "height", "mime_type", "processing_warnings", "suggested_filename", "width");
	$actual_artifact_fields = array_keys($artifact);
	sort($actual_artifact_fields);
	mde2e_assert($expected_artifact_fields === $actual_artifact_fields, "cloud_artifact_fields_invalid", array("expected" => $expected_artifact_fields, "actual" => $actual_artifact_fields));
	mde2e_assert(1 === preg_match("/^art_[0-9a-f]{32}$/", (string) ($artifact["artifact_id"] ?? "")), "missing_artifact", $artifact);
	mde2e_assert(array("artifact_id" => (string) $artifact["artifact_id"]) === ($artifact["artifact_reference"] ?? null), "artifact_reference_invalid", $artifact);
	mde2e_assert("image/webp" === (string) ($artifact["mime_type"] ?? "") && "webp" === (string) ($artifact["format"] ?? ""), "artifact_media_type_invalid", $artifact);
	mde2e_assert((int) ($artifact["filesize_bytes"] ?? 0) > 0 && (int) ($artifact["width"] ?? 0) > 0 && (int) ($artifact["height"] ?? 0) > 0, "artifact_dimensions_invalid", $artifact);
	mde2e_assert(1 === preg_match("/^sha256:[0-9a-f]{64}$/", (string) ($artifact["checksum"] ?? "")), "artifact_checksum_invalid", $artifact);
	mde2e_assert(
		array(
			"owner" => "wordpress_write_ability_final",
			"strategy" => "format_checksum",
			"final_sanitize_unique_required" => true,
		) === ($artifact["filename_basis"] ?? null),
		"artifact_filename_basis_invalid",
		$artifact
	);
	mde2e_assert(
		1 === preg_match("/^media-derivative-webp-[0-9a-f]{8}\\.webp$/", (string) ($artifact["suggested_filename"] ?? ""))
		&& basename((string) $artifact["suggested_filename"]) === (string) $artifact["suggested_filename"],
		"artifact_suggested_filename_invalid",
		$artifact
	);
	mde2e_assert(is_array($artifact["processing_warnings"] ?? null), "artifact_processing_warnings_invalid", $artifact);
	mde2e_assert_no_remote_artifact_material($cloud_projection);

	$local_proposal = npcink_cloud_addon_build_media_derivative_proposal_payload(
		$ability_response,
		$cloud_projection,
		$artifact
	);
	mde2e_assert(!is_wp_error($local_proposal) && is_array($local_proposal), "build_local_proposal", $local_proposal);
	$local_artifact = is_array($local_proposal["artifact"] ?? null) ? $local_proposal["artifact"] : array();
	$expected_local_artifact_fields = array("artifact_id", "expires_at", "filename_basis", "filesize_bytes", "format", "height", "mime_type", "processing_warnings", "sha256", "suggested_filename", "width");
	$actual_local_artifact_fields = array_keys($local_artifact);
	sort($actual_local_artifact_fields);
	mde2e_assert($expected_local_artifact_fields === $actual_local_artifact_fields, "local_proposal_artifact_fields_invalid", array("expected" => $expected_local_artifact_fields, "actual" => $actual_local_artifact_fields));
	mde2e_assert(
		(string) ($local_artifact["artifact_id"] ?? "") === (string) $artifact["artifact_id"]
		&& (string) ($local_artifact["expires_at"] ?? "") === (string) $artifact["expires_at"]
		&& (string) ($local_artifact["sha256"] ?? "") === substr((string) $artifact["checksum"], 7)
		&& (string) ($local_artifact["suggested_filename"] ?? "") === (string) $artifact["suggested_filename"]
		&& ($local_artifact["filename_basis"] ?? null) === ($artifact["filename_basis"] ?? null)
		&& ($local_artifact["processing_warnings"] ?? null) === ($artifact["processing_warnings"] ?? null)
		&& !isset($local_artifact["artifact_reference"], $local_artifact["checksum"]),
		"local_proposal_artifact_projection_invalid",
		$local_artifact
	);
	mde2e_assert_no_remote_artifact_material($local_artifact);

	$received = npcink_cloud_addon_receive_media_derivative_artifact($local_artifact, $trace_id);
	mde2e_assert(!is_wp_error($received) && is_array($received), "receive_derivative_artifact", $received);
	$expected_received_fields = array("artifact_id", "contents", "delivery_ack", "expires_at", "filesize_bytes", "height", "mime_type", "sha256", "transfer_evidence", "width");
	$actual_received_fields = array_keys($received);
	sort($actual_received_fields);
	mde2e_assert($expected_received_fields === $actual_received_fields, "received_artifact_fields_invalid", array("expected" => $expected_received_fields, "actual" => $actual_received_fields));
	$received_image = is_string($received["contents"] ?? null) ? getimagesizefromstring($received["contents"]) : false;
	$received_expires_at = strtotime((string) ($received["expires_at"] ?? ""));
	$cloud_expires_at = strtotime((string) ($artifact["expires_at"] ?? ""));
	mde2e_assert(
		(string) ($received["artifact_id"] ?? "") === (string) $artifact["artifact_id"]
		&& is_string($received["contents"] ?? null)
		&& strlen($received["contents"]) === (int) $artifact["filesize_bytes"]
		&& (int) ($received["filesize_bytes"] ?? 0) === (int) $artifact["filesize_bytes"]
		&& (string) ($received["mime_type"] ?? "") === (string) $artifact["mime_type"]
		&& (int) ($received["width"] ?? 0) === (int) $artifact["width"]
		&& (int) ($received["height"] ?? 0) === (int) $artifact["height"]
		&& (string) ($received["sha256"] ?? "") === substr((string) $artifact["checksum"], 7)
		&& hash("sha256", $received["contents"]) === (string) $received["sha256"]
		&& is_array($received_image)
		&& (string) ($received_image["mime"] ?? "") === (string) $received["mime_type"]
		&& (int) ($received_image[0] ?? 0) === (int) $received["width"]
		&& (int) ($received_image[1] ?? 0) === (int) $received["height"]
		&& false !== $received_expires_at
		&& $received_expires_at > time()
		&& false !== $cloud_expires_at
		&& $received_expires_at <= $cloud_expires_at,
		"received_artifact_facts_invalid",
		array_diff_key($received, array("contents" => true))
	);
	$transfer_evidence = is_array($received["transfer_evidence"] ?? null) ? $received["transfer_evidence"] : array();
	$delivery_ack = is_array($received["delivery_ack"] ?? null) ? $received["delivery_ack"] : array();
	$acknowledged_at_ts = strtotime((string) ($delivery_ack["acknowledged_at"] ?? ""));
	$ack_expires_at_ts = strtotime((string) ($delivery_ack["artifact_expires_at"] ?? ""));
	$ack_deadline_at_ts = strtotime((string) ($transfer_evidence["ack_deadline_at"] ?? ""));
	$expected_ack_fields = array("acknowledged_at", "acknowledgement_scope", "artifact_expires_at", "artifact_id", "byte_size_verified", "checksum_verified", "contract_version", "delivery_id", "idempotent_replay", "received_byte_size", "received_checksum", "status");
	$actual_ack_fields = array_keys($delivery_ack);
	sort($actual_ack_fields);
	mde2e_assert($expected_ack_fields === $actual_ack_fields, "delivery_ack_fields_invalid", array("expected" => $expected_ack_fields, "actual" => $actual_ack_fields));
	mde2e_assert(
		1 === preg_match("/^mdl_[0-9a-f]{32}$/", (string) ($delivery_ack["delivery_id"] ?? ""))
		&& "media_artifact_delivery_ack.v1" === (string) ($delivery_ack["contract_version"] ?? "")
		&& "acknowledged" === (string) ($delivery_ack["status"] ?? "")
		&& "verified_transfer_only" === (string) ($delivery_ack["acknowledgement_scope"] ?? "")
		&& (string) ($delivery_ack["artifact_id"] ?? "") === (string) $received["artifact_id"]
		&& (int) ($delivery_ack["received_byte_size"] ?? 0) === (int) $received["filesize_bytes"]
		&& (string) ($delivery_ack["received_checksum"] ?? "") === "sha256:" . (string) $received["sha256"]
		&& true === ($delivery_ack["byte_size_verified"] ?? null)
		&& true === ($delivery_ack["checksum_verified"] ?? null)
		&& false === ($delivery_ack["idempotent_replay"] ?? null)
		&& false !== $acknowledged_at_ts
		&& false !== $ack_expires_at_ts
		&& $ack_expires_at_ts > $acknowledged_at_ts
		&& $ack_expires_at_ts === $cloud_expires_at
		&& (string) ($delivery_ack["artifact_expires_at"] ?? "") === (string) ($received["expires_at"] ?? ""),
		"delivery_ack_invalid",
		$delivery_ack
	);
	$expected_transfer_fields = array("ack_deadline_at", "artifact_id", "byte_size_verified", "checksum_verified", "content_type_verified", "contract_version", "delivery_id", "dimensions_verified", "image_decoded", "received_byte_size", "received_checksum");
	$actual_transfer_fields = array_keys($transfer_evidence);
	sort($actual_transfer_fields);
	mde2e_assert($expected_transfer_fields === $actual_transfer_fields, "transfer_evidence_fields_invalid", array("expected" => $expected_transfer_fields, "actual" => $actual_transfer_fields));
	mde2e_assert(
		"media_artifact_verified_transfer.v1" === (string) ($transfer_evidence["contract_version"] ?? "")
		&& (string) ($transfer_evidence["artifact_id"] ?? "") === (string) $received["artifact_id"]
		&& (string) ($transfer_evidence["delivery_id"] ?? "") === (string) $delivery_ack["delivery_id"]
		&& (int) ($transfer_evidence["received_byte_size"] ?? 0) === (int) $received["filesize_bytes"]
		&& (string) ($transfer_evidence["received_checksum"] ?? "") === "sha256:" . (string) $received["sha256"]
		&& true === ($transfer_evidence["byte_size_verified"] ?? null)
		&& true === ($transfer_evidence["checksum_verified"] ?? null)
		&& true === ($transfer_evidence["content_type_verified"] ?? null)
		&& true === ($transfer_evidence["image_decoded"] ?? null)
		&& true === ($transfer_evidence["dimensions_verified"] ?? null)
		&& false !== $ack_deadline_at_ts
		&& $acknowledged_at_ts <= $ack_deadline_at_ts,
		"transfer_evidence_invalid",
		$transfer_evidence
	);
	mde2e_assert_no_remote_artifact_material(array_diff_key($received, array("contents" => true)));

	$media_details_input = array(
		"title" => "Npcink optimized media smoke " . gmdate("c"),
		"alt" => "Optimized media derivative smoke image",
		"caption" => "Reviewed caption for the media derivative E2E smoke.",
		"description" => "Reviewed description for the media derivative E2E smoke.",
		"source_type" => "ai_generated",
	);
	$proposal_payload = npcink_cloud_addon_build_media_derivative_optimization_payload(
		$ability_response,
		$cloud_projection,
		$artifact,
		$media_details_input
	);
	mde2e_assert(!is_wp_error($proposal_payload) && is_array($proposal_payload), "build_proposal_payload", $proposal_payload);
	mde2e_assert(!empty($proposal_payload["proposal_ready"]), "optimization_payload_not_ready", $proposal_payload);
	$from_plan_request = is_array($proposal_payload["from_plan_request"] ?? null) ? $proposal_payload["from_plan_request"] : array();
	$optimization_plan = is_array($from_plan_request["plan"] ?? null) ? $from_plan_request["plan"] : array();
	mde2e_assert("npcink-abilities-toolkit/build-media-optimization-plan" === (string) ($from_plan_request["plan_ability_id"] ?? ""), "optimization_from_plan_missing", $proposal_payload);
	mde2e_assert("media_optimization_plan" === (string) ($optimization_plan["artifact_type"] ?? ""), "optimization_plan_type_invalid", $optimization_plan);
	mde2e_assert(2 === count((array) ($optimization_plan["write_actions"] ?? array())), "optimization_plan_action_count_invalid", $optimization_plan);
	$adopt_input = array();
	foreach ((array) ($optimization_plan["write_actions"] ?? array()) as $write_action) {
		if (is_array($write_action) && "npcink-abilities-toolkit/adopt-cloud-media-derivative" === (string) ($write_action["target_ability_id"] ?? "")) {
			$adopt_input = is_array($write_action["input"] ?? null) ? $write_action["input"] : array();
			break;
		}
	}
	$adopt_artifact = is_array($adopt_input["derivative_artifact"] ?? null) ? $adopt_input["derivative_artifact"] : array();
	$expected_adopt_artifact_fields = array("artifact_id", "expires_at", "filename_basis", "filesize_bytes", "format", "height", "mime_type", "processing_warnings", "sha256", "suggested_filename", "width");
	$actual_adopt_artifact_fields = array_keys($adopt_artifact);
	sort($actual_adopt_artifact_fields);
	mde2e_assert($expected_adopt_artifact_fields === $actual_adopt_artifact_fields, "adopt_artifact_fields_invalid", array("expected" => $expected_adopt_artifact_fields, "actual" => $actual_adopt_artifact_fields));
	mde2e_assert(
		(string) ($adopt_artifact["artifact_id"] ?? "") === (string) $received["artifact_id"]
		&& (string) ($adopt_artifact["sha256"] ?? "") === (string) $received["sha256"]
		&& (string) ($adopt_artifact["suggested_filename"] ?? "") === (string) $artifact["suggested_filename"]
		&& ($adopt_artifact["filename_basis"] ?? null) === ($artifact["filename_basis"] ?? null)
		&& ($adopt_artifact["processing_warnings"] ?? null) === ($artifact["processing_warnings"] ?? null)
		&& !isset($adopt_input["file_name"])
		&& !isset($adopt_input["workflow_metadata"])
		&& !isset($adopt_input["transfer_evidence"])
		&& !isset($adopt_input["delivery_ack"]),
		"adopt_artifact_projection_invalid",
		$adopt_input
	);
	mde2e_assert_no_remote_artifact_material($adopt_input);

	$optimization_proposals = mde2e_proposals_from_plan(
		(string) $from_plan_request["plan_ability_id"],
		$optimization_plan,
		array(
			"attachment_id" => $attachment_id,
			"source_type" => "ai_generated",
		),
		array("external_thread_id" => "media-optimization-e2e-smoke", "trace_id" => $trace_id)
	);
	mde2e_assert(1 === count($optimization_proposals), "optimization_proposal_count_invalid", $optimization_proposals);
	$optimization_proposal_id = mde2e_proposal_id($optimization_proposals[0]);
	mde2e_assert("" !== $optimization_proposal_id, "optimization_proposal_missing_id", $optimization_proposals[0]);
	$optimization_execute = mde2e_execute_proposal($optimization_proposal_id);
	$optimization_audit_events = mde2e_assert_core_proposal_audit($optimization_proposal_id);

	$after_url = wp_get_attachment_url($attachment_id);
	$after_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	$after_path = get_attached_file($attachment_id, true);
	$after_image = is_string($after_path) && is_file($after_path) ? getimagesize($after_path) : false;
	$after_size = is_string($after_path) && is_file($after_path) ? filesize($after_path) : false;
	$after_checksum = is_string($after_path) && is_file($after_path) ? "sha256:" . hash_file("sha256", $after_path) : "";
	$after_metadata = wp_get_attachment_metadata($attachment_id);
	$after_head = wp_remote_head($after_url, array("sslverify" => false, "timeout" => 20));
	$created_relative_files = array_merge(
		$created_relative_files,
		mde2e_attachment_metadata_relative_files(is_array($after_metadata) ? $after_metadata : array())
	);
	$history = get_post_meta($attachment_id, "_npcink_ai_media_file_replacement_history", true);
	$history = is_array($history) ? array_values($history) : array();
	$latest_history = end($history);
	$created_relative_files = array_merge($created_relative_files, mde2e_attachment_history_relative_files($attachment_id));
	mde2e_assert($after_url !== $before_url && $after_rel !== $before_rel && "image/webp" === get_post_mime_type($attachment_id) && count($history) >= 1, "adoption_not_applied", array("before_url" => $before_url, "after_url" => $after_url, "before_rel" => $before_rel, "after_rel" => $after_rel, "mime_type" => get_post_mime_type($attachment_id), "history_count" => count($history)));
	mde2e_assert(false !== $after_size && (int) $after_size === (int) $artifact["filesize_bytes"], "adopted_file_size_mismatch", array("expected" => $artifact["filesize_bytes"], "actual" => $after_size, "path" => $after_path));
	mde2e_assert($after_checksum === (string) $artifact["checksum"], "adopted_file_checksum_mismatch", array("expected" => $artifact["checksum"], "actual" => $after_checksum));
	mde2e_assert(is_array($after_image) && (string) ($after_image["mime"] ?? "") === (string) $artifact["mime_type"] && (int) ($after_image[0] ?? 0) === (int) $artifact["width"] && (int) ($after_image[1] ?? 0) === (int) $artifact["height"], "adopted_file_image_facts_mismatch", array("artifact" => $artifact, "image" => $after_image));
	mde2e_assert(is_array($after_metadata) && (int) ($after_metadata["width"] ?? 0) === (int) $artifact["width"] && (int) ($after_metadata["height"] ?? 0) === (int) $artifact["height"] && (string) ($after_metadata["file"] ?? "") === $after_rel, "attachment_metadata_facts_mismatch", array("artifact" => $artifact, "metadata" => $after_metadata));
	mde2e_assert(!is_wp_error($after_head) && 200 === (int) wp_remote_retrieve_response_code($after_head) && "image/webp" === (string) wp_remote_retrieve_header($after_head, "content-type"), "adopted_file_http_delivery_failed", array("url" => $after_url, "response" => $after_head));
	$attachment_post = get_post($attachment_id);
	mde2e_assert($attachment_post && $media_details_input["title"] === $attachment_post->post_title, "metadata_title_not_applied", array("post" => $attachment_post));
	mde2e_assert($media_details_input["caption"] === $attachment_post->post_excerpt, "metadata_caption_not_applied", array("post_excerpt" => $attachment_post ? $attachment_post->post_excerpt : ""));
	mde2e_assert($media_details_input["description"] === $attachment_post->post_content, "metadata_description_not_applied", array("post_content" => $attachment_post ? $attachment_post->post_content : ""));
	mde2e_assert($media_details_input["alt"] === get_post_meta($attachment_id, "_wp_attachment_image_alt", true), "metadata_alt_not_applied", get_post_meta($attachment_id));
	mde2e_assert($media_details_input["source_type"] === get_post_meta($attachment_id, "_npcink_ai_media_source_type", true), "metadata_source_type_not_applied", get_post_meta($attachment_id));

	$content_plan_input = array("attachment_id" => $attachment_id, "max_posts" => 20, "max_replacements_per_post" => 20);
	$content_plan_envelope = mde2e_run_governed_read_ability(
		"npcink-abilities-toolkit/build-media-reference-repair-plan",
		$content_plan_input,
		"Build the bounded content reference repair plan for this smoke attachment."
	);
	mde2e_assert($content_plan_envelope["ok"], "content_reference_plan", $content_plan_envelope);
	$content_plan = (array) ($content_plan_envelope["data"]["result"]["data"] ?? $content_plan_envelope["data"]["data"] ?? array());
	$content_proposals = array();
	if ((int) ($content_plan["action_count"] ?? 0) >= 1) {
		$content_proposals = mde2e_proposals_from_plan("npcink-abilities-toolkit/build-media-reference-repair-plan", $content_plan, $content_plan_input);
		foreach ($content_proposals as $proposal) {
			mde2e_execute_proposal((string) ($proposal["proposal_id"] ?? ""));
		}
	}
	$page_body = (string) get_post_field("post_content", $page_id);
	mde2e_assert(false === strpos($page_body, $before_url) && false !== strpos($page_body, $after_url), "content_reference_repair_not_applied", array("post_content" => $page_body, "repair_plan" => $content_plan));
	$page_http = wp_remote_get(get_permalink($page_id), array("sslverify" => false, "timeout" => 20));
	$page_body_http = is_wp_error($page_http) ? "" : (string) wp_remote_retrieve_body($page_http);
	mde2e_assert(!is_wp_error($page_http) && 200 === (int) wp_remote_retrieve_response_code($page_http) && false !== strpos($page_body_http, $after_url), "page_http_reference_repair_not_visible", array("url" => get_permalink($page_id), "response" => $page_http));

	$option_name = "npcink_ai_e2e_media_derivative_option_" . $stamp;
	$theme_mod_name = "npcink_ai_e2e_media_derivative_theme_mod_" . $stamp;
	$created_option_names[] = $option_name;
	$created_theme_mod_names[] = $theme_mod_name;
	update_option($option_name, array("hero" => array("image" => $before_url)), false);
	set_theme_mod($theme_mod_name, $before_url);
	add_filter("npcink_abilities_toolkit_patchable_setting_targets", "mde2e_patchable_setting_targets", 10, 3);
	$settings_plan_input = array(
		"attachment_id" => $attachment_id,
		"option_names" => array($option_name),
		"theme_mod_names" => array($theme_mod_name),
		"include_theme_mods" => true,
		"max_settings" => 20,
		"max_replacements_per_setting" => 20,
		"excluded_formats" => array("svg", "gif", "ico", "pdf"),
		"min_width" => 64,
		"min_height" => 64,
	);
	$settings_plan_envelope = mde2e_run_governed_read_ability(
		"npcink-abilities-toolkit/build-media-settings-reference-repair-plan",
		$settings_plan_input,
		"Build the bounded settings reference repair plan for this smoke attachment."
	);
	mde2e_assert($settings_plan_envelope["ok"], "settings_reference_plan", $settings_plan_envelope);
	$settings_plan = (array) ($settings_plan_envelope["data"]["result"]["data"] ?? $settings_plan_envelope["data"]["data"] ?? array());
	mde2e_assert((int) ($settings_plan["action_count"] ?? 0) >= 2, "settings_reference_plan_incomplete", $settings_plan);
	$settings_proposals = mde2e_proposals_from_plan("npcink-abilities-toolkit/build-media-settings-reference-repair-plan", $settings_plan, $settings_plan_input);
	foreach ($settings_proposals as $proposal) {
		mde2e_execute_proposal((string) ($proposal["proposal_id"] ?? ""));
	}
	remove_filter("npcink_abilities_toolkit_patchable_setting_targets", "mde2e_patchable_setting_targets", 10);
	$option_json = wp_json_encode(get_option($option_name), JSON_UNESCAPED_SLASHES);
	$theme_mod_value = (string) get_theme_mod($theme_mod_name);
	mde2e_assert(false === strpos($option_json, $before_url) && false !== strpos($option_json, $after_url) && false === strpos($theme_mod_value, $before_url) && false !== strpos($theme_mod_value, $after_url), "settings_reference_repair_not_applied", array("option" => get_option($option_name), "theme_mod" => $theme_mod_value));

	$replacement_id = is_array($latest_history) ? (string) ($latest_history["replacement_id"] ?? "") : "";
	mde2e_assert("" !== $replacement_id, "rollback_replacement_id_missing", $history);
	list($rollback_proposal_id, $rollback_proposal) = mde2e_create_proposal(
		"npcink-abilities-toolkit/restore-media-backup",
		array(
			"attachment_id" => $attachment_id,
			"backup_id" => $replacement_id,
			"expected_current_relative_file" => $after_rel,
			"expected_current_mime_type" => "image/webp",
			"target_conflict_mode" => "overwrite",
			"dry_run" => true,
			"commit" => false,
			"idempotency_key" => "media-restore-" . $replacement_id,
		),
		array("source" => array("type" => "media_derivative_e2e_restore"), "backup_id" => $replacement_id),
		"Rollback media derivative smoke",
		"Smoke proposal for media derivative backup restore.",
		array("external_thread_id" => "media-derivative-e2e-smoke", "trace_id" => $trace_id)
	);
	$rollback_execute = mde2e_execute_proposal($rollback_proposal_id);
	$rollback_audit_events = mde2e_assert_core_proposal_audit($rollback_proposal_id);
	$rollback_url = wp_get_attachment_url($attachment_id);
	$rollback_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	$rollback_path = get_attached_file($attachment_id, true);
	$rollback_image = is_string($rollback_path) && is_file($rollback_path) ? getimagesize($rollback_path) : false;
	$rollback_checksum = is_string($rollback_path) && is_file($rollback_path) ? "sha256:" . hash_file("sha256", $rollback_path) : "";
	mde2e_assert($rollback_url !== $after_url && $rollback_rel === $before_rel && "image/png" === get_post_mime_type($attachment_id), "rollback_not_applied", array("rollback_url" => $rollback_url, "after_url" => $after_url, "before_rel" => $before_rel, "rollback_rel" => $rollback_rel, "mime_type" => get_post_mime_type($attachment_id)));
	mde2e_assert(is_array($rollback_image) && "image/png" === (string) ($rollback_image["mime"] ?? "") && (int) ($rollback_image[0] ?? 0) === (int) ($before_image[0] ?? 0) && (int) ($rollback_image[1] ?? 0) === (int) ($before_image[1] ?? 0) && $rollback_checksum === $before_checksum, "rollback_file_facts_mismatch", array("before" => $before_image, "rollback" => $rollback_image));
	$created_relative_files = array_merge(
		$created_relative_files,
		mde2e_attachment_metadata_relative_files((array) wp_get_attachment_metadata($attachment_id)),
		mde2e_attachment_history_relative_files($attachment_id)
	);

	echo wp_json_encode(
		array(
			"success" => true,
			"cleanup" => $cleanup,
			"attachment_id" => (int) $attachment_id,
			"page_id" => (int) $page_id,
			"run_id" => $run_id,
			"artifact_id" => (string) ($artifact["artifact_id"] ?? ""),
			"receive_delivery_id" => (string) ($delivery_ack["delivery_id"] ?? ""),
			"optimization_proposal_id" => $optimization_proposal_id,
			"optimization_audit_events" => $optimization_audit_events,
			"optimization_write_action_count" => count((array) ($optimization_plan["write_actions"] ?? array())),
			"batch_plan" => array(
				"candidate_count" => count($batch_candidates),
				"batch_size_recommendation" => $batch_size_recommendation,
				"cloud_request_input_ready" => !empty($batch_cloud_input),
			),
			"metadata_updated" => true,
			"file_replaced" => true,
			"rollback_proposal_id" => $rollback_proposal_id,
			"rollback_audit_events" => $rollback_audit_events,
			"content_reference_proposal_count" => count($content_proposals),
			"settings_reference_proposal_count" => count($settings_proposals),
			"read_authorization_evidence" => $read_authorization_evidence,
			"source" => array("url" => $before_url, "relative_file" => $before_rel, "mime_type" => "image/png"),
			"local_adoption" => array(
				"url" => $after_url,
				"relative_file" => $after_rel,
				"mime_type" => "image/webp",
				"head_code" => is_wp_error($after_head) ? 0 : (int) wp_remote_retrieve_response_code($after_head),
				"head_content_type" => is_wp_error($after_head) ? "" : (string) wp_remote_retrieve_header($after_head, "content-type"),
			),
			"rollback" => array("url" => $rollback_url, "relative_file" => $rollback_rel, "mime_type" => get_post_mime_type($attachment_id)),
			"page_display_after_reference_repair" => array(
				"http_code" => is_wp_error($page_http) ? 0 : (int) wp_remote_retrieve_response_code($page_http),
				"contains_derivative_url" => false !== strpos($page_body_http, $after_url),
			),
			"rollback_history_count" => count(get_post_meta($attachment_id, "_npcink_ai_media_file_replacement_history", true) ?: array()),
			"stale_smoke_cleanup" => $stale_cleanup,
		),
		JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
	) . "\n";
} catch (Throwable $e) {
	$mde2e_failure_json = $e->getMessage();
} finally {
	remove_filter("npcink_abilities_toolkit_patchable_setting_targets", "mde2e_patchable_setting_targets", 10);
	if ($cleanup) {
		foreach ($created_pages as $page_id) {
			wp_delete_post((int) $page_id, true);
		}
		if ($created_attachment_id > 0) {
			wp_delete_attachment($created_attachment_id, true);
		}
		foreach ($created_option_names as $option_name) {
			delete_option($option_name);
		}
		foreach ($created_theme_mod_names as $theme_mod_name) {
			remove_theme_mod($theme_mod_name);
		}
		foreach (array_unique(array_filter($created_relative_files)) as $relative_file) {
			$created_relative_files = array_merge($created_relative_files, mde2e_related_generated_relative_files($relative_file));
		}
		$created_relative_files = array_values(array_unique(array_filter($created_relative_files)));
		foreach ($created_relative_files as $relative_file) {
			mde2e_unlink_upload($relative_file);
		}
		global $wpdb;
		$execution_records = get_option("npcink_openclaw_adapter_execution_records", array());
		$execution_records = is_array($execution_records) ? $execution_records : array();
		foreach (array_keys($created_proposal_ids) as $proposal_id) {
			unset($execution_records[md5($proposal_id)]);
			$wpdb->delete($wpdb->prefix . "npcink_governance_core_audit_log", array("proposal_id" => $proposal_id), array("%s"));
			$wpdb->delete($wpdb->prefix . "npcink_governance_core_proposals", array("proposal_id" => $proposal_id), array("%s"));
		}
		foreach (array_keys($created_read_request_ids) as $read_request_id) {
			$wpdb->delete($wpdb->prefix . "npcink_governance_core_audit_log", array("proposal_id" => $read_request_id), array("%s"));
			$wpdb->delete($wpdb->prefix . "npcink_governance_core_read_requests", array("request_id" => $read_request_id), array("%s"));
		}
		update_option("npcink_openclaw_adapter_execution_records", $execution_records, false);
		mde2e_cleanup_stale_smoke_media();
	}
}

if ($cleanup) {
	try {
		mde2e_assert_no_smoke_media_leaks();
		foreach ($created_pages as $page_id) {
			mde2e_assert(null === get_post((int) $page_id), "cleanup_page_leak_guard", array("page_id" => $page_id));
		}
		foreach ($created_option_names as $option_name) {
			mde2e_assert(null === get_option($option_name, null), "cleanup_option_leak_guard", array("option_name" => $option_name));
		}
		foreach ($created_theme_mod_names as $theme_mod_name) {
			mde2e_assert(null === get_theme_mod($theme_mod_name, null), "cleanup_theme_mod_leak_guard", array("theme_mod_name" => $theme_mod_name));
		}
		$remaining_execution_records = get_option("npcink_openclaw_adapter_execution_records", array());
		$remaining_execution_records = is_array($remaining_execution_records) ? $remaining_execution_records : array();
		foreach (array_keys($created_proposal_ids) as $proposal_id) {
			$proposal_count = (int) $wpdb->get_var($wpdb->prepare("select count(*) from {$wpdb->prefix}npcink_governance_core_proposals where proposal_id = %s", $proposal_id));
			$audit_count = (int) $wpdb->get_var($wpdb->prepare("select count(*) from {$wpdb->prefix}npcink_governance_core_audit_log where proposal_id = %s", $proposal_id));
			mde2e_assert(0 === $proposal_count && 0 === $audit_count && !isset($remaining_execution_records[md5($proposal_id)]), "cleanup_governance_leak_guard", array(
				"proposal_id" => $proposal_id,
				"proposal_count" => $proposal_count,
				"audit_count" => $audit_count,
			));
		}
		foreach (array_keys($created_read_request_ids) as $read_request_id) {
			$read_request_count = (int) $wpdb->get_var($wpdb->prepare("select count(*) from {$wpdb->prefix}npcink_governance_core_read_requests where request_id = %s", $read_request_id));
			$audit_count = (int) $wpdb->get_var($wpdb->prepare("select count(*) from {$wpdb->prefix}npcink_governance_core_audit_log where proposal_id = %s", $read_request_id));
			mde2e_assert(0 === $read_request_count && 0 === $audit_count, "cleanup_read_authorization_leak_guard", array(
				"read_request_id" => $read_request_id,
				"read_request_count" => $read_request_count,
				"audit_count" => $audit_count,
			));
		}
		$uploads = wp_upload_dir();
		foreach (array_unique(array_filter($created_relative_files)) as $relative_file) {
			$cleanup_path = trailingslashit((string) ($uploads["basedir"] ?? "")) . ltrim((string) $relative_file, "/");
			mde2e_assert(!is_file($cleanup_path), "cleanup_file_leak_guard", array("relative_file" => $relative_file));
		}
	} catch (Throwable $e) {
		$mde2e_failure_json = $e->getMessage();
	}
}

if ("" !== $mde2e_failure_json) {
	echo $mde2e_failure_json . "\n";
	exit(1);
}
')"
SMOKE_STATUS=$?
set -e
echo "${SMOKE_JSON}"
if [ "${SMOKE_STATUS}" -ne 0 ]; then
	exit "${SMOKE_STATUS}"
fi

if ! command -v docker >/dev/null 2>&1; then
	fail "Docker is required for Cloud evidence checks"
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
	fail "Cloud PostgreSQL container is not running: ${POSTGRES_CONTAINER}"
fi

RUN_ID="$(NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON="${SMOKE_JSON}" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON"])["run_id"])
PY
)"
ARTIFACT_ID="$(NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON="${SMOKE_JSON}" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON"])["artifact_id"])
PY
)"
RECEIVE_DELIVERY_ID="$(NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON="${SMOKE_JSON}" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["NPCINK_MEDIA_DERIVATIVE_E2E_SMOKE_JSON"])["receive_delivery_id"])
PY
)"
if [ "${#RUN_ID}" -gt 191 ] || [[ ! "${RUN_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9_.:-]*$ ]]; then
	fail "Refusing Cloud SQL with invalid run id"
fi
if [[ ! "${ARTIFACT_ID}" =~ ^art_[0-9a-f]{32}$ ]]; then
	fail "Refusing Cloud SQL with invalid artifact id"
fi
if [[ ! "${RECEIVE_DELIVERY_ID}" =~ ^mdl_[0-9a-f]{32}$ ]]; then
	fail "Refusing Cloud SQL with invalid receive delivery id"
fi

echo "== Cloud media derivative telemetry =="
METRIC_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_derivative_job_metrics m join media_artifacts a on a.artifact_id=m.artifact_id and a.run_id=m.run_id where m.run_id='${RUN_ID}' and m.status='succeeded' and m.artifact_id='${ARTIFACT_ID}' and m.output_bytes=a.byte_size and m.output_width=a.width and m.output_height=a.height and m.output_format=a.format;")"
ARTIFACT_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_artifacts where run_id='${RUN_ID}' and artifact_id='${ARTIFACT_ID}' and operation='image.transform.v1' and status='available' and purged_at is null and expires_at > now() and expires_at <= now() + interval '60 minutes' and byte_size > 0 and width > 0 and height > 0 and content_type='image/webp' and checksum ~ '^sha256:[0-9a-f]{64}$';")"
RUN_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from run_records where run_id='${RUN_ID}' and status='succeeded' and execution_kind='media_derivative' and result_json->>'contract_version'='media_derivative_result.v1' and result_json->'artifact'->>'artifact_id'='${ARTIFACT_ID}';")"
UPLOAD_JOB_CHAIN_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from run_records job join media_derivative_job_metrics metric on metric.run_id=job.run_id and metric.site_id=job.site_id join run_records upload on upload.trace_id=job.trace_id and upload.site_id=job.site_id join media_artifacts source on source.run_id=upload.run_id and source.site_id=upload.site_id where job.run_id='${RUN_ID}' and job.contract_version='media_job_request.v1' and job.execution_kind='media_derivative' and job.status='succeeded' and upload.contract_version='media_upload_request.v1' and upload.execution_kind='media_upload' and upload.status='succeeded' and upload.input_json->'request'->>'request_contract_version'='media_upload_request.v1' and source.operation='image.upload.v1' and source.status='available' and metric.source_bytes=source.byte_size and metric.source_width=source.width and metric.source_height=source.height;")"
USAGE_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from usage_meter_events where run_id='${RUN_ID}' and event_kind='run' and meter_key='runs' and quantity=1;")"
DELIVERY_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_artifact_deliveries d join media_artifacts a on a.artifact_id=d.artifact_id and a.site_id=d.site_id where a.run_id='${RUN_ID}' and d.artifact_id='${ARTIFACT_ID}';")"
VERIFIED_DELIVERY_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_artifact_deliveries d join media_artifacts a on a.artifact_id=d.artifact_id and a.site_id=d.site_id where a.run_id='${RUN_ID}' and d.artifact_id='${ARTIFACT_ID}' and d.delivery_id ~ '^mdl_[0-9a-f]{32}$' and d.started_at is not null and d.completed_at is not null and d.acked_at is not null and d.revoked_at is null and d.completed_at >= d.started_at and d.acked_at >= d.completed_at and d.acked_at <= d.ack_deadline_at and d.expected_byte_size=a.byte_size and d.completed_byte_size=d.expected_byte_size and d.received_byte_size=d.expected_byte_size and d.expected_checksum=a.checksum and d.completed_checksum=d.expected_checksum and d.received_checksum=d.expected_checksum and d.byte_size_verified is true and d.checksum_verified is true;")"
RECEIVE_DELIVERY_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_artifact_deliveries d join media_artifacts a on a.artifact_id=d.artifact_id and a.site_id=d.site_id where a.run_id='${RUN_ID}' and d.artifact_id='${ARTIFACT_ID}' and d.delivery_id='${RECEIVE_DELIVERY_ID}' and d.started_at is not null and d.completed_at is not null and d.acked_at is not null and d.revoked_at is null and d.acked_at <= d.ack_deadline_at and d.received_byte_size=a.byte_size and d.received_checksum=a.checksum and d.byte_size_verified is true and d.checksum_verified is true;")"
if [ "${METRIC_COUNT}" != "1" ]; then
	fail "Expected one succeeded media_derivative_job_metrics row for ${RUN_ID}/${ARTIFACT_ID}; got ${METRIC_COUNT}"
fi
if [ "${ARTIFACT_COUNT}" != "1" ]; then
	fail "Expected one available short-TTL media_artifacts row for ${RUN_ID}/${ARTIFACT_ID}; got ${ARTIFACT_COUNT}"
fi
if [ "${RUN_COUNT}" != "1" ]; then
	fail "Expected one succeeded artifact-only run row for ${RUN_ID}/${ARTIFACT_ID}; got ${RUN_COUNT}"
fi
if [ "${UPLOAD_JOB_CHAIN_COUNT}" != "1" ]; then
	fail "Expected one media_upload_request.v1 to media_job_request.v1 chain for ${RUN_ID}; got ${UPLOAD_JOB_CHAIN_COUNT}"
fi
if [ "${USAGE_COUNT}" != "1" ]; then
	fail "Expected one run usage event for ${RUN_ID}; got ${USAGE_COUNT}"
fi
if [ "${DELIVERY_COUNT}" -lt 2 ]; then
	fail "Expected explicit receive and governed adoption deliveries for ${RUN_ID}/${ARTIFACT_ID}; got ${DELIVERY_COUNT}"
fi
if [ "${VERIFIED_DELIVERY_COUNT}" != "${DELIVERY_COUNT}" ]; then
	fail "Expected every delivery for ${RUN_ID}/${ARTIFACT_ID} to be ACKed without anomaly; total ${DELIVERY_COUNT}, verified ${VERIFIED_DELIVERY_COUNT}"
fi
if [ "${RECEIVE_DELIVERY_COUNT}" != "1" ]; then
	fail "Expected the local receive delivery ${RECEIVE_DELIVERY_ID} to have exact ACK evidence; got ${RECEIVE_DELIVERY_COUNT}"
fi
echo "[ok] Addon upload to media job Cloud evidence is present"
echo "[ok] Cloud run, artifact, metric, and usage evidence rows are present"
echo "[ok] Artifact TTL is short and still live"
echo "[ok] Explicit receive and governed adoption deliveries are started, completed, ACKed before deadline, exact-integrity verified, and transfer-only"
echo "[info] Runbook: docs/media-derivative-operations-runbook-v1.md"
