#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PHP_BIN="${MAGICK_WP_PHP:-php}"
WP_PATH="${MAGICK_WP_PATH:-$HOME/Local Sites/magick-ai/app/public}"
MYSQL_SOCKET="${MAGICK_WP_MYSQL_SOCKET:-$HOME/Library/Application Support/Local/run/NPb24Zg9g/mysql/mysqld.sock}"
API_CONTAINER="${MAGICK_CLOUD_API_CONTAINER:-magick-ai-cloud-api-1}"
WORKER_CONTAINER="${MAGICK_CLOUD_WORKER_CONTAINER:-magick-ai-cloud-worker-1}"
POSTGRES_CONTAINER="${MAGICK_CLOUD_POSTGRES_CONTAINER:-magick-ai-cloud-postgres-1}"
POSTGRES_USER="${MAGICK_CLOUD_POSTGRES_USER:-magick}"
POSTGRES_DB="${MAGICK_CLOUD_POSTGRES_DB:-magick_ai_cloud}"
RUN_MIGRATIONS="${MAGICK_MEDIA_DERIVATIVE_E2E_RUN_MIGRATIONS:-1}"
RESTART_WORKER="${MAGICK_MEDIA_DERIVATIVE_E2E_RESTART_WORKER:-1}"
CLEANUP="${MAGICK_MEDIA_DERIVATIVE_E2E_CLEANUP:-1}"

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

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "${API_CONTAINER}"; then
	if [ "${RUN_MIGRATIONS}" = "1" ]; then
		echo "== Cloud migrations =="
		docker exec "${API_CONTAINER}" alembic upgrade head
	fi
	if [ "${RESTART_WORKER}" = "1" ] && docker ps --format '{{.Names}}' | grep -qx "${WORKER_CONTAINER}"; then
		echo "== Restart Cloud runtime worker =="
		docker restart "${WORKER_CONTAINER}" >/dev/null
	fi
fi

echo "== WordPress media derivative E2E smoke =="
cd "${WP_PATH}"
SMOKE_JSON="$(MAGICK_MEDIA_DERIVATIVE_E2E_CLEANUP="${CLEANUP}" "${PHP_BIN}" \
	-d error_reporting=8191 \
	-d "mysqli.default_socket=${MYSQL_SOCKET}" \
	-d "pdo_mysql.default_socket=${MYSQL_SOCKET}" \
	-r '
require "wp-load.php";
wp_set_current_user(1);
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

function mde2e_fail($stage, $data) {
	echo wp_json_encode(
		array(
			"success" => false,
			"failed_stage" => $stage,
			"data" => $data,
		),
		JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
	) . "\n";
	exit(1);
}

function mde2e_assert($condition, $stage, $data) {
	if (!$condition) {
		mde2e_fail($stage, $data);
	}
}

