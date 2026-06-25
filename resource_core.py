import os
import subprocess
import json
from datetime import datetime

import psutil
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

def get_static_gpu_info():
    try:
        # PowerShell로 GPU 하드웨어 사양 쿼리
        result = subprocess.run(
            ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        
        data = json.loads(result.stdout.strip())
        if isinstance(data, dict):
            data = [data]
            
        gpus = []
        for item in data:
            name = item.get("Name", "Unknown GPU")
            ram_bytes = item.get("AdapterRAM")
            if ram_bytes is None or ram_bytes < 0:
                ram_mb = 0.0
            else:
                ram_mb = float(ram_bytes) / (1024 ** 2)
            
            gpus.append({
                "name": name,
                "mem_total_mb": ram_mb,
                "util_percent": 0.0,
                "mem_used_mb": 0.0,
                "temp_c": 0.0,
                "static_only": True
            })
        return gpus
    except Exception:
        return []


SYSTEM_PROMPT = """당신은 컴퓨터 자원 최적화를 돕는 전문 AI 어시스턴트입니다.
사용자로부터 CPU, RAM, GPU, 디스크 사용량과 상위 프로세스 목록을 전달받습니다.
다음 관점으로 분석해서 한국어로 간결하게 답변하세요.

1. 현재 낭비되고 있거나 비정상적으로 자원을 많이 쓰는 프로세스가 있는지
2. RAM/디스크/GPU 중 여유가 부족하거나 과도하게 남는 자원이 있는지
3. 더 효율적으로 자원을 쓰기 위한 구체적이고 실행 가능한 조치

불필요한 군더더기 설명 없이 항목별 bullet로 작성하고, 심각도가 높은 항목을 먼저 언급하세요.

[🔥 핵심 지시사항 - 능동적인 시스템 제어 태그 사용 필수]
사용자에게 "작업 관리자에서 프로세스를 종료하세요"와 같이 말로만 제안하지 마십시오.
당신이 프로세스를 끄거나 파일을 삭제해야 한다고 판단했다면, 답변 텍스트의 **맨 마지막**에 반드시 다음 형식의 시스템 제어 태그를 직접 적으십시오. 
시스템이 이 태그를 인식하여 즉각 사용자 승인 후 조치할 것입니다.

- 프로세스 종료 시: [COMMAND:KILL_PROCESS:PID] (예: [COMMAND:KILL_PROCESS:1234])
- 파일 삭제 시: [COMMAND:DELETE_FILE:파일의절대경로] (예: [COMMAND:DELETE_FILE:C:\temp\dummy.txt])

[🚫 절대 금지 사항]
1. `python.exe` 프로세스는 이 자원 어드바이저 앱 자체를 구동하는 핵심 프로세스이므로 **어떠한 경우에도 종료 태그를 발급하지 마십시오.** (자신을 끄게 됩니다)
2. 시스템을 망가뜨릴 수 있는 핵심 프로세스(explorer.exe, svchost.exe 등)나 Windows 시스템 폴더 내 파일에 대해서는 절대 제어 태그를 발급하지 마세요.
"""

AVAILABLE_MODELS = [
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.0-flash-001"
]


def get_gpu_snapshot():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        gpus = []
        for line in result.stdout.strip().splitlines():
            name, util, mem_used, mem_total, temp = [v.strip() for v in line.split(",")]
            gpus.append({
                "name": name,
                "util_percent": float(util),
                "mem_used_mb": float(mem_used),
                "mem_total_mb": float(mem_total),
                "temp_c": float(temp)
            })
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


def get_disk_snapshot():
    disks = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append({
            "mount": part.mountpoint,
            "total_gb": usage.total / (1024 ** 3),
            "used_gb": usage.used / (1024 ** 3),
            "percent": usage.percent
        })
    return disks


class ResourceMonitor:
    """CPU/RAM/GPU/디스크/프로세스 스냅샷을 수집한다.

    프로세스별 CPU 사용률은 두 번의 측정 사이 시간차가 필요하므로
    psutil.Process 객체를 인스턴스에 캐싱해 호출 시점 간 비교가 가능하게 한다.
    """

    def __init__(self):
        self.proc_cache = {}
        # 최초 CPU 측정 기준점 설정
        psutil.cpu_percent(interval=None)
        # static GPU 정보 로드
        self.static_gpus = get_static_gpu_info()

    def get_process_snapshot(self, top_n=7):
        cache = self.proc_cache
        live_pids = set()
        rows = []

        current_pid = os.getpid()
        for pid in psutil.pids():
            if pid == current_pid:
                continue
            live_pids.add(pid)
            item = cache.get(pid)

            if item is None:
                try:
                    proc = psutil.Process(pid)
                    name = proc.name()
                    proc.cpu_percent(interval=None)  # 측정 기준점 설정
                    cache[pid] = {"proc": proc, "name": name}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                continue  # 이번 회차에는 기준점만 잡고 다음 회차부터 사용

            try:
                proc_obj = item["proc"]
                name = item["name"]
                rows.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": proc_obj.cpu_percent(interval=None),
                    "mem_percent": proc_obj.memory_percent()
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        for pid in list(cache.keys()):
            if pid not in live_pids:
                del cache[pid]

        top_cpu = sorted(rows, key=lambda r: r["cpu_percent"], reverse=True)[:top_n]
        top_mem = sorted(rows, key=lambda r: r["mem_percent"], reverse=True)[:top_n]
        return top_cpu, top_mem

    def get_snapshot(self):
        mem = psutil.virtual_memory()
        top_cpu, top_mem = self.get_process_snapshot()

        gpus = get_gpu_snapshot()
        if not gpus:
            gpus = self.static_gpus

        return {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "mem_total_gb": mem.total / (1024 ** 3),
            "mem_used_gb": mem.used / (1024 ** 3),
            "mem_percent": mem.percent,
            "disks": get_disk_snapshot(),
            "gpus": gpus,
            "top_cpu": top_cpu,
            "top_mem": top_mem
        }


def snapshot_to_text(snap):
    lines = [f"[측정 시각 {snap['timestamp']}]"]
    lines.append(f"CPU 사용률: {snap['cpu_percent']:.1f}%")
    lines.append(
        f"RAM: {snap['mem_used_gb']:.1f} / {snap['mem_total_gb']:.1f} GB 사용 ({snap['mem_percent']:.1f}%)"
    )

    for d in snap["disks"]:
        lines.append(
            f"디스크 {d['mount']}: {d['used_gb']:.1f} / {d['total_gb']:.1f} GB 사용 ({d['percent']:.1f}%)"
        )

    if snap["gpus"]:
        for g in snap["gpus"]:
            lines.append(
                f"GPU {g['name']}: 사용률 {g['util_percent']:.0f}%, "
                f"메모리 {g['mem_used_mb']:.0f}/{g['mem_total_mb']:.0f} MB, 온도 {g['temp_c']:.0f}C"
            )
    else:
        lines.append("GPU 정보: 확인 불가 (NVIDIA GPU가 없거나 nvidia-smi를 찾을 수 없음)")

    lines.append("CPU 사용률 상위 프로세스:")
    for p in snap["top_cpu"]:
        lines.append(f"  - {p['name']} (PID {p['pid']}): CPU {p['cpu_percent']:.1f}%, MEM {p['mem_percent']:.1f}%")

    lines.append("메모리 사용률 상위 프로세스:")
    for p in snap["top_mem"]:
        lines.append(f"  - {p['name']} (PID {p['pid']}): MEM {p['mem_percent']:.1f}%, CPU {p['cpu_percent']:.1f}%")

    return "\n".join(lines)


def ask_llm(snapshot_text, model, temperature):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"다음은 현재 시스템 자원 사용 현황입니다.\n\n{snapshot_text}"}
        ],
        temperature=temperature,
        max_tokens=1000
    )
    
    return response.choices[0].message.content
