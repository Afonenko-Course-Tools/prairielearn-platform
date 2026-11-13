#!/usr/bin/env bash
# Только локальный статический анализ; никаких install, VM, DB, daemon или grading.
set -euo pipefail
cd "$(dirname "$0")/.."
quality_tmp=$(mktemp -d)
trap 'rm -rf "$quality_tmp"' EXIT
git ls-files --cached --others --exclude-standard -z >"$quality_tmp/files"
shell_files=()
yaml_files=()
c_files=()
java_files=()
java_runtime_files=()
docker_files=()
sql_files=()
ansible_files=()
toml_files=()
declare -A terraform_dirs=()
while IFS= read -r -d '' file; do
	if [[ -L "$file" ]]; then continue; fi
	case "/$file/" in
	*/node_modules/* | */fixtures/* | */upstream/* | */native-upstream/* | */.git/*) continue ;;
	esac
	case "$file" in
	ansible/*.yml | ansible/*.yaml | examples/course-cd/*.yml | examples/course-cd/*.yaml) ansible_files+=("$file") ;;
	esac
	case "$file" in
	*.sh) shell_files+=("$file") ;;
	*.yml | *.yaml) yaml_files+=("$file") ;;
	*.c | *.cc | *.cpp) c_files+=("$file") ;;
	*.java)
		java_files+=("$file")
		case "$file" in experiments/*) ;; *) java_runtime_files+=("$file") ;; esac
		;;
	*.dockerignore) ;;
	Dockerfile | Dockerfile.* | */Dockerfile | */Dockerfile.*) docker_files+=("$file") ;;
	*.tf) terraform_dirs["$(dirname "$file")"]=1 ;;
	*.sql) sql_files+=("$file") ;;
	*.toml) toml_files+=("$file") ;;
	*.json) jq -e -s 'length == 1' "$file" >/dev/null ;;
	*.xml) xmllint --nonet --noout "$file" ;;
	esac
done <"$quality_tmp/files"
ruff check .
ruff format --check .
pyright --pythonpath "$(command -v python3)"
npm run typecheck
npm run format:check
bandit -q -r tests -x tests/fixtures -t B301,B307,B501,B506,B602,B605
bandit -q -r . -x ./tests,./node_modules,./runtime/java25-junit-v1/upstream
if ((${#shell_files[@]})); then
	shellcheck "${shell_files[@]}"
	shfmt -d "${shell_files[@]}"
fi
if ((${#yaml_files[@]})); then yamllint --strict "${yaml_files[@]}"; fi
actionlint
if ((${#ansible_files[@]})); then ansible-lint --offline --strict "${ansible_files[@]}"; fi
if ((${#docker_files[@]})); then hadolint "${docker_files[@]}"; fi
if ((${#c_files[@]})); then
	clang-format --dry-run --Werror "${c_files[@]}"
	for file in "${c_files[@]}"; do clang-tidy -quiet "$file" -- -std=gnu11; done
fi
if ((${#java_files[@]})); then if [[ -n ${JAVA_FORMAT_JAR:-} ]]; then
	java -jar "$JAVA_FORMAT_JAR" --aosp --dry-run --set-exit-if-changed "${java_files[@]}"
else
	google-java-format --aosp --dry-run --set-exit-if-changed "${java_files[@]}"
fi; fi
for terraform_dir in "${!terraform_dirs[@]}"; do
	tofu -chdir="$terraform_dir" fmt -check -diff
	tflint --chdir "$terraform_dir" --config "$PWD/.tflint.hcl"
	# Provider schema — только в копии собственных входов, без backend/state/plan/apply.
	terraform_copy=$(mktemp -d "$quality_tmp/tofu-XXXXXX")
	while IFS= read -r -d '' file; do
		if [[ -L "$file" ]]; then continue; fi
		case "/$file/" in */node_modules/* | */fixtures/* | */upstream/* | */native-upstream/* | */.git/*) continue ;; esac
		if [[ "$terraform_dir" == . ]]; then
			terraform_relative="$file"
		elif [[ "$file" == "$terraform_dir/"* ]]; then
			terraform_relative="${file#"$terraform_dir/"}"
		else
			continue
		fi
		mkdir -p "$terraform_copy/$(dirname "$terraform_relative")"
		cp "$file" "$terraform_copy/$terraform_relative"
	done <"$quality_tmp/files"
	TF_DATA_DIR="$terraform_copy/.terraform" tofu -chdir="$terraform_copy" init -backend=false -input=false -no-color
	TF_DATA_DIR="$terraform_copy/.terraform" tofu -chdir="$terraform_copy" validate -json >"$quality_tmp/tofu-validate.json"
	cat "$quality_tmp/tofu-validate.json"
	jq -e '(.valid == true) and (.error_count == 0) and (.warning_count == 0)' "$quality_tmp/tofu-validate.json" >/dev/null
done
if ((${#java_runtime_files[@]})); then tools/quality/java.sh "${java_runtime_files[@]}"; fi
if ((${#sql_files[@]})); then
	sqlfluff lint "${sql_files[@]}"
	sqlfluff lint --rules layout,capitalisation "${sql_files[@]}"
fi
if ((${#toml_files[@]})); then
	taplo lint --no-schema "${toml_files[@]}"
	taplo format --check "${toml_files[@]}"
fi
