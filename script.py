#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RebootAppScript - ежедневный перезапуск приложения по расписанию.

Скрипт не требует внешних библиотек: только стандартная библиотека Python 3.8+.
Работает как фоновый супервизор: в заданное время завершает процесс приложения,
выдерживает паузу и запускает его снова. Все действия пишутся в logs\\rebootapp.log.

Режимы:
    (без параметров)   запустить супервизор (то же, что --daemon)
    --daemon           запустить супервизор
    --restart-now      перезапустить приложение прямо сейчас
    --ensure-running   запустить приложение, если оно не запущено
    --status           показать состояние
    --check            проверить конфигурацию (коды выхода: 0/2/4)
    --init-config      создать config.json со значениями по умолчанию
    --version          показать версию
"""

import argparse
import ctypes
import ctypes.wintypes as wintypes
import datetime as dt
import hashlib
import json
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_NAME = "RebootAppScript"
VERSION = "1.3.2"
TASK_NAME = "RebootAppScript"

IS_WINDOWS = os.name == "nt"

# Флаги CreateProcess / taskkill.
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

TH32CS_SNAPPROCESS = 0x00000002
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080


def get_base_dir():
    """Папка со скриптом (или с exe, если скрипт собран PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_PATH_DEFAULT = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "rebootapp.log"
STATE_PATH_DEFAULT = BASE_DIR / "state.json"

DEFAULTS = {
    "target_time": "00:00",
    "process_name": "assistant.exe",
    "file_to_run": r"C:\Program Files (x86)\Ассистент\assistant.exe",
    "app_args": [],
    "timeout": 60,
    "kill_timeout": 30,
    "launch_retries": 3,
    "launch_retry_delay": 10,
    "launch_check_seconds": 20,
    "start_if_not_running": True,
    "startup_delay": 30,
    "log_level": "INFO",
    "window_position": "primary",
}

log = logging.getLogger("rebootapp")


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

def setup_logging(level="INFO"):
    """Файловый лог (с ротацией) + консоль, если она есть."""
    log.setLevel(logging.DEBUG)
    for handler in list(log.handlers):
        log.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            str(LOG_PATH),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except OSError as exc:
        _safe_stderr("Не удалось открыть файл лога %s: %s\n" % (LOG_PATH, exc))

    if sys.stdout is not None:
        try:
            console = logging.StreamHandler(sys.stdout)
            console.setLevel(getattr(logging, str(level).upper(), logging.INFO))
            console.setFormatter(formatter)
            log.addHandler(console)
        except Exception:
            pass

    if not log.handlers:
        log.addHandler(logging.NullHandler())


def set_log_level(level):
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    for handler in log.handlers:
        handler.setLevel(numeric)


def _safe_stderr(text):
    try:
        if sys.stderr is not None:
            sys.stderr.write(text)
            sys.stderr.flush()
    except Exception:
        pass


def configure_std_streams():
    """Чтобы кириллица не роняла скрипт в консоли с неверной кодировкой."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    pass


def _as_bool(value, key):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "y", "on", "да", "вкл"):
            return True
        if normalized in ("0", "false", "no", "n", "off", "нет", "выкл"):
            return False
    raise ConfigError(
        'Параметр "%s" должен быть true или false, получено: %r' % (key, value)
    )


def _as_int(cfg, key, minimum, maximum):
    try:
        value = int(cfg[key])
    except (TypeError, ValueError):
        raise ConfigError(
            'Параметр "%s" должен быть целым числом, получено: %r' % (key, cfg[key])
        )
    if not minimum <= value <= maximum:
        raise ConfigError(
            'Параметр "%s" должен быть от %d до %d, получено: %d'
            % (key, minimum, maximum, value)
        )
    return value


def parse_target_time(value):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{1,2})\s*", str(value))
    if not match:
        raise ConfigError(
            'Параметр "target_time" должен быть в формате "ЧЧ:ММ", например "00:00". '
            "Получено: %r" % (value,)
        )
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(
            'Параметр "target_time" содержит недопустимое время: "%02d:%02d"'
            % (hour, minute)
        )
    return hour, minute, "%02d:%02d" % (hour, minute)


def load_config(path):
    if not path.is_file():
        raise ConfigError(
            "Файл конфигурации не найден: %s\n"
            "Создайте его командой: python script.py --init-config" % path
        )
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError("Не удалось прочитать %s: %s" % (path, exc))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            "Некорректный JSON в %s: строка %d, столбец %d - %s"
            % (path, exc.lineno, exc.colno, exc.msg)
        )
    if not isinstance(data, dict):
        raise ConfigError("Корень %s должен быть JSON-объектом { ... }" % path)

    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            cfg[key] = data[key]

    cfg["_config_path"] = str(path)

    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        log.warning("Неизвестные параметры конфигурации пропущены: %s", ", ".join(unknown))

    hour, minute, normalized = parse_target_time(cfg["target_time"])
    cfg["target_time"] = normalized
    cfg["_hour"] = hour
    cfg["_minute"] = minute

    process_name = str(cfg["process_name"]).strip().strip('"')
    if not process_name:
        raise ConfigError('Параметр "process_name" не может быть пустым')
    if "\\" in process_name or "/" in process_name:
        raise ConfigError(
            'Параметр "process_name" должен содержать только имя файла, '
            'например "assistant.exe" (без пути)'
        )
    if not process_name.lower().endswith(".exe"):
        process_name += ".exe"
    cfg["process_name"] = process_name

    file_to_run = str(cfg["file_to_run"]).strip().strip('"')
    if not file_to_run:
        raise ConfigError('Параметр "file_to_run" не может быть пустым')
    file_to_run = os.path.expandvars(os.path.expanduser(file_to_run))
    app_path = Path(file_to_run)
    if not app_path.is_absolute():
        app_path = BASE_DIR / app_path
    cfg["file_to_run"] = os.path.normpath(str(app_path))

    app_args = cfg["app_args"]
    if app_args is None:
        app_args = []
    elif isinstance(app_args, str):
        app_args = [app_args]
    elif not isinstance(app_args, list):
        raise ConfigError('Параметр "app_args" должен быть списком строк')
    cfg["app_args"] = [str(item) for item in app_args]

    cfg["timeout"] = _as_int(cfg, "timeout", 0, 3600)
    cfg["kill_timeout"] = _as_int(cfg, "kill_timeout", 1, 600)
    cfg["launch_retries"] = _as_int(cfg, "launch_retries", 0, 10)
    cfg["launch_retry_delay"] = _as_int(cfg, "launch_retry_delay", 0, 300)
    cfg["launch_check_seconds"] = _as_int(cfg, "launch_check_seconds", 1, 300)
    cfg["startup_delay"] = _as_int(cfg, "startup_delay", 0, 3600)
    cfg["start_if_not_running"] = _as_bool(cfg["start_if_not_running"], "start_if_not_running")

    log_level = str(cfg["log_level"]).strip().upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(
            'Параметр "log_level" должен быть DEBUG, INFO, WARNING или ERROR'
        )
    cfg["log_level"] = log_level

    window_position = str(cfg["window_position"]).strip().lower()
    if window_position not in ("keep", "primary"):
        raise ConfigError(
            'Параметр "window_position" должен быть "keep" или "primary"'
        )
    cfg["window_position"] = window_position

    return cfg


def init_config(path):
    if path.exists():
        print("Файл уже существует: %s" % path)
        return 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print("Не удалось создать %s: %s" % (path, exc))
        return 2
    print("Создан файл конфигурации: %s" % path)
    return 0


# ---------------------------------------------------------------------------
# Работа с процессами Windows
# ---------------------------------------------------------------------------

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel32.ReleaseMutex.restype = wintypes.BOOL

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    _user32.MonitorFromPoint.restype = wintypes.HANDLE
    _user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL


def list_processes():
    """Список (pid, имя_файла) всех процессов."""
    if not IS_WINDOWS:
        return []
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        return []

    result = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            result.append((int(entry.th32ProcessID), entry.szExeFile))
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)
    return result


def find_pids(process_name):
    target = process_name.casefold()
    return [pid for pid, name in list_processes() if name.casefold() == target]


def process_info_by_pid(pid):
    for current_pid, name in list_processes():
        if current_pid == pid:
            return name
    return ""


def is_main_window(class_name, title):
    """Главное окно «Ассистента», а не окно сеанса удалённого управления."""
    if class_name.startswith("TfmContainer"):
        return True
    return title.strip().casefold() == "ассистент" and "TApplication" not in class_name


def find_visible_window(process_name, main_only=True):
    """Первое видимое окно процесса с заголовком и нормальным размером."""
    if not IS_WINDOWS:
        return None
    pids = set(find_pids(process_name))
    if not pids:
        return None

    found = []

    @WNDENUMPROC
    def _callback(hwnd, _lparam):
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True

        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title, length + 1)

        class_name = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, class_name, 256)
        if main_only and not is_main_window(class_name.value, title.value):
            return True

        rect = RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 100 or height < 50:
            return True

        found.append(
            {
                "hwnd": int(hwnd),
                "title": title.value,
                "class": class_name.value,
                "left": rect.left,
                "top": rect.top,
                "width": width,
                "height": height,
            }
        )
        return False

    _user32.EnumWindows(_callback, 0)
    return found[0] if found else None


def move_window_to_primary(cfg):
    """Переносит окно приложения на основной монитор (если так настроено)."""
    if not IS_WINDOWS or cfg.get("window_position") != "primary":
        return True

    window = find_visible_window(cfg["process_name"])
    if not window:
        return False

    hwnd = wintypes.HWND(window["hwnd"])
    primary = _user32.MonitorFromPoint(POINT(0, 0), 1)
    current = _user32.MonitorFromWindow(hwnd, 0)
    if current == primary:
        return True

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not _user32.GetMonitorInfoW(primary, ctypes.byref(info)):
        log.warning("Не удалось определить размеры основного монитора")
        return False

    work = info.rcWork
    width = window["width"]
    height = window["height"]
    x = work.left + max(0, (work.right - work.left - width) // 2)
    y = work.top + max(0, (work.bottom - work.top - height) // 2)

    if not _user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0040):
        log.warning(
            "Не удалось перенести окно на основной монитор (код %s)",
            ctypes.get_last_error(),
        )
        return False

    log.info("Окно приложения перенесено на основной монитор")
    return True


def is_admin():
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_hidden(args, timeout=60):
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
    )


def _decode_console(data):
    for encoding in ("cp866", "cp1251", "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    return data.decode("utf-8", "replace")


def _taskkill(process_name):
    result = _run_hidden(["taskkill", "/F", "/T", "/IM", process_name], timeout=60)
    output = _decode_console((result.stdout or b"") + (result.stderr or b"")).strip()
    return result.returncode, output


def _powershell_stop(process_name):
    stem = Path(process_name).stem.replace("'", "''")
    command = (
        "Get-Process -Name '%s' -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue" % stem
    )
    try:
        _run_hidden(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Не удалось выполнить PowerShell Stop-Process: %s", exc)


def _wait_process_state(process_name, initial_pids, timeout_seconds):
    """killed / replaced / failed.

    replaced - процесс исчез, но вместо него появился другой экземпляр
    (например, его перезапустила служба). В этом случае повторный запуск не нужен.
    """
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        remaining = set(find_pids(process_name))
        if not remaining:
            return "killed"
        if not (remaining & initial_pids):
            return "replaced"
        time.sleep(0.4)
    remaining = set(find_pids(process_name))
    if not remaining:
        return "killed"
    if not (remaining & initial_pids):
        return "replaced"
    return "failed"


def terminate_processes(process_name, kill_timeout):
    pids = find_pids(process_name)
    if not pids:
        log.info("Процесс %s не запущен", process_name)
        return "not_running", ""

    initial = set(pids)
    log.info(
        "Завершаю процесс %s (PID: %s)",
        process_name,
        ", ".join(str(pid) for pid in sorted(pids)),
    )
    code, output = _taskkill(process_name)
    if code != 0:
        log.warning("taskkill вернул код %s: %s", code, (output or "без вывода")[:300])

    state = _wait_process_state(process_name, initial, kill_timeout)
    if state in ("killed", "replaced"):
        return state, output

    log.warning("taskkill не помог, пробую PowerShell Stop-Process")
    _powershell_stop(process_name)
    state = _wait_process_state(process_name, initial, kill_timeout)
    return state, output


# ---------------------------------------------------------------------------
# Запуск приложения
# ---------------------------------------------------------------------------

def launch_app(cfg):
    exe_path = Path(cfg["file_to_run"])
    if not exe_path.is_file():
        log.error("Файл приложения не найден: %s", exe_path)
        log.error(
            "Проверьте параметр file_to_run в %s", cfg.get("_config_path", "config.json")
        )
        return False

    existing = find_visible_window(cfg["process_name"])
    if existing:
        log.info("Окно «%s» уже открыто - запуск не требуется", existing["title"])
        return True

    command = [str(exe_path)] + list(cfg["app_args"])
    log.info("Запускаю: %s", subprocess.list2cmdline(command))
    try:
        process = subprocess.Popen(
            command,
            cwd=str(exe_path.parent),
            close_fds=True,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        log.error("Не удалось запустить приложение: %s", exc)
        return False

    deadline = time.monotonic() + cfg["launch_check_seconds"]
    while time.monotonic() < deadline:
        window = find_visible_window(cfg["process_name"])
        if window:
            log.info(
                "Приложение запущено, окно «%s» (PID запуска: %s)",
                window["title"],
                process.pid,
            )
            return True
        time.sleep(0.5)

    log.error(
        "Окно приложения не появилось за %d с после запуска",
        cfg["launch_check_seconds"],
    )
    return False


def start_app(cfg, reason=""):
    if find_pids(cfg["process_name"]):
        window = find_visible_window(cfg["process_name"])
        if window:
            log.info(
                "Приложение уже запущено, окно «%s» найдено - запуск не требуется",
                window["title"],
            )
            return True
        log.info(
            "Процесс %s работает, но окно не найдено - запускаю, чтобы открыть интерфейс",
            cfg["process_name"],
        )

    if reason:
        log.info("%s", reason)
    attempts = cfg["launch_retries"] + 1
    for attempt in range(1, attempts + 1):
        if find_visible_window(cfg["process_name"]):
            log.info("Окно приложения уже открыто - запуск не требуется")
            return True
        log.info("Запуск приложения (попытка %d из %d)", attempt, attempts)
        if launch_app(cfg):
            return True
        if attempt < attempts:
            log.warning("Повторная попытка через %d с", cfg["launch_retry_delay"])
            time.sleep(cfg["launch_retry_delay"])
    log.error("Не удалось открыть окно приложения после %d попыток", attempts)
    return False


# ---------------------------------------------------------------------------
# Состояние
# ---------------------------------------------------------------------------

def state_path_for(config_path):
    return config_path.parent / "state.json"


def read_state(path):
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_state(path, **values):
    data = read_state(path)
    data.update(values)
    data["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(str(temporary), str(path))
    except OSError as exc:
        log.warning("Не удалось сохранить состояние %s: %s", path, exc)


def format_datetime(value):
    if not value:
        return "-"
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        return parsed.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return str(value)


# ---------------------------------------------------------------------------
# Время
# ---------------------------------------------------------------------------

def next_occurrence(hour, minute, now=None):
    now = now or dt.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


def human_delta(seconds):
    seconds = int(max(0, seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append("%d дн." % days)
    if hours:
        parts.append("%d ч" % hours)
    if minutes or not parts:
        parts.append("%d мин" % minutes)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Мьютексы
# ---------------------------------------------------------------------------

def mutex_name(suffix):
    digest = hashlib.sha1(str(BASE_DIR).lower().encode("utf-8")).hexdigest()[:8]
    return "Local\\RebootAppScript_%s_%s" % (digest, suffix)


class WinMutex:
    def __init__(self, name):
        self._name = name
        self._handle = None

    def acquire(self, wait_ms=0):
        if not IS_WINDOWS:
            return True
        handle = _kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            log.warning(
                "Не удалось создать мьютекс %s: %s",
                self._name,
                ctypes.WinError(ctypes.get_last_error()),
            )
            return True
        result = _kernel32.WaitForSingleObject(handle, wait_ms)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self._handle = handle
            return True
        _kernel32.CloseHandle(handle)
        return False

    def release(self):
        if self._handle:
            try:
                _kernel32.ReleaseMutex(self._handle)
            except Exception:
                pass
            _kernel32.CloseHandle(self._handle)
            self._handle = None


# ---------------------------------------------------------------------------
# Перезапуск
# ---------------------------------------------------------------------------

def perform_restart(cfg, reason, state_path):
    lock = WinMutex(mutex_name("action"))
    if not lock.acquire(0):
        log.warning("Другой перезапуск уже выполняется - пропускаю")
        return False

    started = time.monotonic()
    success = False
    message = ""
    log.info("=" * 60)
    log.info("ПЕРЕЗАПУСК: %s", reason)
    log.info("=" * 60)
    try:
        if find_pids(cfg["process_name"]):
            state, _ = terminate_processes(cfg["process_name"], cfg["kill_timeout"])
            if state == "failed":
                message = "не удалось завершить процесс"
                log.error(
                    "Процесс всё ещё работает. Запуск отменён, чтобы не создать "
                    "второй экземпляр. Проверьте права администратора."
                )
            else:
                if state == "replaced":
                    log.warning(
                        "Процесс уже поднят внешней службой - после паузы проверю окно"
                    )
                if cfg["timeout"] > 0:
                    log.info("Пауза %d с перед запуском", cfg["timeout"])
                    time.sleep(cfg["timeout"])
                success = start_app(cfg, "Проверяю окно приложения")
        else:
            log.warning("Приложение не запущено - завершение не требуется")
            success = start_app(cfg, "Запускаю приложение")

        if success:
            move_window_to_primary(cfg)

        if success and not message:
            message = "перезапуск выполнен"
        elif not success and not message:
            message = "не удалось запустить приложение"
    except KeyboardInterrupt:
        message = "прервано пользователем"
        log.warning("Перезапуск прерван пользователем")
    except Exception:
        message = "непредвиденная ошибка"
        log.exception("Непредвиденная ошибка при перезапуске")
    finally:
        duration = time.monotonic() - started
        write_state(
            state_path,
            last_restart_at=dt.datetime.now().isoformat(timespec="seconds"),
            last_result="ok" if success else "error",
            last_message=message,
            last_duration_sec=round(duration, 1),
        )
        log.info(
            "Перезапуск завершён: %s (%.1f с)",
            "успешно" if success else "ошибка",
            duration,
        )
        lock.release()
    return success


# ---------------------------------------------------------------------------
# Режим супервизора
# ---------------------------------------------------------------------------

def run_daemon(cfg, state_path):
    if not IS_WINDOWS:
        log.error("Скрипт предназначен для Windows")
        return 1

    singleton = WinMutex(mutex_name("singleton"))
    if not singleton.acquire(0):
        log.info("Супервизор уже запущен - второй экземпляр не нужен")
        return 0

    log.info("=" * 60)
    log.info("%s v%s", APP_NAME, VERSION)
    log.info("Папка: %s", BASE_DIR)
    log.info("Пользователь: %s", os.environ.get("USERNAME", "?"))
    log.info("Права администратора: %s", "да" if is_admin() else "НЕТ")
    log.info(
        "Приложение: %s (%s)", cfg["process_name"], cfg["file_to_run"]
    )
    log.info("Ежедневный перезапуск в %s", cfg["target_time"])
    log.info("=" * 60)

    if not is_admin():
        log.warning(
            "Скрипт запущен без прав администратора. Завершение приложения может "
            "быть запрещено. Установите автозапуск через install.bat."
        )

    write_state(
        state_path,
        daemon_pid=os.getpid(),
        daemon_started_at=dt.datetime.now().isoformat(timespec="seconds"),
        version=VERSION,
    )

    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        log.info("Получен сигнал %s - завершаю работу", signum)
        stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        candidate = getattr(signal, signal_name, None)
        if candidate is not None:
            try:
                signal.signal(candidate, _handle_signal)
            except (OSError, ValueError):
                pass

    try:
        target = next_occurrence(cfg["_hour"], cfg["_minute"])

        if cfg["startup_delay"] > 0:
            log.info("Ожидание %d с перед первой проверкой", cfg["startup_delay"])
            stop_event.wait(cfg["startup_delay"])

        if dt.datetime.now() >= target and not stop_event.is_set():
            log.info("Время перезапуска наступило за время задержки старта")
            perform_restart(cfg, "по расписанию", state_path)
            target = next_occurrence(cfg["_hour"], cfg["_minute"])

        if cfg["start_if_not_running"] and not stop_event.is_set():
            if start_app(cfg):
                move_window_to_primary(cfg)

        log.info(
            "Следующий перезапуск: %s (через %s)",
            target.strftime("%d.%m.%Y %H:%M"),
            human_delta((target - dt.datetime.now()).total_seconds()),
        )

        while not stop_event.is_set():
            now = dt.datetime.now()
            if now >= target:
                try:
                    perform_restart(cfg, "по расписанию", state_path)
                except Exception:
                    log.exception("Ошибка при плановом перезапуске")
                target = next_occurrence(cfg["_hour"], cfg["_minute"])
                log.info(
                    "Следующий перезапуск: %s (через %s)",
                    target.strftime("%d.%m.%Y %H:%M"),
                    human_delta((target - dt.datetime.now()).total_seconds()),
                )

            remaining = (target - dt.datetime.now()).total_seconds()
            stop_event.wait(max(0.5, min(remaining, 30.0)))
    finally:
        write_state(state_path, daemon_pid=None, daemon_stopped_at=dt.datetime.now().isoformat(timespec="seconds"))
        singleton.release()
        log.info("Супервизор остановлен")

    return 0


# ---------------------------------------------------------------------------
# Диагностика
# ---------------------------------------------------------------------------

def next_run_text(cfg):
    target = next_occurrence(cfg["_hour"], cfg["_minute"])
    return "%s (через %s)" % (
        target.strftime("%d.%m.%Y %H:%M"),
        human_delta((target - dt.datetime.now()).total_seconds()),
    )


def print_restart_plan(cfg, config_path):
    """Показывает, что произойдёт при перезапуске, но ничего не делает."""
    pids = find_pids(cfg["process_name"])
    window = find_visible_window(cfg["process_name"])
    app_path = Path(cfg["file_to_run"])
    command = [str(app_path)] + list(cfg["app_args"])

    print("План перезапуска (проверка, ничего не выполняется)")
    print("Конфигурация: %s" % config_path)
    print("Время:        %s" % cfg["target_time"])
    print("Следующий:    %s" % next_run_text(cfg))
    print()

    if pids:
        print(
            "1. Завершить процесс %s (PID: %s)"
            % (cfg["process_name"], ", ".join(str(pid) for pid in pids))
        )
        print("   taskkill /F /T /IM %s" % cfg["process_name"])
        print("   ждать завершения до %d с" % cfg["kill_timeout"])
        if not window:
            print("   окно сейчас не найдено - после паузы будет запущен assistant.exe")
    else:
        print(
            "1. Процесс %s не запущен - завершение не требуется"
            % cfg["process_name"]
        )

    print("2. Пауза %d с" % cfg["timeout"])
    print("3. Запустить: %s" % subprocess.list2cmdline(command))
    print("   рабочая папка: %s" % app_path.parent)
    print(
        "4. Проверить, что окно открылось: до %d с, попыток запуска: %d"
        % (cfg["launch_check_seconds"], cfg["launch_retries"] + 1)
    )
    print()

    if app_path.is_file():
        print("[OK] Файл приложения найден")
    else:
        print("[ОШИБКА] Файл приложения не найден: %s" % app_path)

    if is_admin():
        print("[OK] Права администратора есть")
    else:
        print(
            "[!] Нет прав администратора: завершение процесса может быть запрещено. "
            "Автозапуск через install.bat решает эту проблему."
        )

    return 0 if app_path.is_file() else 4


def print_status(cfg, config_path):
    state = read_state(state_path_for(config_path))
    now = dt.datetime.now()

    print("%s v%s" % (APP_NAME, VERSION))
    print("Папка:        %s" % BASE_DIR)
    print("Конфигурация: %s" % config_path)
    print("Текущее время: %s" % now.strftime("%d.%m.%Y %H:%M:%S"))
    print()
    print("Время перезапуска: %s" % cfg["target_time"])
    print("Следующий запуск:  %s" % next_run_text(cfg))
    print("Ожидание после закрытия: %d с" % cfg["timeout"])
    print()

    pids = find_pids(cfg["process_name"])
    window = find_visible_window(cfg["process_name"])
    if pids:
        print(
            "Приложение: %s - ЗАПУЩЕНО (PID: %s)"
            % (cfg["process_name"], ", ".join(str(pid) for pid in pids))
        )
        if window:
            print("Окно:       «%s» открыто" % window["title"])
        else:
            remote = find_visible_window(cfg["process_name"], main_only=False)
            if remote:
                print(
                    "Окно:       главное не найдено (открыто: «%s»)" % remote["title"]
                )
            else:
                print("Окно:       НЕ НАЙДЕНО (процесс работает в фоне)")
    else:
        print("Приложение: %s - НЕ ЗАПУЩЕНО" % cfg["process_name"])

    app_path = Path(cfg["file_to_run"])
    if app_path.is_file():
        print("Файл:       %s - найден" % app_path)
    else:
        print("Файл:       %s - НЕ НАЙДЕН" % app_path)

    print()

    daemon_pid = state.get("daemon_pid")
    daemon_alive = False
    if daemon_pid:
        daemon_name = process_info_by_pid(daemon_pid)
        daemon_alive = daemon_name.casefold() in (
            "python.exe",
            "pythonw.exe",
            "rebootapp.exe",
        )
    if daemon_alive:
        print(
            "Супервизор: работает (PID %s, запущен %s)"
            % (daemon_pid, format_datetime(state.get("daemon_started_at")))
        )
    else:
        print("Супервизор: не запущен")
        print("  Запустите: control.bat start")

    last_restart = state.get("last_restart_at")
    if last_restart:
        result = "успешно" if state.get("last_result") == "ok" else "С ОШИБКОЙ"
        print(
            "Последний перезапуск: %s - %s"
            % (format_datetime(last_restart), result)
        )
        if state.get("last_message") and state.get("last_result") != "ok":
            print("  %s" % state["last_message"])
    else:
        print("Последний перезапуск: ещё не выполнялся")

    print()
    print("Лог:        %s" % LOG_PATH)
    return 0


def check_config(cfg, config_path):
    problems = 0
    warnings = 0

    print("Проверка конфигурации: %s" % config_path)
    print("  target_time:  %s" % cfg["target_time"])
    print("  process_name: %s" % cfg["process_name"])
    print("  file_to_run:  %s" % cfg["file_to_run"])
    print("  timeout:      %d с" % cfg["timeout"])
    print()

    app_path = Path(cfg["file_to_run"])
    if app_path.is_file():
        print("[OK] Файл приложения найден")
    else:
        print("[ОШИБКА] Файл приложения не найден: %s" % app_path)
        print("         Исправьте file_to_run в config.json")
        problems += 1

    if not app_path.name.lower().endswith(".exe"):
        print("[ПРЕДУПРЕЖДЕНИЕ] file_to_run указывает не на .exe файл")
        warnings += 1

    if not is_admin():
        print("[ПРЕДУПРЕЖДЕНИЕ] Нет прав администратора - завершение процесса может быть запрещено")
        warnings += 1

    if sys.version_info < (3, 8):
        print("[ОШИБКА] Требуется Python 3.8 или новее")
        problems += 1
    else:
        print("[OK] Python %s" % sys.version.split()[0])

    print()
    if problems:
        print("Итог: найдено ошибок - %d" % problems)
        return 4
    if warnings:
        print("Итог: конфигурация в порядке, предупреждений - %d" % warnings)
    else:
        print("Итог: конфигурация в порядке")
    return 0


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="script.py",
        description="Ежедневный перезапуск приложения по расписанию.",
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH_DEFAULT),
        help="путь к config.json (по умолчанию рядом со скриптом)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daemon", action="store_true", help="запустить супервизор")
    group.add_argument(
        "--restart-now", action="store_true", help="перезапустить приложение сейчас"
    )
    group.add_argument(
        "--ensure-running",
        action="store_true",
        help="запустить приложение, если оно не запущено",
    )
    group.add_argument("--status", action="store_true", help="показать состояние")
    group.add_argument("--check", action="store_true", help="проверить конфигурацию")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать план перезапуска, ничего не выполняя",
    )
    group.add_argument(
        "--init-config", action="store_true", help="создать config.json по умолчанию"
    )
    group.add_argument("--version", action="store_true", help="показать версию")
    return parser


def main(argv=None):
    configure_std_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging("INFO")

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    if args.version:
        print("%s %s" % (APP_NAME, VERSION))
        return 0

    if args.init_config:
        return init_config(config_path)

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        log.error("Ошибка конфигурации: %s", exc)
        return 2

    set_log_level(cfg["log_level"])
    state_path = state_path_for(config_path)

    if args.check:
        return check_config(cfg, config_path)

    if args.dry_run:
        return print_restart_plan(cfg, config_path)

    if args.status:
        print_status(cfg, config_path)
        return 0

    if not IS_WINDOWS:
        log.error("Скрипт предназначен для Windows")
        print("Скрипт предназначен для Windows", file=sys.stderr)
        return 1

    if args.restart_now:
        success = perform_restart(cfg, "вручную", state_path)
        print()
        print("Готово" if success else "Ошибка: перезапуск не выполнен, смотрите лог")
        return 0 if success else 1

    if args.ensure_running:
        success = start_app(cfg, "Проверка приложения")
        if success:
            move_window_to_primary(cfg)
        print("Приложение запущено" if success else "Не удалось запустить приложение")
        return 0 if success else 1

    try:
        return run_daemon(cfg, state_path)
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception("Критическая ошибка")
        return 1


if __name__ == "__main__":
    sys.exit(main())