function mde2e_create_proposal($ability_id, array $input, array $preview, $title, $summary, array $caller) {
	$proposal = mde2e_rest("POST", "/magick-ai-adapter/v1/proposals", array(
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
	return array($proposal_id, $proposal);
}

function mde2e_execute_proposal($proposal_id) {
	$execute = mde2e_rest("POST", "/magick-ai-adapter/v1/proposals/" . rawurlencode($proposal_id) . "/approve-and-execute");
	mde2e_assert($execute["ok"] && 200 === (int) ($execute["status"] ?? 0) && !empty($execute["data"]["success"]), "approve_and_execute", array("proposal_id" => $proposal_id, "execute" => $execute));
	return $execute;
}

function mde2e_proposals_from_plan($plan_ability_id, array $plan, array $plan_input, array $caller = array()) {
	$request = array(
		"plan_ability_id" => $plan_ability_id,
		"plan" => $plan,
		"plan_input" => $plan_input,
	);
	if (!empty($caller)) {
		$request["caller"] = $caller;
	}
	$bridge = mde2e_rest("POST", "/magick-ai-adapter/v1/proposals/from-plan", $request);
	mde2e_assert($bridge["ok"] && in_array((int) ($bridge["status"] ?? 0), array(200, 201), true), "proposals_from_plan", array("plan_ability_id" => $plan_ability_id, "bridge" => $bridge));
	if (isset($bridge["data"]["proposals"]) && is_array($bridge["data"]["proposals"])) {
		return array_values(array_filter($bridge["data"]["proposals"], "is_array"));
	}
	if (isset($bridge["data"]["proposal"]) && is_array($bridge["data"]["proposal"])) {
		return array($bridge["data"]["proposal"]);
	}
	if (isset($bridge["data"]["proposal_id"])) {
		return array($bridge["data"]);
	}
	return array();
}

function mde2e_proposal_id(array $proposal) {
	return (string) ($proposal["proposal_id"] ?? "");
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

$cleanup = "1" === (string) getenv("MAGICK_MEDIA_DERIVATIVE_E2E_CLEANUP");
$created_pages = array();
$created_attachment_id = 0;
$created_option_names = array();
$created_theme_mod_names = array();
$created_relative_files = array();

try {
	$upload = wp_upload_dir();
	$dir = trailingslashit($upload["path"]);
	if (!is_dir($dir)) {
		wp_mkdir_p($dir);
	}

	$stamp = gmdate("YmdHis");
	$filename = "magick-ai-e2e-media-derivative-" . $stamp . ".png";
	$path = $dir . $filename;
	$image = imagecreatetruecolor(800, 450);
	$bg = imagecolorallocate($image, 60, 70, 85);
	$panel = imagecolorallocate($image, 250, 250, 250);
	$accent = imagecolorallocate($image, 96, 165, 250);
	$text = imagecolorallocate($image, 20, 30, 45);
	imagefilledrectangle($image, 0, 0, 799, 449, $bg);
	imagefilledrectangle($image, 70, 80, 730, 370, $panel);
	imagefilledellipse($image, 400, 225, 260, 170, $accent);
	imagestring($image, 5, 265, 212, "Magick AI Media Smoke", $text);
	imagepng($image, $path);
	imagedestroy($image);

	$filetype = wp_check_filetype($filename, null);
	$attachment_id = wp_insert_attachment(array(
		"post_mime_type" => $filetype["type"] ?: "image/png",
		"post_title" => "Magick AI media derivative smoke " . gmdate("c"),
		"post_status" => "inherit",
	), $path);
	require_once ABSPATH . "wp-admin/includes/image.php";
	wp_update_attachment_metadata($attachment_id, wp_generate_attachment_metadata($attachment_id, $path));
	$created_attachment_id = (int) $attachment_id;

	$before_url = wp_get_attachment_url($attachment_id);
	$before_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	$created_relative_files[] = $before_rel;
	$page_id = wp_insert_post(array(
		"post_title" => "Magick AI media derivative smoke page " . gmdate("c"),
		"post_status" => "publish",
		"post_type" => "page",
		"post_content" => "<figure class=\"wp-block-image\"><img src=\"" . esc_url($before_url) . "\" class=\"wp-image-" . (int) $attachment_id . "\" alt=\"smoke\" /></figure>",
	));
	$created_pages[] = (int) $page_id;

	$trace_id = "wp-media-derivative-e2e-" . $attachment_id;
	$create = mde2e_rest("POST", "/magick-ai-adapter/v1/media-derivative-runs", array(
		"attachment_id" => $attachment_id,
		"target_format" => "webp",
		"max_width" => 320,
		"quality" => 80,
		"trace_id" => $trace_id,
		"idempotency_key" => "wp-media-derivative-e2e-" . $attachment_id . "-" . time(),
	));
	mde2e_assert($create["ok"] && 202 === (int) ($create["status"] ?? 0), "create_preview", $create);
	$run_id = (string) ($create["data"]["run_id"] ?? "");
	mde2e_assert("" !== $run_id, "create_preview_missing_run_id", $create);

	$status = array();
	for ($i = 0; $i < 40; $i++) {
		usleep(0 === $i ? 250000 : 750000);
		$status = mde2e_rest("GET", "/magick-ai-adapter/v1/media-derivative-runs/" . rawurlencode($run_id), array("trace_id" => $trace_id));
		$state = (string) ($status["data"]["cloud_run"]["status"] ?? "");
		if (in_array($state, array("succeeded", "completed", "failed"), true)) {
			break;
		}
	}

	$result = mde2e_rest("GET", "/magick-ai-adapter/v1/media-derivative-runs/" . rawurlencode($run_id) . "/result", array("trace_id" => $trace_id));
	mde2e_assert($result["ok"], "poll_result", array("status" => $status, "result" => $result));
	$cloud_result = (array) ($result["data"]["cloud_result"] ?? array());
	mde2e_assert(in_array((string) ($cloud_result["status"] ?? ""), array("succeeded", "completed"), true), "cloud_result_not_success", array("status" => $status, "result" => $result));
	$artifact = (array) ($cloud_result["derivative"] ?? array());
	mde2e_assert("" !== (string) ($artifact["artifact_id"] ?? ""), "missing_artifact", $result);

	$preview_url = (string) ($artifact["preview_url"] ?? "");
	$preview_http = "" !== $preview_url ? wp_remote_get($preview_url, array("sslverify" => false, "timeout" => 20)) : null;
	$preview_code = is_wp_error($preview_http) ? 0 : (int) wp_remote_retrieve_response_code($preview_http);
	$preview_type = is_wp_error($preview_http) ? "" : (string) wp_remote_retrieve_header($preview_http, "content-type");
	mde2e_assert(200 === $preview_code && false !== strpos($preview_type, "image/webp"), "signed_preview_failed", array("preview_url_present" => "" !== $preview_url, "http_code" => $preview_code, "content_type" => $preview_type));

	$media_details_input = array(
		"title" => "Magick AI optimized media smoke " . gmdate("c"),
		"alt" => "Optimized media derivative smoke image",
		"caption" => "Reviewed caption for the media derivative E2E smoke.",
		"description" => "Reviewed description for the media derivative E2E smoke.",
		"source_type" => "ai_generated",
	);
	$proposal_payload = mde2e_rest("POST", "/magick-ai-adapter/v1/media-derivative-proposal-payload", array(
		"ability_response" => (array) ($create["data"]["ability_response"] ?? array()),
		"cloud_result" => $cloud_result,
		"derivative_artifact" => $artifact,
		"media_details_input" => $media_details_input,
	));
	mde2e_assert($proposal_payload["ok"] && 200 === (int) ($proposal_payload["status"] ?? 0), "build_proposal_payload", $proposal_payload);
	mde2e_assert(!empty($proposal_payload["data"]["proposal_ready"]), "optimization_payload_not_ready", $proposal_payload);
	$from_plan_request = is_array($proposal_payload["data"]["from_plan_request"] ?? null) ? $proposal_payload["data"]["from_plan_request"] : array();
	$optimization_plan = is_array($from_plan_request["plan"] ?? null) ? $from_plan_request["plan"] : array();
	mde2e_assert("magick-ai/build-media-optimization-plan" === (string) ($from_plan_request["plan_ability_id"] ?? ""), "optimization_from_plan_missing", $proposal_payload);
	mde2e_assert("media_optimization_plan" === (string) ($optimization_plan["artifact_type"] ?? ""), "optimization_plan_type_invalid", $optimization_plan);
	mde2e_assert(2 === count((array) ($optimization_plan["write_actions"] ?? array())), "optimization_plan_action_count_invalid", $optimization_plan);

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

	$after_url = wp_get_attachment_url($attachment_id);
	$after_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	$created_relative_files[] = $after_rel;
	$history = get_post_meta($attachment_id, "_magick_ai_media_file_replacement_history", true);
	$history = is_array($history) ? array_values($history) : array();
	$latest_history = end($history);
	if (is_array($latest_history)) {
		$created_relative_files[] = (string) ($latest_history["backup"]["relative_file"] ?? "");
	}
	mde2e_assert($after_url !== $before_url && "image/webp" === get_post_mime_type($attachment_id) && count($history) >= 1, "adoption_not_applied", array("before_url" => $before_url, "after_url" => $after_url, "mime_type" => get_post_mime_type($attachment_id), "history_count" => count($history)));
	$attachment_post = get_post($attachment_id);
	mde2e_assert($attachment_post && $media_details_input["title"] === $attachment_post->post_title, "metadata_title_not_applied", array("post" => $attachment_post));
	mde2e_assert($media_details_input["caption"] === $attachment_post->post_excerpt, "metadata_caption_not_applied", array("post_excerpt" => $attachment_post ? $attachment_post->post_excerpt : ""));
	mde2e_assert($media_details_input["description"] === $attachment_post->post_content, "metadata_description_not_applied", array("post_content" => $attachment_post ? $attachment_post->post_content : ""));
	mde2e_assert($media_details_input["alt"] === get_post_meta($attachment_id, "_wp_attachment_image_alt", true), "metadata_alt_not_applied", get_post_meta($attachment_id));
	mde2e_assert($media_details_input["source_type"] === get_post_meta($attachment_id, "_magick_ai_media_source_type", true), "metadata_source_type_not_applied", get_post_meta($attachment_id));

	$content_plan_input = array("attachment_id" => $attachment_id, "max_posts" => 20, "max_replacements_per_post" => 20);
	$content_plan_envelope = mde2e_rest("POST", "/magick-ai-adapter/v1/run-read-ability", array(
		"ability_id" => "magick-ai/build-media-reference-repair-plan",
		"input" => $content_plan_input,
	));
	mde2e_assert($content_plan_envelope["ok"], "content_reference_plan", $content_plan_envelope);
	$content_plan = (array) ($content_plan_envelope["data"]["result"]["data"] ?? $content_plan_envelope["data"]["data"] ?? array());
	mde2e_assert((int) ($content_plan["action_count"] ?? 0) >= 1, "content_reference_plan_empty", $content_plan);
	$content_proposals = mde2e_proposals_from_plan("magick-ai/build-media-reference-repair-plan", $content_plan, $content_plan_input);
	foreach ($content_proposals as $proposal) {
		mde2e_execute_proposal((string) ($proposal["proposal_id"] ?? ""));
	}
	$page_body = (string) get_post_field("post_content", $page_id);
	mde2e_assert(false === strpos($page_body, $before_url) && false !== strpos($page_body, $after_url), "content_reference_repair_not_applied", array("post_content" => $page_body));

	$option_name = "magick_ai_e2e_media_derivative_option_" . $stamp;
	$theme_mod_name = "magick_ai_e2e_media_derivative_theme_mod_" . $stamp;
	$created_option_names[] = $option_name;
	$created_theme_mod_names[] = $theme_mod_name;
	update_option($option_name, array("hero" => array("image" => $before_url)), false);
	set_theme_mod($theme_mod_name, $before_url);
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
	$settings_plan_envelope = mde2e_rest("POST", "/magick-ai-adapter/v1/run-read-ability", array(
		"ability_id" => "magick-ai/build-media-settings-reference-repair-plan",
		"input" => $settings_plan_input,
	));
	mde2e_assert($settings_plan_envelope["ok"], "settings_reference_plan", $settings_plan_envelope);
	$settings_plan = (array) ($settings_plan_envelope["data"]["result"]["data"] ?? $settings_plan_envelope["data"]["data"] ?? array());
	mde2e_assert((int) ($settings_plan["action_count"] ?? 0) >= 2, "settings_reference_plan_incomplete", $settings_plan);
	$settings_proposals = mde2e_proposals_from_plan("magick-ai/build-media-settings-reference-repair-plan", $settings_plan, $settings_plan_input);
	foreach ($settings_proposals as $proposal) {
		mde2e_execute_proposal((string) ($proposal["proposal_id"] ?? ""));
	}
	$option_json = wp_json_encode(get_option($option_name), JSON_UNESCAPED_SLASHES);
	$theme_mod_value = (string) get_theme_mod($theme_mod_name);
	mde2e_assert(false === strpos($option_json, $before_url) && false !== strpos($option_json, $after_url) && false === strpos($theme_mod_value, $before_url) && false !== strpos($theme_mod_value, $after_url), "settings_reference_repair_not_applied", array("option" => get_option($option_name), "theme_mod" => $theme_mod_value));

	$replacement_id = is_array($latest_history) ? (string) ($latest_history["replacement_id"] ?? "") : "";
	mde2e_assert("" !== $replacement_id, "rollback_replacement_id_missing", $history);
	list($rollback_proposal_id, $rollback_proposal) = mde2e_create_proposal(
		"magick-ai/replace-media-file",
		array(
			"attachment_id" => $attachment_id,
			"mode" => "rollback",
			"replacement_id" => $replacement_id,
			"dry_run" => true,
			"commit" => false,
			"idempotency_key" => "media-rollback-" . $replacement_id,
		),
		array("source" => array("type" => "media_derivative_e2e_rollback"), "replacement_id" => $replacement_id),
		"Rollback media derivative smoke",
		"Smoke proposal for media derivative rollback.",
		array("external_thread_id" => "media-derivative-e2e-smoke", "trace_id" => $trace_id)
	);
	$rollback_execute = mde2e_execute_proposal($rollback_proposal_id);
	$rollback_url = wp_get_attachment_url($attachment_id);
	$rollback_rel = (string) get_post_meta($attachment_id, "_wp_attached_file", true);
	mde2e_assert($rollback_url !== $after_url && "image/png" === get_post_mime_type($attachment_id), "rollback_not_applied", array("rollback_url" => $rollback_url, "after_url" => $after_url, "mime_type" => get_post_mime_type($attachment_id)));
	$created_relative_files[] = $rollback_rel;

	$page_http = wp_remote_get(get_permalink($page_id), array("sslverify" => false, "timeout" => 20));
	$after_head = wp_remote_head($after_url, array("sslverify" => false, "timeout" => 20));

	echo wp_json_encode(
		array(
			"success" => true,
			"cleanup" => $cleanup,
			"attachment_id" => (int) $attachment_id,
			"page_id" => (int) $page_id,
			"run_id" => $run_id,
			"artifact_id" => (string) ($artifact["artifact_id"] ?? ""),
			"optimization_proposal_id" => $optimization_proposal_id,
			"optimization_write_action_count" => count((array) ($optimization_plan["write_actions"] ?? array())),
			"metadata_updated" => true,
			"file_replaced" => true,
			"rollback_proposal_id" => $rollback_proposal_id,
			"content_reference_proposal_count" => count($content_proposals),
			"settings_reference_proposal_count" => count($settings_proposals),
			"source" => array("url" => $before_url, "relative_file" => $before_rel, "mime_type" => "image/png"),
			"derivative" => array(
				"url" => $after_url,
				"relative_file" => $after_rel,
				"mime_type" => "image/webp",
				"head_code" => is_wp_error($after_head) ? 0 : (int) wp_remote_retrieve_response_code($after_head),
				"head_content_type" => is_wp_error($after_head) ? "" : (string) wp_remote_retrieve_header($after_head, "content-type"),
			),
			"rollback" => array("url" => $rollback_url, "relative_file" => $rollback_rel, "mime_type" => get_post_mime_type($attachment_id)),
			"page_display_after_reference_repair" => array(
				"http_code" => is_wp_error($page_http) ? 0 : (int) wp_remote_retrieve_response_code($page_http),
				"contains_derivative_url" => false !== strpos(is_wp_error($page_http) ? "" : (string) wp_remote_retrieve_body($page_http), $after_url),
			),
			"rollback_history_count" => count(get_post_meta($attachment_id, "_magick_ai_media_file_replacement_history", true) ?: array()),
		),
		JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
	) . "\n";
} finally {
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
			mde2e_unlink_upload($relative_file);
		}
	}
}
')"
echo "${SMOKE_JSON}"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
	RUN_ID="$(SMOKE_JSON="${SMOKE_JSON}" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["SMOKE_JSON"])["run_id"])
PY
)"
	ARTIFACT_ID="$(SMOKE_JSON="${SMOKE_JSON}" python3 - <<'PY'
