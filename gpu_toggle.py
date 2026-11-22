import subprocess
import sys
import ctypes
import os
import re

# 隐藏子进程窗口（Windows 专用）
CREATE_NO_WINDOW = 0x08000000
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = subprocess.SW_HIDE

# ============================================
# 手动后备 ID：仅在自动发现失败时使用
# 正常情况下无需修改，留占位符即可
# ============================================
MANUAL_GPU_ID = r"PCI\VEN_XXXX&DEV_XXXX&SUBSYS_XXXXXXXX&REV_XX\XXXXXXXXXXXXXXXXXX"

# PCI 厂商 ID
VENDOR_NVIDIA = "10DE"
VENDOR_AMD = "1002"


def log(msg):
    """日志已禁用，此函数为空操作"""
    pass


def run_command(cmd):
    """静默执行命令，返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            startupinfo=startupinfo,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)


def find_discrete_gpu_id():
    """
    通过解析 pnputil 输出自动查找独立显卡的实例 ID。
    识别依据：实例 ID 中的 PCI 厂商 ID 为 10DE(NVIDIA) 或 1002(AMD)。
    返回: 实例 ID 字符串，未找到则返回 None
    """
    rc, stdout, _ = run_command(["pnputil", "/enum-devices", "/class", "Display"])
    if rc != 0:
        return None

    # 按空行分块，每块代表一个设备
    blocks = re.split(r"\r?\n\s*\r?\n", stdout.strip())

    # 实例 ID 行匹配（中英文 + 全角/半角冒号兼容）
    # 英文: "Instance ID:            PCI\VEN_..."
    # 中文: "实例 ID:                PCI\VEN_..."
    id_pattern = re.compile(
        r"(?:Instance ID|Device Instance ID|实例 ID|设备实例 ID)\s*[:：]\s*(PCI\\[^\s]+)",
        re.IGNORECASE,
    )

    for block in blocks:
        id_match = id_pattern.search(block)
        if not id_match:
            continue
        instance_id = id_match.group(1).strip()

        # 从实例 ID 中提取 PCI 厂商 ID
        ven_match = re.search(r"VEN_([0-9A-Fa-f]{4})", instance_id)
        if not ven_match:
            continue
        vendor = ven_match.group(1).upper()

        if vendor in (VENDOR_NVIDIA, VENDOR_AMD):
            return instance_id

    return None


def get_device_status(instance_id):
    """
    精确查询单个设备的状态行。
    返回: "enabled" / "disabled" / None(查询失败或无法判断)
    兼容中英文系统：
      英文: Status:   Started / Disabled
      中文: 状态:     已启动 / 已禁用
    """
    rc, stdout, _ = run_command([
        "pnputil", "/enum-devices", "/instanceid", instance_id
    ])
    if rc != 0:
        return None

    for line in stdout.splitlines():
        low = line.lower()
        if "status" in low or "状态" in line:
            if "started" in low or "已启动" in line or "已启用" in line:
                return "enabled"
            if "disabled" in low or "已禁用" in line or "已停用" in line:
                return "disabled"
    return None


def toggle_gpu(instance_id):
    """检测当前状态并执行相反的切换操作"""
    status = get_device_status(instance_id)

    if status == "enabled":
        rc, _, _ = run_command(["pnputil", "/disable-device", instance_id])
        return rc == 0

    elif status == "disabled":
        rc, _, _ = run_command(["pnputil", "/enable-device", instance_id])
        return rc == 0

    else:
        # 状态无法判断时的兜底：优先尝试启用，避免显卡卡在禁用状态
        rc, _, _ = run_command(["pnputil", "/enable-device", instance_id])
        return rc == 0


if __name__ == "__main__":
    # 自动请求管理员权限
    if not ctypes.windll.shell32.IsUserAnAdmin():
        script = os.path.abspath(sys.argv[0])
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', None, 0
        )
        sys.exit()

    # 自动发现独显实例 ID
    gpu_id = find_discrete_gpu_id()

    # 自动发现失败时回退到手动 ID
    if not gpu_id:
        gpu_id = MANUAL_GPU_ID

    # 若仍为占位符（说明既无独显也无法自动获取），直接退出避免误操作
    if "XXXX" in gpu_id:
        sys.exit(1)

    toggle_gpu(gpu_id)
