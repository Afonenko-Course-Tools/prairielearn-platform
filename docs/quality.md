# Проверки качества Platform

`tools/check-quality.sh` выполняет штатные CLI и возвращает ошибку при замечании
или сбое инструмента. Установка зависимостей в эту команду не входит. Можно также вызвать
`npm run quality` и `npm run quality:controls`. CI запускает
тот же gate в официальном Arch Linux image; функциональные контракты остаются
в отдельном Ubuntu job. Используется настоящий JDK 25 и `--release 25`.

Python: Ruff E4/E7/E9/F/B и форматирование, Pyright strict по всему дереву.
TypeScript Compiler API: существующий `npm run typecheck`; включены новые
`.mjs`, `.js`, `.cjs`, `.ts`, `.mts`, `.cts` в любом собственном каталоге.
Prettier отвечает за MJS, рабочий JSON и YAML; архивные JSON проверяются как
JSON без переписывания исторических свидетельств. Чужие schemas/native-upstream
и runtime upstream не форматируются. Намеренно некорректные fixtures исключены
из общего gate; их ожидаемое отклонение проверяют существующие функциональные
тесты. `git ls-files --cached --others --exclude-standard` включает новые
неигнорируемые собственные файлы; зависимости, fixtures, upstream и symlinks
не обходятся.

ShellCheck, shfmt, yamllint --strict, actionlint, ansible-lint --offline --strict,
Hadolint, clang-format и широкий clang-tidy анализируют все обнаруженные входы
своего языка. SQLFluff PostgreSQL проверяет AL04/AM08/ST03 и форматирование.
OpenTofu fmt, TFLint recommended и provider schema validate выполняются для
обнаруженных модулей: init всегда `-backend=false`, только в временной копии
собственных входов. State, tfvars, VM, plan, apply, DB и Docker daemon не нужны.
Compose проверяется отдельно штатным `docker compose config --quiet` с
синтетическими переменными и пустым env-file; overlays соединяются с base.

Служебный Java компилируется с `-Xlint:all -Werror`, затем проверяется стандартными
SpotBugs (`-effort:max -low`, все приоритеты) и Error Prone. Experiments имеют отдельные одноимённые модули и
остаются входами форматирования, их доверенные producers/consumers проверены
синтетически; они не компилируются вместе как один runtime. Upstream annotation
попадает только в auxclasspath. Полный SpotBugs отчёт обязан иметь errors=0 и
missingClasses=0. `result()` использует тот же monitor, что callbacks JUnit:
это явная гарантия видимости, без утверждения о воспроизведённой ранее гонке.
Единственное исключение EI_EXPOSE_REP2 ограничено `testPlanExecutionStarted`:
живой TestPlan принадлежит lifecycle JUnit и нужен для dynamic tests.

Подготовка Java анализаторов использует обычные Maven profiles:

```bash
mvn -B -q -f tools/quality/pom.xml -Pspotbugs dependency:build-classpath -Dmdep.outputFile=/tmp/platform-spotbugs-classpath
mvn -B -q -f tools/quality/pom.xml -Perrorprone dependency:build-classpath -Dmdep.outputFile=/tmp/platform-errorprone-classpath
export SPOTBUGS_CLASSPATH="$(cat /tmp/platform-spotbugs-classpath)"
export ERROR_PRONE_CLASSPATH="$(cat /tmp/platform-errorprone-classpath)"
tools/check-quality.sh
```

Это devDependencies проверки служебного кода; student build и условия заданий
не изменяются. `requirements-dev.txt` и package.json используют штатные package
managers. Собственного установщика и дополнительной матрицы lock-версий нет.

## Рассмотренные контексты Bandit

Блокирующий профиль B301/B307/B501/B506/B602/B605 проходит по всему собственному
Python. Полный стандартный профиль также блокирует весь собственный production Python,
включая tools/runtime/images/experiments и новые каталоги, кроме tests; каждая
точная оговорка находится возле соответствующей строки. `--ignore-nosec` audit
остаётся видимым в CI, ошибки анализа и коды кроме 0/1 отклоняются. Он содержит
46 рассмотренных сигналов и не является baseline для новых предупреждений.
Новые строки не наследуют оговорки.

B404: импорт subprocess нужен компонентам, назначение которых — запуск argv.
B603: вызовы передают явные argv без shell, с существующими границами путей,
timeout/containment по назначению компонента. B607: Git/Docker/curl берутся из
операторского PATH согласно AGENTS.md; это зависимость установленной среды,
не доказательство shell injection. B108: `/tmp` — cwd/base directory,
а не фиксированное имя создаваемого файла. B102: загружаются доверенные
`supervisor.py` runtime bundle и tests/checks.py; student fish исполняется
отдельным ограниченным процессом. Происхождение trusted tests остаётся
операторской границей. B101 заменён явным отказом при отсутствии import loader. Ещё 140 asserts
экспериментальных runners/consumers стали явными if/raise AssertionError:
проверки полноты и self-checks теперь не исчезают при python -O.

