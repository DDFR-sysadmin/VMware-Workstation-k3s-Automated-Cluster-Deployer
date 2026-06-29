terraform {
  required_providers {
    vmworkstation = {
      source  = "elsudano/vmworkstation"
      version = "2.0.1"
    }
  }
}

locals {
  vmx_target_path = "${var.vm_base_dir}\\k8s-master-tf\\k8s-master-tf.vmx"
}

provider "vmworkstation" {
  endpoint = "http://127.0.0.1:8697/api"
  username = var.vmware_username
  password = var.vmware_password
  https    = false
  debug    = "NONE"
}

# ==========================================
# 1. МАСТЕР НОДА
# ==========================================
resource "vmworkstation_virtual_machine" "k8s-master-tf" {
  sourceid     = var.parent_id_deb
  denomination = "k8s-master-tf"
  path         = local.vmx_target_path
  processors   = 2
  memory       = 4096
  state        = "off"

  provisioner "local-exec" {
    command     = <<EOF
      $vmrun = "${var.vmware_exe_path}".Replace("vmware.exe", "vmrun.exe")
      & $vmrun -T ws start "${local.vmx_target_path}" gui
    EOF
    interpreter = ["PowerShell", "-Command"]
  }
}

# ==========================================
# 2. ВОРКЕР НОДЫ (Динамический блок)
# ==========================================
resource "vmworkstation_virtual_machine" "k8s_worker" {
  count = var.count_of_workers

  sourceid     = var.parent_id_deb
  denomination = "k8s-worker-${count.index + 1}"
  path         = "${var.vm_base_dir}\\k8s-worker-${count.index + 1}\\k8s-worker-${count.index + 1}.vmx"
  processors   = 3
  memory       = 8192
  state        = "off"

  provisioner "local-exec" {
    command     = <<EOF
      $vmrun = "${var.vmware_exe_path}".Replace("vmware.exe", "vmrun.exe")
      & $vmrun -T ws start "${var.vm_base_dir}\k8s-worker-${count.index + 1}\k8s-worker-${count.index + 1}.vmx" gui
    EOF
    interpreter = ["PowerShell", "-Command"]
  }

  # Ждем создания мастера. А флаг -parallelism=1 выстроит сами воркеры в очередь.
  depends_on = [vmworkstation_virtual_machine.k8s-master-tf]
}

# ==========================================
# 3. ГЕНЕРАЦИЯ inventory.ini ДЛЯ ANSIBLE
# ==========================================
resource "null_resource" "generate_inventory" {

  triggers = {
    always_run = "${timestamp()}"
  }

  provisioner "local-exec" {
    command     = <<EOF
      $vmrun = "${var.vmware_exe_path}".Replace("vmware.exe", "vmrun.exe")

      # Функция, которая будет крутиться в цикле, пока ОС полностью не загрузится и не отдаст IP по DHCP
      function Get-ValidIP {
          param([string]$vmxPath, [string]$nodeName)
          Write-Host "Ожидаем полную загрузку Debian и запуск сетей для $nodeName..." -ForegroundColor Cyan

          while ($true) {
              $output = (& $vmrun -T ws getGuestIPAddress "$vmxPath") 2>&1

              if ($output -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
                  $clean_ip = $output.Trim()
                  Write-Host "   [$nodeName] ОС загружена, Пойман IP: $clean_ip" -ForegroundColor Green
                  return $clean_ip
              }

              $short_err = if ($output.Length -gt 50) { $output.Substring(0,50) + "..." } else { $output }
              Write-Host "   [$nodeName] Ждем (в консоли VMware: $short_err)" -ForegroundColor Gray
              Start-Sleep -Seconds 5
          }
      }

      # 1. Запрашиваем IP мастера
      $master_ip = Get-ValidIP "${local.vmx_target_path}" "k8s-master"

      # 2. Формируем начало файла
      $inventory = "[masters]`nk8s-master ansible_host=$master_ip`n`n[workers]"

      # 3. В цикле запрашиваем IP для всех сгенерированных воркеров
      $worker_count = ${var.count_of_workers}
      $base_dir = "${var.vm_base_dir}"

      for ($i = 1; $i -le $worker_count; $i++) {
          $nodeName = "k8s-worker-$i"
          $vmxPath = "$base_dir\$nodeName\$nodeName.vmx"
          $ip = Get-ValidIP $vmxPath $nodeName
          $inventory += "`n$nodeName ansible_host=$ip"
      }

      # 4. Добавляем переменные Ansible
      $inventory += "`n`n[all:vars]`nansible_user=user`nansible_password=password`nansible_become=true`nansible_become_method=sudo`nansible_become_password=password"

      # 5. Записываем готовый файл
      $inventory | Out-File -FilePath "${path.module}\inventory.ini" -Encoding ascii
      Write-Host "Файл inventory.ini успешно создан" -ForegroundColor Green
    EOF
    interpreter = ["PowerShell", "-Command"]
  }

  # Этот блок ждет завершения создания И мастера, И всех элементов массива воркеров
  depends_on = [
    vmworkstation_virtual_machine.k8s-master-tf,
    vmworkstation_virtual_machine.k8s_worker
  ]
}
