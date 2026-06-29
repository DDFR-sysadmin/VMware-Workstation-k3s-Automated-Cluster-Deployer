$ErrorActionPreference = "Stop"

function Check-Command ($cmd)
{
    return (Get-Command $cmd -ErrorAction SilentlyContinue) -ne $null
}

Write-Host "=== Проверка базового окружения ===" -ForegroundColor Cyan

# === Проверка и установка winget ===
if (-not (Check-Command "winget"))
{
    Write-Host "winget не найден. Попытка установить..." -ForegroundColor Yellow
    try
    {
        $url = "https://github.com/microsoft/winget-cli/releases/latest/download/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle"
        $outPath = "$env:TEMP\winget.msixbundle"

        Write-Host "Скачивание установщика winget..." -ForegroundColor Gray
        Invoke-WebRequest -Uri $url -OutFile $outPath

        Write-Host "Установка пакета..." -ForegroundColor Gray
        Add-AppxPackage -Path $outPath

        Remove-Item $outPath
        Write-Host "winget успешно установлен! Перезапустите терминал и запустите скрипт заново." -ForegroundColor Red
        exit
    } catch
    {
        Write-Host "Ошибка при автоматической установке winget: $_" -ForegroundColor Red
        Write-Host "Пожалуйста, установите winget вручную (https://github.com/microsoft/winget-cli) и повторите попытку." -ForegroundColor Yellow
        exit
    }
}

# === Проверка и установка Python ===
if (-not (Check-Command "python"))
{
    Write-Host "Python не найден. Пытаюсь установить через winget..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    Write-Host "Python установлен. Перезапустите терминал и запустите скрипт заново." -ForegroundColor Red
    exit
}

# === Проверка и установка pip ===
if (-not (Check-Command "pip"))
{
    Write-Host "pip не найден. Попоытка установить" -ForegroundColor Yellow
    try
    {
        # Инициализируем pip через встроенный модуль ensurepip
        python -m ensurepip --default-pip --quiet
        python -m pip install --upgrade pip -q
        Write-Host "pip успешно установлен и обновлен." -ForegroundColor Green
    } catch
    {
        Write-Host "Не удалось автоматически установить pip: $_" -ForegroundColor Red
        Write-Host "Попробуйте запустить: python -m ensurepip --default-pip вручную." -ForegroundColor Yellow
        exit
    }
}

Write-Host "Установка зависимостей Python..." -ForegroundColor Cyan
# Используем безопасный вызов через 'python -m pip', чтобы избежать проблем с PATH
python -m pip install -r requirements.txt -q

while ($true)
{
    Write-Host "`n=== K3S VMware Workstation Cluster Deployer ===" -ForegroundColor Green
    Write-Host "1. Запустить подготовку (pre-deploy.py)"
    Write-Host "2. Запустить деплой (deploy.py)"
    Write-Host "3. Выход"
    $choice = Read-Host "Выберите действие (1-3)"

    switch ($choice)
    {
        "1"
        {
            python pre-deploy.py
            $next = Read-Host "`nПодготовка завершена. Запустить деплой? (Y/n)"
            if ($next -notmatch "^[nN]$")
            { python deploy.py
            }
        }
        "2"
        { python deploy.py
        }
        "3"
        { exit
        }
        default
        { Write-Host "Неверный выбор" -ForegroundColor Red
        }
    }
}
