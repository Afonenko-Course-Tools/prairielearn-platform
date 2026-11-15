#!/usr/bin/env bash
# Отрицательные контроли работают только в копии собственных файлов.
set -euo pipefail
cd "$(dirname "$0")/../.."
control_source=$PWD
control_tmp=$(mktemp -d)
trap 'rm -rf "$control_tmp"' EXIT
git ls-files --cached --others --exclude-standard -z >"$control_tmp/files"
mkdir "$control_tmp/repo"
while IFS= read -r -d '' control_file; do
	[[ -L "$control_file" ]] && continue
	case "/$control_file/" in */node_modules/* | */.git/*) continue ;; esac
	mkdir -p "$control_tmp/repo/$(dirname "$control_file")"
	cp "$control_file" "$control_tmp/repo/$control_file"
done <"$control_tmp/files"
ln -s "$control_source/node_modules" "$control_tmp/repo/node_modules"
cd "$control_tmp/repo"
git init -q
control_failure() {
	local expected=$1
	local status
	set +e
	tools/check-quality.sh >"$control_tmp/log" 2>&1
	status=$?
	set -e
	if [[ $status == 0 ]] || ! grep -Eq "$expected" "$control_tmp/log"; then
		cat "$control_tmp/log"
		printf 'Контроль не подтвердил отказ: %s (exit %s)\n' "$expected" "$status" >&2
		exit 1
	fi
	printf 'PASS %s exit=%s\n' "$expected" "$status"
}
mkdir newly_owned
printf 'def broken() -> int:\n    return "wrong"\n' >newly_owned/own.py
control_failure 'reportReturnType|not assignable|cannot be assigned'
rm newly_owned/own.py
printf 'import hashlib\n\ndef digest(value: bytes) -> str:\n    return hashlib.md5(value).hexdigest()\n' >newly_owned/production.py
ruff format newly_owned/production.py >/dev/null
control_failure 'B324'
rm newly_owned/production.py
printf '/** @type {number} */\nexport const value = "wrong";\n' >newly_owned/own.js
control_failure 'TS2322'
rm newly_owned/own.js
printf 'enabled: yes\n' >newly_owned/warning.yml
control_failure 'truthy'
rm newly_owned/warning.yml
printf 'FROM scratch\nINVALID_INSTRUCTION value\n' >Dockerfile.new
control_failure 'unexpected|DL1000'
rm Dockerfile.new
printf 'SELECT a.id FROM foo AS a JOIN bar AS a ON a.id = a.id;\n' >newly_owned/own.sql
control_failure 'AL04'
rm newly_owned/own.sql
printf 'int main(void) {\n  int *p = 0;\n  return *p;\n}\n' >newly_owned/own.c
control_failure 'clang-analyzer-core.NullDereference'
rm newly_owned/own.c
cat >ansible/new.yml <<'YAML'
- name: Synthetic control
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Run synthetic command
      ansible.builtin.shell: echo control
YAML
control_failure 'command-instead-of-shell|no-changed-when'
rm ansible/new.yml
mkdir newly_owned/module
cat >newly_owned/module/main.tf <<'HCL'
terraform {
  required_version = ">= 1.13.0"
}
variable "unused" {
  type = string
}
HCL
tofu -chdir=newly_owned/module fmt >/dev/null
control_failure 'terraform_unused_declarations'
rm -r newly_owned/module
cat >newly_owned/NewBug.java <<'JAVA'
package synthetic;

public final class NewBug {
    public static void fail() {
        new IllegalStateException("synthetic control");
    }
}
JAVA
control_failure 'RV_EXCEPTION_NOT_THROWN'
rm newly_owned/NewBug.java
# Сбой исполняемого файла не должен становиться успешным gate.
mkdir "$control_tmp/bin"
printf '#!/bin/sh\nexit 42\n' >"$control_tmp/bin/jq"
chmod +x "$control_tmp/bin/jq"
set +e
PATH="$control_tmp/bin:$PATH" tools/check-quality.sh >"$control_tmp/tool-failure" 2>&1
control_status=$?
set -e
[[ $control_status == 42 ]]
printf 'PASS tool failure exit=%s\n' "$control_status"
