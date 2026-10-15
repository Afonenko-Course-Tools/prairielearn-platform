# Пилот на Proxmox

Платформа обслуживает несколько native-курсов в одной VM. Конфигурация пилота:
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
`up -d --force-recreate` при материальных изменениях. При неизменной delivery PostgreSQL/SQLite state и snapshots сохраняются после перезапуска. Для новой delivery соблюдайте условия раздела [«Прежний курс и другая delivery»](#прежний-курс-и-другая-delivery). Systemd включает запуск после reboot.
Docker socket предоставлен только PL для запуска grader containers; ответ
студента выполняется в ограниченном grader без socket и сети. На уровне PL
одновременно выполняются максимум два локальных grader job по 512 MiB.

## Обновление одного курса

### Учреждение и новый native курс

Авторитетный descriptor хранится в versioned `config/institutions.json`, запись
`pl-courses-v2` ссылается на `institution` key. Для БГУ это `bsu`; другой descriptor
работает тем же generic кодом. Не задавайте numeric native ID или названия
учреждения в записи курса. Перед переносом snapshot выполните `check_registry.py`
и `stage_courses.py`; публикуемый payload должен иметь полный release receipt.

Для новой изолированной поставки подготовьте readonly `/course/KEY/DELIVERY_HASH`
и разрешённый bridge binding. Используйте уже существующего native administrator,
его private allowlist и **те же** токены, ключи и сертификаты. Каталог учреждений
не содержит SSO registration и не изменяет issuer/client/deployment/subjects.
Registry смонтируйте отдельным readonly файлом в контейнер; путь ниже — пример,
его отсутствие является ошибкой, скрипт не генерирует конфигурацию.

```sh
sudo docker exec -w /PrairieLearn prairielearn-pl-1 node \
  /PrairieLearn/apps/prairielearn/tools/bootstrap-native-course.mjs \
  --registry /run/deployment/courses.json --course-key COURSE_KEY \
  --path /course/COURSE_KEY/DELIVERY_HASH
```

CLI проверяет v2 registry и institution catalog до native dependencies, затем
inventory/hash/symlinks и bridge path, production config и фактическую administrator
роль. Он вызывает native `models/institution.selectAllInstitutions` и
`insertInstitution({shortName,longName,displayTimezone,uidRegexp})`, далее native
`models/course.insertCourse` с разрешённым `institution_id` и actor/audit. Это те
же модели, которые используют административные tRPC `institutions.addInstitution`
и `courses.insert`. Course repository остаётся `null`: snapshot immutable, native
repository sync не используется. Результат JSON содержит фактические course и
institution IDs, но не credentials; native disk sync ещё нужен.

Повтор одинакового descriptor/path возвращает прежние IDs. Named locks защищают
одновременный bootstrap. Если native короткое имя совпало, но descriptor отличается,
или course принадлежит другому institution, команда завершается ошибкой; существующее
учреждение/курс не переименовываются и не перемещаются. CLI не создаёт admin и не
мигрирует предыдущую delivery. Для другого каталога передайте `--institutions PATH`;
descriptor поля — shortName/longName/displayTimezone/uidRegexp; timezone должен быть
известен runtime, UID regexp при наличии проходит штатные ограничения синтаксиса.

После bootstrap выполните sync с полученным actual course ID и той же registry:

```sh
sudo docker exec -w /PrairieLearn prairielearn-pl-1 node \
  /PrairieLearn/apps/prairielearn/tools/sync-native-course.mjs \
  --course-id ACTUAL_COURSE_ID --path /course/COURSE_KEY/DELIVERY_HASH \
  --registry /run/deployment/courses.json --course-key COURSE_KEY
```

Sync дополнительно сравнивает фактический institution ID до изменения native path.
Прежняя форма с actual ID без registry остаётся локальной операцией существующего
курса, она не создаёт institution и не выбирает Default. Наличие неизвестного key
в явно переданной registry всегда ошибка. Сам bootstrap не подтверждает native
Student launch, grader или Moodle grades: нужны сквозные live evidence.

Повторный импорт **той же** новой поставки проверяйте на тестовой БД после
штатного создания enrollment/attempt/result. Сохраняйте их IDs и grades. Для нового
семестра key меняет instance UUID; не объявляйте это миграцией pilot. Assessment,
course, access и question namespaces не менять. Legacy Default/pilot данные
не удалять, credentials не регенерировать и LTI registration не заменять.

### Прежний курс и другая delivery

Для новой delivery подготовьте новый native course и отдельный instance, например `2026-2027-s1`, в существующем профиле Gateway.
Сохраните ту же SQLite schema3, routePrefix/cookie path, HTTPS origin, LTI registration и activity bindings;
ключи signing/handoff/bridge и шифрования БД, bearer tokens и TLS certificates не заменяйте.
Сохранённые строки `GatewaySession` и CSRF продолжают действовать до обычного expiry; одноразовость handoff/state не меняется.
Прежний pilot, его enrollments, attempts, assignments, labels и observations остаются в прежнем scope без переноса в новый instance.
Замена delivery внутри того же instance здесь не поддерживается: `Explicit delivery migration required` нельзя обходить.
Свежая БД допустима для первого отдельного развёртывания, но не обеспечивает непрерывность существующих cookies/session bearer.
Условия переключения и проверка сохранности состояния описаны в [инструкции Gateway](https://github.com/Afonenko-Course-Tools/moodle-prairielearn-gateway/blob/73ea3c64e32af9805bc3fc5cc06b59d6630717c0/docs/two-courses.md).

1. Экспортировать и проверить выбранный курс; его UUID и source course ID должны
   сохраняться. Создать новый каталог `<id>/<newDeliveryHash>`, старый оставить.
2. Сохранить существующую Gateway БД schema3 и её путь в именованном профиле. Проверить фактические ID нового native course/instance, затем обновить только его delivery path и согласованную binding в Gateway и bridge. Прежние назначения и observations не переносить; конфигурацию другого курса, его БД и snapshots не менять.
3. Доставить файлы и перечитать конфигурации через
   `ansible-playbook -i /absolute/private/inventory.yml ansible/site.yml --tags deployment`.
   Этот режим использует уже установленный Docker и не обновляет APT repositories;
   для локального обновления курса исходящий Интернет не требуется.
4. Выполнить native sync только для выбранного **actual course ID**:

```sh
sudo docker exec -w /PrairieLearn prairielearn-pl-1 node \
  /PrairieLearn/apps/prairielearn/tools/sync-native-course.mjs \
  --course-id ACTUAL_COURSE_ID --path /course/COURSE_ID/NEW_DELIVERY_HASH
```

Команда проверяет deliveryHash, все inventory hashes, отсутствие symlinks,
binding, source course ID и прежний UUID. Выполнить её может локальный оператор
через доверенную конфигурацию с уже созданным native administrator. Actual native
models, audit и named locks используются без прямого SQL изменения оценок.
Ошибки/warnings native sync завершают команду с ошибкой; после сбоя следует
проверить фактический native path и повторить операцию либо выбрать прежнюю версию.
Native `loadFromDisk` — dev-only route и для production этой командой не заменяется.

## Проверка установленной версии

 Используйте согласованные Platform/Gateway 2.0.0 и только опубликованные digest
 pins из release receipts. Перед установкой подтвердите pull всех образов с
 целевого узла; отсутствие доступа к GHCR не доказывает отсутствие версии.
 Диагностические candidate images не проходят production staging gate.

 На новом изолированном стенде проверьте доверенный HTTPS, подписанные LTI
 launches, native Student editor, фактические оценки, выбор случайных позиций,
 teacher/student isolation, AGS readback, очередь, конкурентные отправки и
 сохранение состояния после перезапуска. Moodle mock проверяет протокол, а
 подключение Moodle учреждения требует отдельной фактической проверки.

 Для bootstrap и последующих обновлений системных пакетов нужен доступ VM к
 закреплённым repositories или разрешённый оператором транспорт тех же байтов.
 Режим обновления одного курса `--tags deployment` использует установленный
 Docker и не требует изменения сети или доступа к APT repositories.

## Проверка браузера за HTTPS-прокси

В native private `pl.json` задайте `trustProxy: 1`, если перед PrairieLearn
находится ровно один управляемый nginx. Proxy должен перезаписывать
`X-Forwarded-Proto`, а native порт не должен публиковаться наружу. Это позволяет
штатному `secure: auto` выдавать Secure cookies при внешнем HTTPS. Без этой
настройки cookie с `SameSite=None` отвергается браузером, даже если HTTP-клиент
принимает её.

Production nginx должен проксировать `/assets/` в native PrairieLearn с сохранением
пути: стили, модули JavaScript и шрифты находятся вне `/pl/`. Проверка HTML200
без загрузки этих ресурсов не подтверждает работоспособность панели.

Проверка фактического развёртывания (URL и CA принадлежат своему стенду):

```sh
PL_BROWSER_TEST_URL=https://АДРЕС_СТЕНДА \
PL_BROWSER_TEST_CA=/абсолютный/путь/ca.crt \
python3 -m unittest discover -s tests -p test_browser_assets_live.py
```

Тест читает настоящую страницу, проверяет HTTP200 и MIME её CSS/JS, затем
проверяет Secure/HttpOnly native cookies. Для административной панели дополнительно
проверьте её ресурсы и отображение интерфейса в настоящем браузере.
