# Генератор для самостоятельного использования

[Скачать BPMN Generator v23.4.2 для Windows](https://raw.githubusercontent.com/egorkoksarov11-lang/bpmn/main/releases/BPMN_Generator_Windows_v23_4_2.zip).

Распакуйте ZIP целиком, дважды нажмите `START_WINDOWS.cmd`, дождитесь установки, выберите `.bpmn`, `.json`, `.yaml`, `.yml` или `.ylm` и нажмите «Создать схему». Структура JSON, условия, типы узлов и примеры для скачивания показаны прямо на первой странице.

BPMN, SVG и отчёты сохраняются в новой папке `results`. Python, Node.js и библиотеки устанавливаются автоматически внутри пакета; права администратора не требуются. JSON/YAML преобразуется во входной BPMN, далее работает прежний алгоритм scratch.

[Инструкция](../desktop/README.md) · [Формат JSON/YAML](../desktop/INPUT_FORMAT.md) · [Пример JSON](../desktop/example.json) · [Пример YAML](../desktop/example.yaml) · [Проверки v23.4.2](../docs/INPUT_ADAPTER_V23_4_2.md) · [Windows Actions](https://github.com/egorkoksarov11-lang/bpmn/actions/workflows/desktop-windows.yml).

Полный код включён в ZIP. Пользовательских процессов в архиве нет. Первая установка требует интернета; обработка файлов локальная. Предыдущий пакет v23.4.1 остаётся доступен в этой папке.
