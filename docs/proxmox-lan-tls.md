# HTTPS для сайта и Moodle в локальной сети Proxmox

Это план будущего развёртывания в LAN без DNS. Он не означает, что Proxmox или
рабочие серверы уже настроены. Для студентов нужен постоянный адрес гостевой VM
и сертификат от доверенного учреждением центра сертификации (CA).

Во всех примерах `192.0.2.20` — **адрес только для документации**, а не адрес,
который следует назначить VM. Замените его выделенным адресом своей LAN; блок
`192.0.2.0/24` описан в [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737.html).

## Два разных сервера и сертификата

| Назначение | Где работает | Адрес для подключения | Кто получает доступ |
| --- | --- | --- | --- |
| Панель Proxmox | На гипервизоре, `pveproxy` | IP узла Proxmox, обычно HTTPS порт 8006 | Администраторы |
| Сайт, Moodle, Gateway, PrairieLearn | В гостевой VM; HTTPS завершает reverse proxy | Постоянный IP VM, HTTPS порт 443 | Студенты и преподаватели |

Сертификат гипервизора не настраивает HTTPS внутри VM. Выделите VM отдельный
статический IP либо постоянную DHCP-резервацию; проверьте адрес, маску, шлюз и
отсутствие конфликта адресов. При подключении VM к сетевому мосту Proxmox адрес
гипервизора не становится адресом VM.

На сетевом и VM firewall разрешите студенческой сети доступ к VM на TCP 443.
Порты панели Proxmox, SSH, PostgreSQL, Docker, внутренних API и прямые порты
приложений оставьте доступными только необходимым административным или внутренним
сетям. Не публикуйте в LAN отладочные порты вместо proxy. Доступ к панели Proxmox
для работы с курсом студентам не нужен.

## Постоянные внешние адреса Moodle и LTI

Заранее выберите один origin: схема `https`, IP VM и порт. Ниже — пример схемы
путей, которую ещё нужно настроить и проверить на выбранном proxy и backend:

| Компонент | Пример внешнего URL |
| --- | --- |
| Сайт курса | `https://192.0.2.20/` |
| Moodle | `https://192.0.2.20/moodle` |
| Gateway | `https://192.0.2.20/gateway/` |
| PrairieLearn | `https://192.0.2.20/pl/` |

Разные пути остаются одним origin. Если используется другой HTTPS-порт, он должен
присутствовать во всех соответствующих URL. SAN сертификата содержит IP, без
порта и пути.

В Moodle задайте фиксированный публичный адрес, без завершающего `/`:

```php
$CFG->wwwroot = 'https://192.0.2.20/moodle';
$CFG->reverseproxy = true;
$CFG->sslproxy = true;
```

