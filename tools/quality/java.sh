#!/usr/bin/env bash
# Анализ только собственного служебного Java bytecode; upstream annotation — auxclasspath.
set -euo pipefail
: "${SPOTBUGS_CLASSPATH:?Подготовьте профиль spotbugs из tools/quality/pom.xml}"
: "${ERROR_PRONE_CLASSPATH:?Подготовьте профиль errorprone из tools/quality/pom.xml}"
java_quality_tmp=$(mktemp -d)
trap 'rm -rf "$java_quality_tmp"' EXIT
mkdir "$java_quality_tmp/aux" "$java_quality_tmp/classes" "$java_quality_tmp/ep"
javac -J-XX:ActiveProcessorCount=2 --release 25 -g -d "$java_quality_tmp/aux" runtime/java25-junit-v1/upstream/org/prairielearn/autograder/AutograderInfo.java
java_quality_cp="runtime/java25-junit-v1/junit-platform-console-standalone-1.14.1.jar:runtime/java25-junit-v1/json-simple-1.1.1.jar:$java_quality_tmp/aux"
javac -J-XX:ActiveProcessorCount=2 --release 25 -g -Xlint:all -Werror -cp "$java_quality_cp" -d "$java_quality_tmp/classes" "$@"
set +e
java -XX:ActiveProcessorCount=2 -Xmx512m -cp "$SPOTBUGS_CLASSPATH" edu.umd.cs.findbugs.LaunchAppropriateUI -textui -effort:max -low -exitcode -exclude tools/quality/spotbugs-exclude.xml -auxclasspath "$java_quality_cp" -xml:withMessages="$java_quality_tmp/spotbugs.xml" "$java_quality_tmp/classes"
spotbugs_status=$?
set -e
cat "$java_quality_tmp/spotbugs.xml"
if [[ $spotbugs_status != 0 ]]; then exit "$spotbugs_status"; fi
xmllint --nonet --xpath 'boolean(/BugCollection/Errors[@errors="0" and @missingClasses="0"])' "$java_quality_tmp/spotbugs.xml" | grep -Fx true
errorprone_flags=()
for java_package in api file main model parser processing tree util; do
	errorprone_flags+=("-J--add-exports=jdk.compiler/com.sun.tools.javac.$java_package=ALL-UNNAMED")
done
for java_package in code comp; do
	errorprone_flags+=("-J--add-opens=jdk.compiler/com.sun.tools.javac.$java_package=ALL-UNNAMED")
done
javac -J-XX:ActiveProcessorCount=2 -J-Xmx512m "${errorprone_flags[@]}" --release 25 -XDcompilePolicy=simple --should-stop=ifError=FLOW -processorpath "$ERROR_PRONE_CLASSPATH" '-Xplugin:ErrorProne' -Werror -cp "$java_quality_cp" -d "$java_quality_tmp/ep" "$@"
