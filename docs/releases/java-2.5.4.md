# Java 2.5.4 без повторной сборки Community/SP

Исходная база — актуальный публичный main после Community 2.5.3 и reference-complete source tools. Исправлены три точных дескриптора JUnit: `assertEquals(int, Integer)`, `assertFalse(boolean, String)`, `assertArrayEquals(char[], char[])`. Каждый по-прежнему вызывает штатный JUnit один раз и сохраняет независимые leaf outcomes. Два Source bundle SHA соответствуют изменённому фасаду; Transform, изоляция, scoring и admission policy не меняются.

Существующий Java Dockerfile получает новый закрытый toolchain context. Публикуется только новый Java image. Community 2.5.3, fish и Workspace сохраняют прежние immutable digests и исходное build provenance. `tools/publish-receipt.py` создаёт три новых assets из нового reviewed Source и фактического набора digests. Его Source/version обозначают новую assembly; reused images не объявляются заново собранными.

Полный workflow `components=all` здесь не используется: он собирает все роли. `components=community` относится только к прежнему Community-only выпуску. Версия 2.5.4 и actual digests/readback не считаются опубликованными до штатных действий оператора. Старые release/tag/assets не перезаписываются.

Принятые Source-проверки включают настоящий полный локальный leaf-тест: пять JUnit исходов (один положительный и четыре ожидаемых отрицательных) за 3,265 с. Это не OCI qualification и не полный census. Два случая отсутствующего полного JUnit-отчёта остаются открытыми.

Для увеличенного инфраструктурного run budget Java-course Source содержит `run-seconds: 120` при outer300/compile120. Это отдельное изменение Source курса, не скрытая правка образа. Новый digest/registry и run120 входят в новую честно сгенерированную Native delivery; старые delivery hashes/receipts не меняются.
