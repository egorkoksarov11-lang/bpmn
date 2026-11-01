# BPMN Universal Engine — experimental r4

Автоматическая компоновка с сохранением бизнес-логики. Новый эксперимент совместно размещает основные шаги и ответвления, сохраняя порядок чтения в дорожках. Заголовки дорожек учитываются как препятствия при поиске маршрутов.

- [SVG](output/process_08_v23.svg) · [BPMN](output/process_08_v23.bpmn)
- [Сравнение r3/r4 и запуск](docs/DEVELOPMENT_R4.md)
- [Геометрия](output/geometry_report.json) · [Читаемость](output/readability_report.json) · [Semantic diff](output/semantic_diff.json)
- [Предыдущая схема r3](https://github.com/egorkoksarov11-lang/bpmn/blob/ca03247a96836a41a28004db7db4995178331223/output/process_08_v23.svg)

На frozen №08: контакты 60 → 40, длинные переходы 33 → 31, пиковая плотность 8 → 7 потоков в ячейке. Площадь выросла примерно на 0,6%; индекс близких параллельных линий немного вырос. Это компромисс по открытой инженерной политике, не доказательство человеческой оценки качества. 63 теста прошли; semantic diff и DI freeze равны нулю.

Сохранены 64 узла, 95 переходов, 18 документных связей, 17 документных references и 6 дорожек. Полный текст, Open Sans 13 px. Схема ещё экспериментальная: пересечения остаются, печать целиком на одном A4 слишком мелкая.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_v23.py --input inputs/benchmark/process_08_v4_frozen.bpmn \
  --output-dir output-r4 --candidate-timeout 120 \
  --incumbent examples/process_08_r3.bpmn --repack-spine --no-decision-orientations
PYTHONPATH=src/v23:src/v22 .venv/bin/python -m pytest tests src/v22/tests -q
```

Python ≥3.10. Сеть, Node и Graphviz при компоновке не требуются. Для новой модели убрать --incumbent; флаг --repack-spine включает экспериментальную перестановку основной цепочки. Без него сохранён прежний режим. Результаты записываются отдельно от входов. Время A* ограничено; точные координаты могут различаться между запусками.

[Архитектура](docs/ARCHITECTURE_V23.md) · [История r3](docs/DEVELOPMENT_R3.md) · [Исследование ручных схем](docs/studies/HUMAN_LAYOUT_AUTOMATION_RULES_RU.md). Крупные сценарные шаблоны пока остаются аналитическим инструментом. Офисные документы, исходные архивы и сырые журналы сессии не публикуются.
