#!/usr/bin/env bash

set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  scripts/publish-pr.sh --title TITLE --body-file PATH [--base BRANCH] [--dry-run]

Publishes the current clean topic branch, creates a pull request from a
completed body contract, and requests squash auto-merge after required checks.
EOF
}

fail() {
	echo "[pr-publish] error: $*" >&2
	exit 1
}

quote_command() {
	printf '[pr-publish] would run:'
	printf ' %q' "$@"
	printf '\n'
}

title=''
body_file=''
base_branch='master'
dry_run=0
invocation_dir="${PWD}"

while [ "$#" -gt 0 ]; do
	case "$1" in
		--)
			shift
			;;
		--title)
			[ "$#" -ge 2 ] || fail '--title requires a value'
			title="$2"
			shift 2
			;;
		--body-file)
			[ "$#" -ge 2 ] || fail '--body-file requires a value'
			body_file="$2"
			shift 2
			;;
		--base)
			[ "$#" -ge 2 ] || fail '--base requires a value'
			base_branch="$2"
			shift 2
			;;
		--dry-run)
			dry_run=1
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			fail "unknown argument: $1"
			;;
	esac
done

[ -n "${title}" ] || fail '--title is required'
[ -n "${body_file}" ] || fail '--body-file is required'

command -v git >/dev/null 2>&1 || fail 'git is required'
command -v gh >/dev/null 2>&1 || fail 'GitHub CLI (gh) is required'

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail 'run inside a Git worktree'
cd "${repo_root}"

case "${body_file}" in
	/*) body_path="${body_file}" ;;
	*) body_path="${invocation_dir}/${body_file}" ;;
esac

[ -f "${body_path}" ] || fail "body file not found: ${body_path}"

for required_heading in Scope Boundary Verification Risk; do
	grep -Eiq "^#{1,6}[[:space:]]+.*${required_heading}" "${body_path}" \
		|| fail "body file is missing the ${required_heading} heading"
done

if [ "${base_branch}" = 'production' ]; then
	grep -Fq 'Approved for production validation by operator.' "${body_path}" \
		|| fail 'production PR body is missing operator approval'
fi

branch="$(git branch --show-current)"
[ -n "${branch}" ] || fail 'detached HEAD is not publishable'
[ "${branch}" != "${base_branch}" ] || fail "refusing to publish the base branch: ${base_branch}"

[ -z "$(git status --porcelain)" ] || fail 'worktree must be clean before publishing'

git fetch origin "${base_branch}"
git rev-parse --verify "origin/${base_branch}" >/dev/null 2>&1 \
	|| fail "origin/${base_branch} is unavailable"
git merge-base --is-ancestor "origin/${base_branch}" HEAD \
	|| fail "branch must include the latest origin/${base_branch}"

commit_count="$(git rev-list --count "origin/${base_branch}..HEAD")"
[ "${commit_count}" -gt 0 ] || fail "branch has no commits beyond origin/${base_branch}"

head_sha="$(git rev-parse HEAD)"

if [ "${dry_run}" = '1' ]; then
	quote_command git push -u origin "${branch}"
	quote_command gh pr create --base "${base_branch}" --head "${branch}" --title "${title}" --body-file "${body_path}"
	quote_command gh pr merge '<created-pr-url>' --auto --squash --match-head-commit "${head_sha}"
	echo '[pr-publish] dry-run passed'
	exit 0
fi

existing_pr="$(
	gh pr list \
		--state open \
		--head "${branch}" \
		--json url \
		--jq '.[0].url // empty'
)"
[ -z "${existing_pr}" ] || fail "an open pull request already exists: ${existing_pr}"

git push -u origin "${branch}"
pr_url="$(
	gh pr create \
		--base "${base_branch}" \
		--head "${branch}" \
		--title "${title}" \
		--body-file "${body_path}"
)"

gh pr merge "${pr_url}" --auto --squash --match-head-commit "${head_sha}"

echo "[pr-publish] pull_request=${pr_url}"
echo '[pr-publish] auto_merge=squash_requested'