import json
import os

print(json.loads(os.environ["SMOKE_JSON"])["artifact_id"])
PY
)"
	echo "== Cloud media derivative telemetry =="
	METRIC_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_derivative_job_metrics where run_id='${RUN_ID}' and status='succeeded' and artifact_id='${ARTIFACT_ID}' and artifact_download_count >= 1;")"
	ARTIFACT_COUNT="$(docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At -c "select count(*) from media_derivative_artifacts where run_id='${RUN_ID}' and artifact_id='${ARTIFACT_ID}' and purged_at is null and expires_at > now() and expires_at <= now() + interval '60 minutes';")"
	if [ "${METRIC_COUNT}" != "1" ]; then
		fail "Expected one succeeded media_derivative_job_metrics row for ${RUN_ID}/${ARTIFACT_ID}; got ${METRIC_COUNT}"
	fi
	if [ "${ARTIFACT_COUNT}" != "1" ]; then
		fail "Expected one live short-TTL media_derivative_artifacts row for ${RUN_ID}/${ARTIFACT_ID}; got ${ARTIFACT_COUNT}"
	fi
	echo "[ok] Cloud artifact and bounded telemetry rows are present"
	echo "[ok] Artifact TTL is short and still live"
	echo "[info] Runbook: docs/media-derivative-operations-runbook-v1.md"
fi
