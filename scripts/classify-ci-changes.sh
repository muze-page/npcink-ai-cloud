#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
	printf '%s\n' \
		'deploy_required=true' \
		'static_terms_only=false' \
		'docs_only=false'
	exit 0
fi

deploy_required=false
static_terms_only=true
docs_only=true

for changed_file in "$@"; do
	case "${changed_file}" in
		site/terms/*)
			deploy_required=true
			docs_only=false
			;;
		.github/workflows/ci.yml|.github/workflows/deploy-production.yml|docker-compose*.yml|Dockerfile*|*/Dockerfile*|deploy/*.sh)
			deploy_required=true
			static_terms_only=false
			docs_only=false
			;;
		docs/*.md|docs/**/*.md|deploy/*.md|.github/*.md|.github/**/*.md|README.md|AGENTS.md|CONTRIBUTING.md|SECURITY.md)
			static_terms_only=false
			;;
		.github/*|.github/**/*|docs/*|docs/**/*|tests/*|tests/**/*|deploy/RELEASE_CHECKLIST.md)
			static_terms_only=false
			docs_only=false
			;;
		*)
			deploy_required=true
			static_terms_only=false
			docs_only=false
			;;
	esac
done

printf 'deploy_required=%s\n' "${deploy_required}"
printf 'static_terms_only=%s\n' "${static_terms_only}"
printf 'docs_only=%s\n' "${docs_only}"
