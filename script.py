import time
import subprocess

def main():
    print("Завершаем задачу...")

    process_name = "assistant.exe"
    try:
        subprocess.run(['taskkill', '/F', '/IM', process_name], check=True)
        print(f"Процесс {process_name} завершён")
    except subprocess.CalledProcessError as e:
        print(f"Процесс {process_name} не может быть завершен\n{e}")

    time.sleep(60)

    print("Запускаем программу...")

    file_to_run = "path/to_file.exe"

    try:
        subprocess.Popen(file_to_run, shell=True)
        print(f"Файл {file_to_run} запущен")
    except Exception as e:
        print(f"Ошибка при запуске файла: {e}")


if __name__ == "__main__":
    main()