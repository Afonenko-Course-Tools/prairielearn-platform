# Пилот на Proxmox

Платформа обслуживает несколько native-курсов в одной VM. Проверенный стенд:
Ubuntu Server 26.04.1 LTS, 4 vCPU, 8 GiB RAM и диск 60 GiB. Новая VM имеет
отдельный state OpenTofu; существующие VM и конфигурации QCL-NEGF не изменяются.
Для пилота до десяти одновременных пользователей резервное копирование не входит
в согласованную область работы.

Cloud image закреплён в `tofu/main.tf`: сборка `release-20260927`, SHA-256
`8800651811af9a85465ad1d552add729947bb16488dddb4a9b5305a3d97332b2`.
Перед новой установкой следует проверить актуальный стабильный Ubuntu и подпись
его checksum-манифеста, затем согласованно заменить URL и checksum.

## Подготовка

1. Создать приватный каталог вне Git для tfvars, state, inventory, ключей,
   конфигураций Gateway/PL и TLS. Не копировать весь профиль другого проекта.
   `tools/proxmox-preflight.py` читает только необходимые параметры профиля:
   API token передаётся curl через stdin, CA используется для проверки TLS.
2. Проверить свободный VMID, assigned RAM с резервом 4 GiB, загрузку CPU,
   место на выбранном storage и bridge. Отдельно проверить IP через ARP DAD.
   Повторная проверка уже созданного VMID не является повторной admission новой VM.
3. Инициализировать OpenTofu с отдельным приватным backend/state; проверить plan:
   изменения относятся только к собственной VM, image и cloud-init snippet.
   `prevent_destroy` защищает VM/image. Bootstrap snippet после первого запуска
   неизменяем; последующие изменения гостя выполняет Ansible.
   `overwrite: false` сохраняет уже загруженный image и исключает повторную
   проверку доступности временного bootstrap URL при последующих plan.
4. Установить соответствующий приватному SSH ключу публичный ключ. Проверить
   host key через доверенный канал. Не принимать неизвестный host key автоматически.
5. Подготовить server certificate с SAN внутреннего IP и доверенный собственный
   CA. Закрытый ключ CA остаётся на компьютере оператора; VM получает только
   server key/certificate и открытый CA certificate.

Пример проверки ресурсов:

```sh
python3 tools/proxmox-preflight.py --profile /absolute/private/profile \
  --vm-id 200 --memory-gib 8 --disk-gib 60 --output /absolute/private/preflight.json
tofu -chdir=tofu init
tofu -chdir=tofu plan -var-file=/absolute/private/production.tfvars.json
```

Примеры переменных: `tofu/terraform.tfvars.example` и
`ansible/inventory.example.yml`. TLS verification отключать не требуется.
Если исходящие соединения Proxmox/VM недоступны, оператор может передать
проверенный cloud image и Docker archive через собственный ограниченный relay.
Это транспорт тех же проверенных байтов, а не изменение сетей других проектов.

## Размещение

`compose/compose.prod.yml` открывает только HTTPS на IP VM. PL работает в
production с `devMode: false`, `hasShib: true`, `cookieDomain: null` для IP
и новым `databaseEncryptionKey`. Native path root задаётся `coursesRoot: /course`.
Gateway использует постоянные SQLite файлы; PostgreSQL хранится в Docker volume.
Ключи, roster, SQLite и runtime configuration в Git не помещаются.

Дерево курсов содержит неизменяемые версии:

```text
/srv/prairielearn/courses/
  java/<deliveryHash>/
  system-practice/<deliveryHash>/
```

Один parent directory монтируется readonly в PL как `/course`, а в Gateway как
`/native`. Для непривилегированного Gateway native directories доступны на чтение
и обход (0755/0644); приватные runtime directories сохраняют отдельные права.
`pl_course_source` в inventory содержит это дерево, `pl_course_dir` — его parent.

Ansible устанавливает Docker/Compose из официального repository и classic image
store: одинаковые config image IDs сохраняются после `docker save/load`.
Установка выполняется с exact images, уже проверенными на исходном компьютере.
`pl_image_ids` должен перечислять PL, Gateway, nginx и **все** grader images;
offline archive должен содержать каждый отсутствующий image.

```sh
ansible-playbook -i /absolute/private/inventory.yml ansible/site.yml --check
ansible-playbook -i /absolute/private/inventory.yml ansible/site.yml
```

Изменение runtime files требует перечитать конфигурации: Ansible делает
`up -d --force-recreate` при материальных изменениях. PostgreSQL/SQLite volumes
и старые snapshots сохраняются. Systemd включает запуск после reboot.
Docker socket предоставлен только PL для запуска grader containers; ответ
студента выполняется в ограниченном grader без socket и сети. На уровне PL
одновременно выполняются максимум два локальных grader job по 512 MiB.

## Обновление одного курса

1. Экспортировать и проверить выбранный курс; его UUID и source course ID должны
   сохраняться. Создать новый каталог `<id>/<newDeliveryHash>`, старый оставить.
2. Выбрать новый путь только в соответствующей конфигурации Gateway и binding
   native bridge. Конфигурацию другого курса и его snapshots не менять.
3. Доставить файлы и перечитать конфигурации через
   `ansible-playbook -i /absolute/private/inventory.yml ansible/site.yml --tags deployment`.
   Этот режим использует уже установленный Docker и не обновляет APT repositories;
   для локального обновления курса исходящий Интернет не требуется.
4. Выполнить native sync только для выбранного **actual course ID**:

```sh
sudo docker exec -w /PrairieLearn prairielearn-pl-1 node \
  /PrairieLearn/apps/prairielearn/bridge/operator-tools/sync-native-course.mjs \
  --course-id ACTUAL_COURSE_ID --path /course/COURSE_ID/NEW_DELIVERY_HASH
```

Команда проверяет deliveryHash, все inventory hashes, отсутствие symlinks,
binding, source course ID и прежний UUID. Выполнить её может локальный оператор
через доверенную конфигурацию с уже созданным native administrator. Actual native
models, audit и named locks используются без прямого SQL изменения оценок.
Ошибки/warnings native sync завершают команду с ошибкой; после сбоя следует
проверить фактический native path и повторить операцию либо выбрать прежнюю версию.
Native `loadFromDisk` — dev-only route и для production этой командой не заменяется.

## Границы проверки

Проверка сервера 11 октября 2026 использует настоящие подписанные LTI launches
локального Moodle mock с ноутбука, доверенный HTTPS, Student HTTP submissions
и AGS readonly readback. Настоящий Moodle учреждения пока недоступен.
Стенд использует diagnostic candidate images с проверенными config IDs и
архивами: доступ к опубликованным GHCR artifacts не подтверждён текущими токенами.
Это не опубликованный runtime release и не прохождение published staging gate.
Публикация immutable runtime images и проверка реального Moodle остаются отдельными
этапами. `runtime-profiles.json` для нового fish profile намеренно содержит
`image: null` до публикации; существующие published checks не ослабляются.

На проверенном узле исходящий доступ VM к package repositories отсутствовал:
bootstrap использовал ограниченный relay ноутбука. Для последующих обновлений
системных пакетов требуется разрешённый оператором транспорт; работа уже
размещённого runtime и режим `--tags deployment` от relay не зависят.