| Точная строка полного audit | Правило |
| --- | --- |
| `experiments/c3-feedback-f0-v2/run.py:10` | B404 |
| `experiments/c3-feedback-f0-v2/run.py:56` | B603 |
| `experiments/c3-feedback-f0/run.py:10` | B404 |
| `experiments/c3-feedback-f0/run.py:161` | B603 |
| `experiments/c3-feedback-state-timeout/run.py:9` | B404 |
| `experiments/c3-feedback-state-timeout/run.py:54` | B603 |
| `images/fish-git-grader/grade.py:161` | B102 |
| `images/fish-git-grader/grade.py:205` | B102 |
| `images/java25-grader/grade.py:22` | B404 |
| `images/java25-grader/grade.py:358` | B108 |
| `images/java25-grader/grade.py:493` | B108 |
| `images/java25-grader/grade.py:533` | B603 |
| `images/java25-grader/grade.py:1933` | B108 |
| `images/java25-grader/grade.py:1943` | B108 |
| `images/sp-git-workspace/sp-git-workspace-init.py:8` | B404 |
| `images/sp-git-workspace/sp-git-workspace-init.py:105` | B607 |
| `images/sp-git-workspace/sp-git-workspace-init.py:105` | B603 |
| `runtime/fish-git-v1/supervisor.py:8` | B404 |
| `runtime/fish-git-v1/supervisor.py:50` | B603 |
| `tools/build-course.py:10` | B404 |
| `tools/build-course.py:228` | B603 |
| `tools/delivery4.py:9` | B404 |
| `tools/delivery4.py:464` | B607 |
| `tools/delivery4.py:464` | B603 |
| `tools/dev-tls.py:22` | B404 |
| `tools/dev-tls.py:87` | B603 |
| `tools/grading_job.py:15` | B404 |
| `tools/grading_job.py:811` | B607 |
| `tools/grading_job.py:811` | B603 |
| `tools/grading_job.py:921` | B603 |
| `tools/grading_job.py:1130` | B607 |
| `tools/grading_job.py:1130` | B603 |
| `tools/proxmox-preflight.py:9` | B404 |
| `tools/proxmox-preflight.py:115` | B607 |
| `tools/proxmox-preflight.py:115` | B603 |
| `tools/publish-metadata.py:8` | B404 |
| `tools/publish-metadata.py:59` | B607 |
| `tools/publish-metadata.py:59` | B603 |
| `tools/stage_courses.py:9` | B404 |
| `tools/stage_courses.py:84` | B607 |
| `tools/stage_courses.py:84` | B603 |
| `tools/vendor-native-schemas.py:5` | B404 |
| `tools/vendor-native-schemas.py:24` | B607 |
| `tools/vendor-native-schemas.py:24` | B603 |
| `tools/vendor-native-schemas.py:32` | B607 |
| `tools/vendor-native-schemas.py:32` | B603 |

Два B506 в тестах используют `yaml.BaseLoader`, который создаёт строки и
коллекции, без Python object constructors; это сохраняет workflow `on` строкой.
Точные исключения находятся у вызовов. Bandit 1.9.4 дополнительно печатает
`nosec encountered ... but no failed test` при повторном обходе дочерних AST
nodes и при ограниченном профиле. Эти сообщения подтверждены на строках,
для которых полный `--ignore-nosec` audit действительно даёт соответствующий
код; они не означают пропущенный finding. Конфигурация Bandit не отключает
глобальные diagnostics. Ansible core 2.22 при discovery чужих callback plugins
сообщает о deprecated `oneline` и `tree`; собственные playbooks их не выбирают.
Ansible production profile проходит без findings; notices стороннего пакета
оставлены видимыми.

Точные NOLINT C ограничены `_GNU_SOURCE` glibc, намеренным syscall injection
include в fixture, bounded libc calls без поддержки Annex K в glibc и argv
`execvp`, являющимся назначением sandbox wrapper. Signed masks оформлены
явными unsigned значениями, тестовый CLI использует проверяемый strtol.
Ruff E402 ограничены bootstrap sys.path перед импортами; B023 — синхронными
mock callbacks, потребляемыми до следующей итерации цикла.

Низкоприоритетный SpotBugs также блокирует gate: четыре общих `throws Exception`
заменены точными IOException/ParseException/Mismatch/MalformedURLException;
plan проверяется requireNonNull в точках чтения lifecycle. Эти правки не меняют
сигнатуры обязательного учебного API и поведение допустимых JUnit событий.

`tools/quality/controls.sh` создаёт временную копию, проверяет новые root/helper
Python (тип и B324 вне узкого профиля), JS, warning-level YAML, Dockerfile.new,
SQL, C null dereference, новый Ansible playbook, Terraform unused declaration,
Java forgotten exception и exit 42 инструмента.
Каждый контроль обязан получить ненулевой exit и ожидаемый diagnostic.
Никакой unsafe fixture не исполняется. Перед запуском нужны те же инструменты
и Java classpaths, что для основного gate.

Hadolint в CI берётся из официального [release v2.15.1](https://github.com/hadolint/hadolint/releases/tag/v2.15.1),
проверяется `checksums.sha256` того же release. GJF — обычный Maven artifact
`com.google.googlejavaformat:google-java-format:2.0.0:jar:all-deps`, соответствующий
[официальному release 2.0.0](https://github.com/google/google-java-format/releases/tag/v2.0.0).
В CLI допустим системный `google-java-format`; CI явно передаёт `JAVA_FORMAT_JAR`
и запускает тот же официальный formatter через `java -jar`. AUR не используется.
