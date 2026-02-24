import time
import subprocess
import schedule
import datetime
import json

with open('config.json', 'r', encoding='utf-8') as file:
    config = json.load(file)

target_time_conf = config["target_time"]
process_name_conf = config["process_name"]
file_to_run_conf = config["file_to_run"]
timeout_conf = config["timeout"]

<<<<<<< HEAD
def format_time(time_str):
    parts = time_str.split(':')
    if len(parts) == 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return time_str

def main():
    target_time = format_time(target_time_conf)
=======

def main():
    target_time = target_time_conf
>>>>>>> 023cf553edc067243c4d6775a58f228c7d8ff94f
    schedule_task_daily(target_time)

def schedule_task_daily(target_time):
    schedule.every().day.at(target_time).do(execute_task)
    print(f"Задача заплпанирована на ежедневное выполнение в {target_time}"
          f"\nПрограмма работает. Нажмите Ctrl+C для выхода")

    while True:
        schedule.run_pending()
        time.sleep(1)

def kill_process(process_name):
    print(f"\n[ДЕЙСТВИЕ] Завершаем процесс '{process_name}'...")
    try:
        attempts = [
            f'taskkill /F /IM "{process_name}"',
            f'taskkill /F /IM {process_name}',
            f'powershell "Get-Process {process_name} -ErrorAction SilentlyContinue | Stop-Process -Force"',
            f"powershell \"Stop-Process -Name '{process_name}' -Force -ErrorAction SilentlyContinue\""
        ]

        for i, attempt in enumerate(attempts, 1):
            print(f"\nПопытка {i}: {attempt}")
            result = subprocess.run(attempt, shell=True, capture_output=True, text=True, encoding='cp866')

            if result.returncode == 0:
                print("Успешный успех")
                break
            elif "not found" in result.stderr.lower() or "не найдено" in result.stderr.lower():
                print("Процес не найден")
            else:
                print(f"Результат: {result.stderr[:100]}...")

    except Exception as e:
        print(f"ФАТАЛ ЕРОР: {e}")

    # 2. Ждём 1 минуту
    print("\n" + "=" * 60)
    print(f"ОЖИДАНИЕ {timeout_conf} СЕКУНД")
    print("=" * 60)

    for i in range(timeout_conf, 0, -1):
        print(f"Осталось: {i:2d} секунд", end='\r')
        time.sleep(1)
    print("\nОжидание завершено!")


def diagnose_process(process_name):
    """Диагностика: что видит система?"""
    print("\n" + "=" * 60)
    print("ДИАГНОСТИКА ПРОЦЕССОВ")
    print("=" * 60)

    # 1. Tasklist
    print("\n1. Результат tasklist:")
    result = subprocess.run('tasklist', shell=True, capture_output=True, text=True, encoding='cp866')
<<<<<<< HEAD
    print(result.stdout[:2000])

    # 2. Поиск процесса
=======
    print(result.stdout[:2000])  # Первые 2000 символов

    # 2. Поиск конкретного процесса
>>>>>>> 023cf553edc067243c4d6775a58f228c7d8ff94f
    print(f"\n2. Поиск '{process_name}':")
    cmd = f'tasklist | findstr /i "{process_name}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='cp866')
    if result.stdout:
        print("Найден в tasklist:")
        print(result.stdout)
    else:
        print("Не найден в tasklist")

    # 3. WMIC (более детальная информация)
    print(f"\n3. Информация WMIC о '{process_name}':")
    cmd = f'wmic process where "name like \'%{process_name}%\'" get Name,ProcessId,CommandLine,ExecutablePath'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='cp866')
    print(result.stdout if result.stdout else "Не найдено через WMIC")

    # 4. PowerShell (ИСПРАВЛЕННАЯ СТРОКА)
    print(f"\n4. Поиск через PowerShell:")
<<<<<<< HEAD
    ps_name = process_name.replace('.exe', '')
    cmd = f'powershell "Get-Process {ps_name} -ErrorAction SilentlyContinue | Format-Table Id,Name,Path"'

=======

    # Способ 1: Без звездочки (проще)
    ps_name = process_name.replace('.exe', '')
    cmd = f'powershell "Get-Process {ps_name} -ErrorAction SilentlyContinue | Format-Table Id,Name,Path"'

    # ИЛИ Способ 2: С правильным экранированием
    # cmd = f'powershell "Get-Process *{ps_name}* -ErrorAction SilentlyContinue | Format-Table Id,Name,Path"'

>>>>>>> 023cf553edc067243c4d6775a58f228c7d8ff94f
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='cp866')
    print(result.stdout if result.stdout else "Не найдено через PowerShell")

def execute_task():
    print(f"[{datetime.datetime.now()}]: Завершаем задачу...")

    diagnose_process(process_name_conf)
    kill_process(process_name_conf)


    print(f"[{datetime.datetime.now()}]: Запускаем программу...")

    file_to_run = file_to_run_conf

    try:
        subprocess.Popen(file_to_run, shell=True)
        print(f"[{datetime.datetime.now()}]: Файл {file_to_run} запущен")
    except Exception as e:
        print(f"[{datetime.datetime.now()}]: Ошибка при запуске файла: {e}")

if __name__ == "__main__":
    main()