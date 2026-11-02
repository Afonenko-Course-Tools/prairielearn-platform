# Полное авторское Java-решение в private проверке

Этот tools-only followup основан на квалифицированном Source2.5.2. Версия
Runtime OCI, grade.py, registry, схемы и публичный student descriptor не меняются.
Новые tools требуют отдельной Source-квалификации; они не выдаются за прежний
опубликованный commit или новый опубликованный Runtime.

В reference-сценарии Java без additional-java-sources источниками являются
только файлы явно объявленного named reference с прежними Source hashes и
origin checks. Полное авторское решение может добавлять helper-классы и
использовать другие имена реализации. Сначала проверяется оригинальный
student delivery descriptor, затем только private reference job получает
точный список авторских sourceFiles. Ограничения128 файлов,1MiB на файл,4MiB
суммарно, .java и безопасные пути сохраняются. Student/starter/contract cases,
scoring, runtime image и ветвь явно настроенной student ZIP policy прежние.

Это не даёт студенту дополнительных upload capabilities и не разрешает
собирать файлы по неявному поиску. Declared/source controls не являются полным
container coverage или release receipt.
