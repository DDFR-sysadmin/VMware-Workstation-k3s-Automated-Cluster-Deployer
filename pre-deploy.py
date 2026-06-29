import getpass
import json
import os
import subprocess
import sys
import time
import winreg

import requests
from colorama import Fore, Style, init
from requests.auth import HTTPBasicAuth

init(autoreset=True)

STATE_FILE = "state.json"
TFVARS_FILE = "secrets.auto.tfvars"
SECRETS_FILE = "passwords.yaml"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"step": 0, "data": {}}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)


def prompt_yn(question):
    while True:
        resp = input(f"{question} [y/n]: ").lower().strip()
        if resp in ["y", "yes"]:
            return True
        if resp in ["n", "no"]:
            return False


def find_vmware_paths():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation",
        )
        install_path, _ = winreg.QueryValueEx(key, "InstallPath")
        return {
            "exe": os.path.join(install_path, "vmware.exe"),
            "vmrun": os.path.join(install_path, "vmrun.exe"),
            "vmrest": os.path.join(install_path, "vmrest.exe"),
        }
    except WindowsError:
        print(Fore.RED + "Не удалось найти VMware в реестре.")
        sys.exit(1)


def find_default_vm_dir():
    pref_path = os.path.expandvars(r"%APPDATA%\VMware\preferences.ini")
    if os.path.exists(pref_path):
        with open(pref_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                # Приводим строку к нижнему регистру для надежного поиска
                if line.strip().lower().startswith("prefvmx.defaultvmpath"):
                    parts = line.split("=", 1)
                    if len(parts) > 1:
                        return parts[1].strip().strip('"').strip("'")
    return os.path.expandvars(r"%USERPROFILE%\Documents\Virtual Machines")


def check_dependencies():
    deps = {
        "terraform": "terraform --version",
        "gsudo": "gsudo --version",
        "wsl": "wsl -d Debian -- uname -a",
        "ansible (in WSL)": "wsl -d Debian -- ansible --version",
    }
    for name, cmd in deps.items():
        print(f"Проверка {name}...", end=" ")
        try:
            subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
            print(Fore.GREEN + "ОК")
        except subprocess.CalledProcessError:
            print(Fore.RED + "ОШИБКА")
            if prompt_yn(
                f"Зависимость {name} не найдена. Попытаться установить? (N - выход)"
            ):
                print(
                    Fore.YELLOW
                    + "Функция автоустановки для этой зависимости еще не реализована полностью. Установите вручную."
                )
                sys.exit(1)
            else:
                sys.exit(1)


def to_wsl_path(win_path):
    cmd = f'wsl -d Debian -e wslpath -a "{win_path}"'
    return subprocess.check_output(cmd, shell=True).decode().strip()


def run():
    state = load_state()

    if state["step"] > 0:
        print(Fore.YELLOW + f"Найдено сохраненное состояние (Шаг {state['step']}).")
        if not prompt_yn("Продолжить с места остановки? (N - начать сначала)"):
            state = {"step": 0, "data": {}}

    data = state["data"]

    # ШАГ 1: Пути VMware
    if state["step"] < 1:
        print(Fore.CYAN + "\nШаг 1: Поиск путей VMware")
        paths = find_vmware_paths()
        data["vmware_exe"] = paths["exe"]
        data["vmrest_exe"] = paths["vmrest"]
        data["vm_base_dir"] = find_default_vm_dir()
        print(f"Найдено: {data['vmware_exe']}\nБазовая папка VM: {data['vm_base_dir']}")

        state["step"] = 1
        state["data"] = data
        save_state(state)

        # ШАГ 2: Настройка и запуск vmrest
        if state["step"] < 2:
            print(Fore.CYAN + "\nШаг 2: Настройка API vmrest")
            api_user = input("Придумай логин для API vmrest: ")
            api_pass = getpass.getpass("Придумай пароль для API vmrest: ")

            print("Регистрация кредов в vmrest...")
            try:
                # Передаем данные в процесс vmrest -C
                p = subprocess.Popen(
                    [data["vmrest_exe"], "-C"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                # ВАЖНО: отправляем api_pass ДВАЖДЫ (для поля Password и для Retype password)
                # Также добавлил timeout=5, чтобы скрипт не вис вечно, если Windows заблокирует Pipe
                p.communicate(input=f"{api_user}\n{api_pass}\n{api_pass}\n", timeout=5)
                print(Fore.GREEN + "Креды успешно зарегистрированы автоматически.")

            except subprocess.TimeoutExpired:
                # Если за 5 секунд процесс не завершился, значит Windows заблокировал потоковый ввод пароля.
                p.kill()
                p.wait()
                print(
                    Fore.YELLOW
                    + "\n[!] Windows заблокировал автоматический ввод пароля из соображений безопасности."
                )
                print(
                    Fore.YELLOW
                    + "Пожалуйста, введите те же самые логин и пароль вручную в открывшемся интерфейсе:"
                )

                # В интерактивном режиме вводим креды напрямую
                subprocess.run([data["vmrest_exe"], "-C"])

            print("Запуск vmrest в фоне (порт 8697)...")
            # DETACHED_PROCESS = 0x00000008 для запуска в фоне без окна
            subprocess.Popen([data["vmrest_exe"]], creationflags=0x00000008)
            time.sleep(3)  # Ждем, пока API поднимется

            data["api_user"] = api_user
            data["api_pass"] = api_pass
            state["step"] = 2
            state["data"] = data
            save_state(state)

    # ШАГ 3: Поиск Debian ID
    if state["step"] < 3:
        print(Fore.CYAN + "\nШаг 3: Поиск образа Debian")
        try:
            res = requests.get(
                "http://127.0.0.1:8697/api/vms",
                auth=HTTPBasicAuth(data["api_user"], data["api_pass"]),
            )
            res.raise_for_status()
            vms = res.json()
            debian_id = None
            for vm in vms:
                if "debian" in vm.get("path", "").lower():
                    debian_id = vm.get("id")
                    print(
                        Fore.GREEN + f"Найден Debian ID: {debian_id} ({vm.get('path')})"
                    )
                    break
            # Лично мне этот блок не разу не пригодился, но пусть будет на всякий случай, просит интерактивно ввести id Golden Image c гугл диска
            if not debian_id:
                debian_id = input(
                    Fore.YELLOW
                    + "Образ Debian не найден автоматически. Введите ID вручную: "
                )

            data["parent_id"] = debian_id
            state["step"] = 3
            state["data"] = data
            save_state(state)
        except Exception as e:
            print(Fore.RED + f"Ошибка API vmrest: {e}")
            sys.exit(1)

    # ШАГ 4: Генерация конфигов (tfvars и secrets.yaml)
    if state["step"] < 4:
        print(Fore.CYAN + "\nШаг 4: Генерация файлов конфигурации")

        master_pass = getpass.getpass("Пароль для ОС master-ноды: ")
        worker_pass = getpass.getpass("Пароль для ОС worker-нод: ")

        with open(TFVARS_FILE, "w", encoding="utf-8") as f:
            f.write(f'vmware_username = "{data["api_user"]}"\n')
            f.write(f'vmware_password = "{data["api_pass"]}"\n')
            # \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
            escaped_vm_dir = data["vm_base_dir"].replace(chr(92), chr(92) + chr(92))
            f.write(f'vm_base_dir = "{escaped_vm_dir}"\n')
            f.write(f'parent_id_deb = "{data["parent_id"]}"\n')
            f.write(
                f'vmware_exe_path = "{data["vmware_exe"].replace(chr(92), chr(92) + chr(92))}"\n'
            )
        print(Fore.GREEN + f"Файл {TFVARS_FILE} создан.")

        with open(SECRETS_FILE, "w", encoding="utf-8") as f:
            f.write(f'master_password: "{master_pass}"\n')
            f.write(f'workers_password: "{worker_pass}"\n')
        print(Fore.GREEN + f"Файл {SECRETS_FILE} создан (пока в открытом виде).")

        state["step"] = 4
        state["data"] = data
        save_state(state)

    # ШАГ 5: Зависимости и WSL (Ansible Vault & SSH)
    if state["step"] < 5:
        print(Fore.CYAN + "\nШаг 5: Проверка зависимостей и WSL")
        check_dependencies()

        print("Генерация SSH ключа ed25519 (если нет)...")
        subprocess.run(
            "wsl -d Debian -e bash -c \"if [ ! -f ~/.ssh/id_ed25519 ]; then ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''; fi\"",
            shell=True,
        )

        print("Шифрование secrets.yaml через ansible-vault...")
        vault_pass = getpass.getpass("Придумайте пароль для ansible-vault: ")

        # Сохраняем пароль во временный файл в WSL
        wsl_secrets_path = to_wsl_path(os.path.abspath(SECRETS_FILE))
        cmd = f'wsl -d Debian -e bash -c "echo {vault_pass} > /tmp/.vp && ansible-vault encrypt {wsl_secrets_path} --vault-password-file /tmp/.vp && rm /tmp/.vp"'
        subprocess.run(cmd, shell=True)
        print(Fore.GREEN + "Файл secrets.yaml зашифрован")

        state["step"] = 6
        state["data"] = data
        save_state(state)
        print(Fore.GREEN + "\nПОДГОТОВКА УСПЕШНО ЗАВЕРШЕНА")


if __name__ == "__main__":
    run()
