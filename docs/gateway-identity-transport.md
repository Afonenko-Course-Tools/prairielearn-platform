# Имя из проверенного Gateway handoff

Gateway выдаёт ASCII `X-Verified-Name-UTF8-B64: v1.<base64url>` от строгого UTF-8.
В production nginx только защищённый handoff получает этот response header через
`auth_request` и устанавливает `X-Trust-Auth-Name-UTF8-B64`. Старое raw Name
очищается. Все остальные proxy locations, включая dev через `pl-headers.conf`,
очищают оба Name header вместе с прежними UID/UIN. Прямой callback закрыт.

`images/prairielearn/patch-gateway-name.py` проверяет целиком pinned src TS и dist JS
до записи любого файла. Одна canonical функция decoder генерируется в оба файла
перед прежним `loadUser`; Dockerfile применяет patch согласованно. Prefix, alphabet,
padding, round trip, строгий UTF-8, duplicate headers и границы размера проверяются
до `loadUser`. Decoder сохраняет пустую строку, BOM, combining marks и буквальные
HTML/URL символы; normalization, trim и повторное декодирование отсутствуют.
UID/UIN/provider, авторизация, SQL и связи результатов не меняются.

Base callbacks в `tests/fixtures/gateway-name-base.{ts,js}` — побайтные public
upstream fixtures Community `92584fe426ececb84bc2d09de9975c7056c0c5f6`;
целые fingerprints закреплены в patcher. Проверки `tests/test_identity_transport.py`
исполняют generated TS/JS callback с mock Router/loadUser. Это не native DB proof.
`tests/test_proxy_live.py` дополнительно проверяет очистку нового header настоящим
nginx на существующем opt-in proxy fixture.

Поставка требует согласованных Gateway, proxy и native image. При несовпавшем
fingerprint сборка отказывает; старый callback не совместим с новым transport.
Generated materials proxy должен сохранять существующий static materials block
и применять те же proxy правила. Live конфигурацию этот patch не изменяет.

Проверка native numeric user_id, повторного входа с обновлением профиля и
сохранности assessment/submission связей выполняется отдельно на настоящем
native/PostgreSQL. Mock loadUser, Gateway SQLite и proxy echo её не заменяют.
Два actual Moodle student входа и teacher UI остаются отдельной приёмкой.