Последние два параметра относятся к установке за reverse proxy, где HTTPS
завершается на proxy, а дальше используется HTTP. Сверьте их со своей схемой
по [документации Moodle о reverse proxy](https://docs.moodle.org/503/en/Reverse_proxy_frontend).
Сам `wwwroot` не создаёт маршрут `/moodle`: web server и proxy должны согласованно
обслуживать этот префикс. Проверьте редиректы, CSS, изображения, cookies и вход;
не переносите произвольный пример `proxy_pass` с удалением префикса без проверки.
Proxy должен задавать доверенные forwarded-заголовки и сохранять ограничения
идентификации и доступа Gateway/PrairieLearn.

После выбора адресов откройте в Moodle настройки зарегистрированного внешнего
инструмента. Скопируйте оттуда фактические **issuer / Platform ID, client ID,
deployment ID, URL авторизации, token endpoint и JWKS** в конфигурацию Gateway;
в Moodle укажите фактические launch/login/JWKS URL инструмента. ID не вычисляются
из IP и не заменяются произвольными значениями. Используйте
[настройку External tool](https://docs.moodle.org/503/en/External_tool) и
[описание парной LTI-регистрации Moodle](https://docs.moodle.org/403/en/LTI_provider).
При смене IP или `wwwroot` отдельно согласуйте регистрацию обеих сторон,
сохранённые ссылки и callback URL: Moodle также предупреждает о проверке LTI и
контента при [переходе на HTTPS](https://docs.moodle.org/503/en/Transitioning_to_HTTPS).
При обычном продлении сертификата с прежними URL повторная регистрация не нужна.

## Сертификат VM от CA учреждения

Предпочтителен существующий CA учреждения с принятой процедурой выдачи,
продления и отзыва. Если его нет, создание управляемого частного CA — отдельная
задача администратора. Будущий рабочий CA отделён от текущего development CA:
[локальные инструменты разработки](development.md) не заменяют эту процедуру.

Для закрытой LAN с частным IP публичный ACME не решает выдачу сертификата:
публичные CA не выпускают сертификаты на Reserved IP или Internal Name согласно
[CA/B Forum Baseline Requirements](https://github.com/cabforum/servercert/blob/main/docs/BR.md#422-approval-or-rejection-of-certificate-applications).
При этом публичные IP-сертификаты уже существуют, например у
[Let's Encrypt](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability);
это не делает закрытый частный адрес допустимым. DNS-01 предполагает контроль
над публичным доменом, которого в этой схеме нет.

На VM создайте серверный ключ и CSR вне checkout. Следующий пример только готовит
запрос: он не подписывает сертификат и не меняет доверие компьютера.
Запускайте его один раз в новом каталоге: не перезаписывайте действующий ключ.

```bash
vm_ip=192.0.2.20                 # заменить реальным выделенным IP VM
tls_dir=/srv/course/tls         # отдельный закрытый каталог вне Git
umask 077
mkdir -p "$tls_dir/request"
openssl req -new -newkey rsa:3072 -noenc \
  -keyout "$tls_dir/request/server.key" \
  -out "$tls_dir/request/server.csr" \
  -subj "/CN=$vm_ip" \
  -addext "subjectAltName=IP:$vm_ip" \
  -addext "extendedKeyUsage=serverAuth"
```

Администратору CA передаётся CSR, а серверный приватный ключ
остаётся на VM. Ключ CA не нужен proxy и не должен попадать на VM или к студентам.
Для автоматического старта proxy серверный ключ в примере без пароля: ограничьте
его права и доступ к резервным копиям. Подробности параметров — в
[OpenSSL req](https://docs.openssl.org/3.5/man1/openssl-req/).

Запросите leaf-сертификат с `subjectAltName=IP:РЕАЛЬНЫЙ_IP` и назначением
`serverAuth`, а также промежуточные сертификаты цепочки. IP должен быть именно
IP SAN; один CN или `DNS:192.0.2.20` его не заменяет. CA может не скопировать
расширения CSR автоматически, поэтому проверяйте выданный сертификат. Формат
IP SAN описан в [OpenSSL x509v3_config](https://docs.openssl.org/3.5/man5/x509v3_config/).

## Цепочка на proxy и доверие клиентов

Для Nginx соберите `fullchain.pem`: сначала leaf, затем промежуточные сертификаты
в порядке цепочки. Корневой сертификат устанавливается в доверие клиентов и
обычно не включается в отправляемую сервером цепочку. Ниже только TLS-фрагмент,
который нужно встроить в существующую конфигурацию маршрутов и контроля доступа:

```nginx
server {
    listen 443 ssl;
    server_name 192.0.2.20;
    ssl_certificate     /etc/nginx/tls/current/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/current/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    # Здесь нужны проверенные location/upstream и правила доступа приложения.
}
```

Порядок цепочки и настройки ключа объясняет
[официальная документация Nginx HTTPS](https://nginx.org/en/docs/http/configuring_https_servers.html).
Храните ключи, приватные конфигурации, LTI/JWT-ключи и токены вне Git; TLS-ключ
proxy и ключ подписи JWT инструмента — разные ключи.

Администратор распространяет **только публичный сертификат корневого CA** через
проверенный канал; перед установкой сверяется его SHA-256 fingerprint. Доверие
нужно не только браузерам студентов: настройте CA также у Moodle/PHP/cURL,
Gateway и других клиентов, выполняющих HTTPS-запросы. Их хранилища могут различаться.
Firefox на Linux не всегда использует системное хранилище автоматически; для
управляемых машин примените поддерживаемый импорт или enterprise policy.
Поведение ОС и Firefox описано у
[Mozilla](https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox).
Исключение в браузере, `curl -k` и отключённая проверка TLS не являются настройкой
доверия.

## Продление leaf без замены CA

Назначьте ответственного и срок предупреждения до `notAfter`. Продлевайте leaf
у того же CA с тем же IP SAN; смена CA и распространение нового trust anchor —
отдельная согласованная операция. До установки проверьте срок, SAN, назначение,
цепочку и соответствие ключу:

```bash
vm_ip=192.0.2.20                 # заменить реальным IP
issued=/srv/course/tls/incoming  # новый комплект, вне Git
root_ca=/srv/course/trust/root-ca.crt
openssl x509 -in "$issued/leaf.crt" -noout -subject -issuer -dates -ext subjectAltName
openssl x509 -in "$issued/leaf.crt" -noout -checkend 1209600  # пример: 14 дней
openssl verify -CAfile "$root_ca" -untrusted "$issued/intermediates.pem" \
  -purpose sslserver -verify_ip "$vm_ip" "$issued/leaf.crt"
openssl x509 -in "$issued/leaf.crt" -pubkey -noout | \
  openssl pkey -pubin -outform DER | openssl dgst -sha256
openssl pkey -in "$issued/server.key" -pubout -outform DER | openssl dgst -sha256
```

Последние два отпечатка должны совпасть. Если leaf подписан непосредственно
корнем, уберите `-untrusted` с отсутствующим файлом. Опции проверки приведены в
[OpenSSL verify](https://docs.openssl.org/3.5/man1/openssl-verify/) и
[OpenSSL x509](https://docs.openssl.org/3.5/man1/openssl-x509/).

Для контейнера предпочтителен read-only mount **стабильного каталога**
`/srv/course/tls:/etc/nginx/tls:ro`. Внутри него храните комплекты в
`versions/ИМЯ_ВЕРСИИ/`, а `current` сделайте относительной ссылкой на один комплект.
Подготовьте и проверьте оба файла заранее; затем атомарно замените ссылку
`current` на новую версию и сохраните старую для отката. Не заменяйте сам
смонтированный каталог. Особенности источника mount описывает
[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/).

При отдельном bind mount каждого файла атомарная замена файла на хосте может
оставить контейнер со старым inode. Проверьте содержимое именно внутри proxy;
если новый файл ему не виден, потребуется пересоздание контейнера с теми же
проверенными параметрами. Один reload этого не исправляет.

После переключения выполните `nginx -t` в среде действующего proxy. При ошибке
верните прежнюю ссылку. При успехе выполните `nginx -s reload` там же. Nginx
проверяет новую конфигурацию и меняет workers при
[reload](https://nginx.org/en/docs/control.html); это не заменяет проверку реально
отдаваемого сертификата через новое соединение:

```bash
vm_ip=192.0.2.20                 # заменить реальным IP
root_ca=/srv/course/trust/root-ca.crt
openssl s_client -connect "$vm_ip:443" -CAfile "$root_ca" \
  -verify_ip "$vm_ip" -verify_return_error </dev/null
curl --fail --cacert "$root_ca" "https://$vm_ip/moodle/login/index.php"
```

Опции проверки нового TLS-соединения описаны в
[OpenSSL s_client](https://docs.openssl.org/3.5/man1/openssl-s_client/).
Сверьте fingerprint и срок сертификата нового соединения с новым leaf; проверьте
сайт и Moodle из обычного доверяющего CA браузера. При первоначальном переносе
адресов дополнительно проверьте реальный LTI-вход студента, ограничения доступа,
отправку работы и возврат оценки. При продлении с неизменными адресами проверьте
также HTTPS-запросы сервисов; настройки issuer/client/deployment и JWT-ключи
из-за продления TLS не меняются.

## Если администратор хочет настроить сертификат самой панели Proxmox

Это отдельная необязательная задача для IP узла гипервизора, не IP VM. Можно
загрузить выданный для узла custom certificate через **Node → Certificates**;
официальный CLI — `pvenode` (`pvenode cert info`, `pvenode help cert set` для
проверки доступной команды и параметров на установленной версии).

Proxmox использует custom-файлы `/etc/pve/local/pveproxy-ssl.pem` и
`/etc/pve/local/pveproxy-ssl.key`; ключ должен быть без пароля. **Не заменяйте**
автоматические `pve-ssl.pem`, `pve-ssl.key`, корневой `pve-root-ca.pem` или
`/etc/pve/priv/pve-root-ca.key`. Следуйте
[официальному руководству Proxmox по сертификатам](https://github.com/proxmox/pve-docs/blob/master/certificate-management.adoc)
и [описанию CLI pvenode](https://github.com/proxmox/pve-manager/blob/master/PVE/CLI/pvenode.pm).
Приватный ключ CA кластера никогда не переносится в VM или на клиентские машины.
Для доверия панели администраторы отдельно устанавливают только публичный CA
сертификат либо доверяют выбранному CA учреждения; студентам доступ к панели
и её сертификат для курса не требуются.

Официальные источники проверены 10 октября 2026 года. Перед рабочим развёртыванием
сверьте параметры с установленными версиями Proxmox, Moodle, Nginx и OpenSSL.
