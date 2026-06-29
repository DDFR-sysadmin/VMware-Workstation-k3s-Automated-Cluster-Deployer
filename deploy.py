import getpass
import json
import os
import subprocess
import sys

from colorama import Fore, Style, init

init(autoreset=True)

STATE_FILE = "state.json"


def to_wsl_path(win_path):
    cmd = f'wsl -d Debian -e wslpath -a "{win_path}"'
    return subprocess.check_output(cmd, shell=True).decode().strip()


def run():
    if not os.path.exists(STATE_FILE):
        print(Fore.RED + "State-файл не найден. Сначала нужно выполнить pre-deploy.py")
        sys.exit(1)

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    if state.get("step", 0) < 6:
        print(
            Fore.RED
            + "Подготовка (pre-deploy) не была завершена до конца. Сначала нужно её закончить."
        )
        sys.exit(1)

    print(Fore.CYAN + "=== 1. TERRAFORM DEPLOY ===")

    # Terraform init
    subprocess.run(["terraform", "init"], check=True)

    # Terraform plan
    print(Fore.YELLOW + "\nФормирование плана...")
    subprocess.run(["terraform", "plan", "-out=tfplan"], check=True)

    # Terraform apply
    _ = input(
        Fore.YELLOW
        + "\nНажмите Enter для запуска Terraform Apply (это поднимет виртуалки и сгенерирует inventory.ini)..."
    )
    subprocess.run(["terraform", "apply", "tfplan"], check=True)

    print(Fore.GREEN + "\nИнфраструктура поднята. Переходим к Ansible.")

    if not os.path.exists("inventory.ini"):
        print(
            Fore.RED
            + "Файл inventory.ini не найден! Проверьте отработал ли provisioner в Terraform."
        )
        sys.exit(1)

    # =========================================================================
    # АВТОМАТИЧЕСКАЯ ОЧИСТКА KNOWN_HOSTS В WSL
    # =========================================================================
    # Этот блок был добавелен для удобства так как скрипт запускался несколько раз что бы не зачищать каждый раз ключи ssh нахуя я всё это пишу эту хуйню всё равно никто читать не будет как же я хочу найтись на DevOps работу ааааа блять
    print(Fore.YELLOW + "\nОчистка старых SSH-ключей (known_hosts) в WSL...")
    import re

    try:
        with open("inventory.ini", "r", encoding="utf-8") as f:
            inv_text = f.read()

        # Находим все IP-адреса, прописанные в ansible_host=
        ips = re.findall(r"ansible_host=([0-9.]+)", inv_text)

        if ips:
            for ip in ips:
                # Вызываем ssh-keygen -R для каждого IP напрямую внутри дистрибутива Debian
                try:
                    subprocess.run(
                        f"wsl -d Debian -e ssh-keygen -R {ip}",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    print(f"ключ для {ip} не был сгенерирован до этого\n")

            print(
                Fore.GREEN + f"[+] Хосты очищены в ~/.ssh/known_hosts: {', '.join(ips)}"
            )
        else:
            print(
                Fore.YELLOW
                + "[!] В inventory.ini не обнаружено IP-адресов для очистки."
            )
    except Exception as e:
        print(Fore.RED + f"[!] Не удалось сбросить SSH-ключи: {e}")
    # =========================================================================

    print(Fore.CYAN + "\n=== 2. ANSIBLE DEPLOY ===")
    vault_pass = getpass.getpass(
        "Введите пароль от ansible-vault (который был задан на этапе pre-deploy): "
    )

    # Транслируем пути для WSL
    wsl_inventory = to_wsl_path(os.path.abspath("inventory.ini"))
    wsl_playbook = to_wsl_path(os.path.abspath("k3s_deploy.yml"))

    ansible_cmd = (
        f'wsl -d Debian -e bash -c "'
        f"export ANSIBLE_HOST_KEY_CHECKING=False; "
        f"echo {vault_pass} > /tmp/.vp && "
        f"ansible-playbook -i {wsl_inventory} {wsl_playbook} --vault-password-file /tmp/.vp; "
        f'rm /tmp/.vp"'
    )

    print(Fore.YELLOW + f"Запуск Ansible внутри WSL...\n")
    # Используем shell=True, чтобы WSL корректно подхватил всю команду с пайпами
    result = subprocess.run(ansible_cmd, shell=True)

    if result.returncode == 0:
        print(Fore.GREEN + "\nДеплой k3s кластера успешно завершен!")
    else:
        print(Fore.RED + f"\nAnsible завершился с ошибкой (код {result.returncode}).")


if __name__ == "__main__":
    run()
