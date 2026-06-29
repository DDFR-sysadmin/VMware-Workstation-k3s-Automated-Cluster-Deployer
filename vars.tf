variable "vmware_username" {
  type = string
}

variable "vmware_password" {
  type      = string
  sensitive = true
}

variable "vm_base_dir" {
  type        = string
  description = "Абсолютный путь к папке на диске, где будут храниться файлы виртуальных машин"
}

variable "parent_id_deb" {
  type = string
  description = "ID-шик эталонного образа "
}

variable "vmware_exe_path" {
  type        = string
  description = "Путь к исполняемому файлу VMware Workstation GUI"
}

variable "count_of_workers" {
  type        = number
  description = "Количество worker-нод для кластера"
  default     = 2
}
