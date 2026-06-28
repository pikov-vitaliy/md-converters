"""Чинит None std-потоки под pythonw (ярлык GUI без консоли).

Под pythonw sys.stdout/stderr = None. Любой вывод — включая
предупреждения при импорте markitdown/magika — роняет процесс с
AttributeError ещё ДО main(). Поэтому этот модуль импортируется
ПЕРВЫМ в gui_server (до тяжёлых импортов) и перенаправляет None в
os.devnull. Для обычного запуска с консолью — ничего не делает.
"""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
