# Производный Landlock helper

Компонент изменён22октября2026года относительно `PrairieLearn/PrairieLearn`, `graders/java/sandbox.c`, commit `7ab76051b1957a4dd4717f1ec4c6087d1da8b7cf`. Единственный редактируемый policy source — `sandbox.c`. Новая возможность ограничена проверенным character device `/dev/null`1:3: file-bound READ/WRITE и уже поддерживаемый TRUNCATE. Recursive grant каталогу `/dev` не добавлен; остальные upstream rules/ABI handling сохранены.

Helper проверяет no-follow parent/leaf FD, root UID/GID, безопасные parents, mode0666/nlink1 и полную path/FD identity до/после add-rule. Любой отказ нового grant завершает helper до target exec. Служебные FD закрываются; ошибки их закрытия также запрещают exec. Paths, flags либо policy из student config/env не принимаются.

`provenance.json` связывает точный upstream blob, изменённый source и фактически скомпилированный ELF. Полные upstream license/notices сохранены в `PRAIRIELEARN-LICENSE`, скопированном из уже имеющегося PrairieLearn license snapshot репозитория; его исходный commit и hash указаны отдельно. Комментарии upstream и attribution не удалены. Равенство прежнего image ELF этому source не утверждается.

Новый бинарный файл создаётся offline существующим GCC; compiler/binutils/headers/argv/source before-after и ELF requirements сохраняются в частном operator evidence. Он не хранится в Git и не выводится из предположительного hash. Runtime guard проверяет фактические bytes/owner/mode/nlink/parents/file capabilities до official child execution; compiled digest закреплён в существующем runner. Обновление binary требует новой связанной source/build/runner hash closure, а не редактирования соседнего receipt.

C syscall fixtures проверяют точный leaf/mask, object/identity failures и отсутствие exec/служебных FD при отказе. Это source proof, не kernel sandbox acceptance. Actual helper/canaries/Gradle/B8 checks допускаются после отдельного ROOT source/compile review. Локальный image ID не является опубликованным OCI digest; публикация требует отдельной приёмки.
