"""시스템 자원(CPU/RAM/GPU/디스크/전력/프로세스) 수집 백엔드 + OpenRouter LLM 호출.

## 스레딩 설계 (중요)

이전 버전은 "값마다 캐시 + 백그라운드 스레드"를 여러 개 따로 두는 구조였다
(프로세스 스캔 스레드, GPU PDH 스레드, nvidia-smi 스레드 ...). 그런데 WMI/COM
센서 조회(LibreHardwareMonitor, ThermalZone)는 매 새로고침 틱마다 GUI가 새로
만드는 QThread에서 호출되고 있었고, 그 COM 연결 객체를 전역 변수에 캐싱해
다음 틱의 '다른' 스레드가 재사용했다. COM 객체는 자신을 만든 스레드(아파트먼트)
밖에서 쓰면 예외를 던지거나, 그 스레드가 메시지 루프를 더 이상 돌리지 않는
애매한 상태에서는 응답을 영원히 기다리며 멈출 수 있다. 이게 "수집 중..."에서
멈춰 무한루프처럼 보이는 근본 원인이었다.

그래서 이번 버전은 **수집을 담당하는 스레드를 프로세스 생애주기 동안 단 하나만
둔다.** WMI 연결, PDH 쿼리 핸들 등 "한 스레드에서만 안전한" 상태는 모두 이
스레드 안의 지역 객체로 가지고 다니며, 절대 다른 스레드와 공유하지 않는다.
GUI(또는 호출자)는 ResourceMonitor.get_snapshot()으로 마지막 결과만 읽어가며,
이 호출은 락 하나만 잡는 즉시 반환이라 절대 블로킹되지 않는다.
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime

import psutil
from dotenv import load_dotenv

try:
    import win32pdh
    HAS_PDH = True
except ImportError:
    HAS_PDH = False

try:
    import wmi
    HAS_WMI = True
except ImportError:
    HAS_WMI = False

try:
    import pythoncom
    HAS_PYTHONCOM = True
except ImportError:
    HAS_PYTHONCOM = False

try:
    import pynvml
    HAS_NVML = True
except ImportError:
    HAS_NVML = False

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# OpenAI 클라이언트는 지연 생성한다.
# 모듈 import 시점에 api_key가 None이면 OpenAI()가 예외를 던지므로,
# 키가 없을 때도 대시보드(모니터링)는 정상 동작하도록 분석 호출 시에만 생성한다.
_client = None


def _get_client():
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요."
            )
        from openai import OpenAI

        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
            # 타임아웃을 지정하지 않으면 네트워크가 막혔을 때 SDK 기본값(수 분)까지
            # 무한정 대기해 "응답이 안 와요" 행(hang)처럼 보일 수 있다.
            timeout=30.0,
            max_retries=1,
        )
    return _client


# ─────────────────────────────────────────────────────────────
# 상수 / 설정
# ─────────────────────────────────────────────────────────────
from resource_advisor_command import get_commands_prompt

def get_dynamic_system_prompt():
    return f"""당신은 컴퓨터 자원 최적화를 돕는 전문 AI 어드바이저입니다.
사용자로부터 CPU, RAM, GPU, 디스크 사용량, 상위 프로세스 목록, 전력 사용량/예상 전기요금을 전달받습니다.
다음 관점용으로 분석해서 한국어로 간결하게 답변하세요.

1. 현재 낭비되고 있거나 비정상적으로 자원을 많이 쓰는 프로세스가 있는지
2. RAM/디스크/GPU 중 여유가 부족하거나 과도하게 쓰는 자원이 있는지
3. 전력 사용량과 예상 전기요금이 합리적인 수준인지, 특정 프로세스 때문에 불필요하게 높다면 무엇을 줄여야 하는지
4. 더 효율적으로 자원과 전력을 쓰기 위한 구체적이고 실행 가능한 조치

전력 데이터가 'N/A'로 표시되어 있다면 측정 불가 상태이니 추측하지 말고 해당 항목은 언급하지 마세요.
불필요한 군더더기 설명 없이 항목별로 bullet으로 작성하고, 심각도가 높은 항목을 먼저 언급하세요.
Markdown 문법(예: **굵게**, 코드펜스, 제목 마크업)은 사용하지 말고 일반 텍스트로만 작성하세요.

[🔥 핵심 지시사항 - 능동적인 시스템 제어 태그 사용 필수]
사용자에게 "작업 관리자에서 프로세스를 종료하세요" 와 같이 말로만 제안하지 마십시오.
당신이 프로세스를 끄거나 파일을 삭제해야 한다고 판단했다면, 답변 텍스트의 **맨 마지막**에 반드시 다음 형식의 시스템 제어 태그를 직접 적으십시오. 
시스템이 이 태그를 인식하여 즉각 사용자의 승인을 거쳐 조치할 것입니다.

{get_commands_prompt()}

[🚫 절대 금지 사항]
1. `python.exe` 프로세스는 이 자원 어드바이저 앱 자체를 구동하는 핵심 프로세스이므로 **어떠한 경우에도 종료 태그를 발급하지 마십시오.** (자신을 끄게 됩니다)
2. 시스템을 망가뜨릴 수 있는 핵심 프로세스(explorer.exe, svchost.exe 등)나 Windows 시스템 폴더 내 파일에 대해서는 제어 태그를 발급하지 마세요.
"""

DEFAULT_ELECTRICITY_RATE_WON_PER_KWH = 150.0

AVAILABLE_MODELS = [
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini"
]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ─────────────────────────────────────────────────────────────
# 정적 GPU 정보 (Win32_VideoController)
# ─────────────────────────────────────────────────────────────
def get_static_gpu_info():
    """Win32_VideoController 로 모든 GPU의 이름·VRAM을 읽는다.

    호출자(컬렉터 스레드)가 자체 스케줄로 호출한다. 실패해도 빈 리스트를
    반환할 뿐 예외를 던지지 않는다.
    """
    utf8_prefix = "$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    script = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", utf8_prefix + script],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15, creationflags=_NO_WINDOW
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        data = json.loads(result.stdout.strip())
        if isinstance(data, dict):
            data = [data]

        gpus = []
        for idx, item in enumerate(data):
            name = item.get("Name", "Unknown GPU")
            ram_bytes = item.get("AdapterRAM")
            ram_mb = 0.0 if (ram_bytes is None or ram_bytes < 0) else float(ram_bytes) / (1024 ** 2)
            gpus.append({
                "index": idx,
                "name": name,
                "mem_total_mb": ram_mb,
                "util_percent": 0.0,
                "mem_used_mb": 0.0,
                "static_only": True
            })
        return gpus
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# DXGI 어댑터 열거 (luid → 이름/VRAM 권위 매핑)
#
# Windows 작업 관리자가 GPU를 식별·집계하는 단위가 바로 어댑터 LUID다. PDH의
# "GPU Engine" / "GPU Adapter Memory" 카운터도 인스턴스 이름에 luid를 담고
# 있으므로, "luid → GPU 이름" 매핑만 있으면 어떤 카운터 값이 어느 GPU 것인지
# 이름 유사도 같은 추측 없이 정확히 연결할 수 있다. 그 매핑의 권위 있는 출처가
# DXGI IDXGIFactory1::EnumAdapters1 (작업 관리자와 동일한 데이터)이다.
#
# ctypes로 COM vtable을 직접 호출하므로 한 단계라도 어긋나면 프로세스가 죽을 수
# 있다 - 모든 단계를 예외로 감싸고, 실패하면 빈 리스트를 돌려준다(호출부는
# Win32_VideoController 기반 폴백으로 동작).
# ─────────────────────────────────────────────────────────────
_DXGI_ERROR_NOT_FOUND = 0x887A0002
_DXGI_ADAPTER_FLAG_SOFTWARE = 0x2


def get_dxgi_adapters():
    """하드웨어 GPU 어댑터를 DXGI 열거 순서대로 반환한다.

    반환: [{"luid": "luid_0x..._0x...", "name": str, "mem_total_mb": float}]
    소프트웨어 어댑터(Microsoft Basic Render Driver 등)와 실패는 제외/빈 리스트.
    """
    import ctypes
    from ctypes import wintypes, POINTER, byref, c_void_p

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", _LUID),
            ("Flags", wintypes.UINT),
        ]

    def _vfn(ptr, index, restype, argtypes):
        vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))
        fnptr = vtbl.contents[index]
        return ctypes.WINFUNCTYPE(restype, *argtypes)(fnptr)

    try:
        dxgi = ctypes.windll.dxgi
    except Exception:
        return []

    iid_factory1 = (ctypes.c_byte * 16)(
        0xec, 0x66, 0x71, 0x7b, 0xc7, 0x21, 0xae, 0x44,
        0xb2, 0x1a, 0xc9, 0xae, 0x32, 0x1a, 0xe3, 0x69,
    )
    try:
        create = dxgi.CreateDXGIFactory1
        create.restype = ctypes.c_int32  # HRESULT를 정수로 받아 ctypes 자동 예외 방지
        create.argtypes = [ctypes.c_void_p, POINTER(c_void_p)]
        factory = c_void_p()
        hr = create(ctypes.cast(iid_factory1, ctypes.c_void_p), byref(factory))
        if hr != 0 or not factory.value:
            return []
    except Exception:
        return []

    adapters = []
    try:
        enum_adapters1 = _vfn(factory, 12, ctypes.c_int32, [c_void_p, wintypes.UINT, POINTER(c_void_p)])
        i = 0
        while True:
            adapter = c_void_p()
            hr = enum_adapters1(factory, i, byref(adapter)) & 0xFFFFFFFF
            if hr == _DXGI_ERROR_NOT_FOUND or hr != 0 or not adapter.value:
                break
            try:
                get_desc1 = _vfn(adapter, 10, ctypes.c_int32, [c_void_p, POINTER(_DXGI_ADAPTER_DESC1)])
                desc = _DXGI_ADAPTER_DESC1()
                if get_desc1(adapter, byref(desc)) == 0 and not (desc.Flags & _DXGI_ADAPTER_FLAG_SOFTWARE):
                    luid = (f"luid_0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}"
                            f"_0x{desc.AdapterLuid.LowPart & 0xFFFFFFFF:08x}")
                    adapters.append({
                        "luid": luid,
                        "name": desc.Description,
                        "mem_total_mb": desc.DedicatedVideoMemory / (1024 ** 2),
                        "shared_total_mb": desc.SharedSystemMemory / (1024 ** 2),
                    })
            finally:
                try:
                    _vfn(adapter, 2, ctypes.c_ulong, [c_void_p])(adapter)  # Release
                except Exception:
                    pass
            i += 1
    except Exception:
        adapters = []
    finally:
        try:
            _vfn(factory, 2, ctypes.c_ulong, [c_void_p])(factory)  # Release
        except Exception:
            pass

    return adapters


# ─────────────────────────────────────────────────────────────
# NVIDIA GPU 스냅샷 (nvidia-smi)
# ─────────────────────────────────────────────────────────────
def _parse_smi_value(raw):
    """nvidia-smi 필드 값을 float로 변환한다.
    'N/A', '[Not Supported]' 등 측정 불가 값은 None으로 반환한다."""
    raw = (raw or "").strip()
    if not raw or raw.lower() in ("n/a", "[n/a]", "not supported", "[not supported]"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def get_gpu_snapshot():
    """nvidia-smi로 NVIDIA GPU의 실시간 사용률·VRAM·온도를 읽는다.

    호출자가 알아서 호출 주기를 관리한다(여기서는 캐싱하지 않는다 - 컬렉터
    스레드 안에서만 호출되므로 별도 캐시/락이 필요 없다).
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True, encoding="utf-8", errors="replace", timeout=3, creationflags=_NO_WINDOW
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [v.strip() for v in line.split(",")]
        if len(parts) < 6:
            continue
        idx_raw, name = parts[0], parts[1]
        util = _parse_smi_value(parts[2])
        mem_used = _parse_smi_value(parts[3])
        mem_total = _parse_smi_value(parts[4])
        power_w = _parse_smi_value(parts[5])

        try:
            smi_index = int(idx_raw)
        except ValueError:
            smi_index = len(gpus)

        gpus.append({
            "smi_index": smi_index,
            "name": name,
            "util_percent": util if util is not None else 0.0,
            "mem_used_mb": mem_used if mem_used is not None else 0.0,
            "mem_total_mb": mem_total if mem_total is not None else 0.0,
            "power_w": power_w,
        })
    return gpus if gpus else None


# ─────────────────────────────────────────────────────────────
# NVIDIA GPU 스냅샷 (NVML, nvidia-smi보다 우선)
#
# nvidia-smi.exe를 매 틱 서브프로세스로 띄우는 대신, 드라이버와 함께 설치되는
# nvml.dll을 ctypes로 직접 호출한다(hw-monitor-main의 nvml-wrapper crate와
# 동일한 라이브러리). 서브프로세스 spawn 비용·백신 실시간 검사 지연이 없고,
# CSV 파싱도 필요 없어 nvidia-smi보다 빠르고 안정적으로 온도를 읽는다.
# NVML 핸들은 컬렉터 스레드 하나에서만 init/조회하도록 사용해야 한다.
# ─────────────────────────────────────────────────────────────
class _NvmlGpuSampler:
    def __init__(self):
        self._ok = False
        if not HAS_NVML:
            return
        try:
            pynvml.nvmlInit()
            self._ok = True
        except Exception:
            self._ok = False

    def sample(self):
        """NVML로 모든 NVIDIA GPU의 사용률·VRAM·온도를 읽는다.

        NVML 자체를 못 쓰거나 GPU가 하나도 없으면 None을 반환해 호출자가
        nvidia-smi 폴백으로 넘어가게 한다.
        """
        if not self._ok:
            return None
        try:
            count = pynvml.nvmlDeviceGetCount()
        except Exception:
            return None
        if not count:
            return None

        gpus = []
        for i in range(count):
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "replace")
            except Exception:
                continue

            util_percent = 0.0
            try:
                util_percent = float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
            except Exception:
                pass

            mem_used_mb = mem_total_mb = 0.0
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used_mb = mem.used / (1024 ** 2)
                mem_total_mb = mem.total / (1024 ** 2)
            except Exception:
                pass

            # GPU 전력(W) - LibreHardwareMonitor(관리자 권한 필요) 없이도 드라이버가
            # 직접 보고하는 값이라 NVIDIA GPU라면 이것만으로도 "전력 측정 불가"를
            # 피할 수 있다. milliwatts로 반환되므로 1000으로 나눈다.
            power_w = None
            try:
                power_w = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                pass

            gpus.append({
                "smi_index": i,
                "name": name,
                "util_percent": util_percent,
                "mem_used_mb": mem_used_mb,
                "mem_total_mb": mem_total_mb,
                "power_w": power_w,
            })

        return gpus if gpus else None


# ─────────────────────────────────────────────────────────────
# 디스크 스냅샷
# ─────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────
# 이름 유사도 매칭 헬퍼
# ─────────────────────────────────────────────────────────────
def _name_similarity(a: str, b: str) -> float:
    """두 GPU 이름의 유사도를 0~1 사이 값으로 반환한다.
    공통 토큰 비율로 계산해 nvidia-smi와 WMI 이름 차이를 허용한다.

    단, 제조사가 서로 다르다고 판단되면(예: "NVIDIA..." vs "Intel...") 토큰이
    겹치더라도 절대 매칭시키지 않는다 - 한쪽 이름이 일반적인 단어("Graphics",
    "GPU" 등)만 포함해서 우연히 점수가 높게 나오는 경우, 내장 그래픽의 실시간
    데이터가 외장 GPU 카드에(혹은 반대로) 잘못 들어가는 사고를 막기 위함이다.
    """
    a_vendor = _gpu_vendor(a)
    b_vendor = _gpu_vendor(b)
    if a_vendor and b_vendor and a_vendor != b_vendor:
        return 0.0
    a_tokens = set(re.split(r"[\s\-/]", a.lower()))
    b_tokens = set(re.split(r"[\s\-/]", b.lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    return len(intersection) / max(len(a_tokens), len(b_tokens))


_GPU_VENDOR_KEYWORDS = {
    "nvidia": ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla"),
    "amd": ("amd", "radeon", "ryzen"),
    "intel": ("intel", "iris", "uhd"),
}


def _gpu_vendor(name: str):
    """GPU 이름에서 제조사를 추정한다. 모르면 None(보수적으로 매칭 허용)."""
    n = (name or "").lower()
    for vendor, keywords in _GPU_VENDOR_KEYWORDS.items():
        if any(k in n for k in keywords):
            return vendor
    return None


# ─────────────────────────────────────────────────────────────
# GPU 프로세스 사용률 + 어댑터별 사용률 (PDH "GPU Engine" 카운터)
#
# PDH 쿼리 핸들은 컬렉터 스레드 하나가 인스턴스를 들고 다니며 재사용한다.
# rate counter 특성상 두 샘플 사이에 sleep(0.2)이 필요한데, 이 클래스는 항상
# 컬렉터 스레드에서만 호출되므로 그 0.2초는 다른 어떤 것도 블로킹하지 않는다.
#
# "GPU Engine" 카운터의 인스턴스 이름은 벤더 무관 표준 OS 카운터라서
# Intel/AMD 내장 그래픽도 NVIDIA처럼 nvidia-smi/NVML 없이 사용률을 읽을 수
# 있다. 인스턴스 경로 형식: pid_<pid>_luid_<low>_<high>_phys_<phys>_eng_<n>_engtype_<type>
#
# 처음에는 "phys"가 물리 GPU 번호라고 가정하고 그걸로 어댑터를 구분했는데,
# 실제로 확인해 보니 단일 다이 GPU에서는 phys가 거의 항상 0으로 고정되고
# (멀티칩 모듈에서나 의미가 있는 "어댑터 내부 세그먼트" 번호다), 실제로
# 서로 다른 물리 GPU를 구분하는 값은 "luid"다. phys만 보고 그룹화하면
# 내장 그래픽과 외장 그래픽의 사용률이 한 버킷으로 합쳐져서, 외장 GPU가
# 실제로 작업 중일 때도 그 사용량이 엉뚱한(내장) GPU 카드에 붙는 버그가
# 있었다 - luid로 그룹화해 각 물리 어댑터를 정확히 분리한다.
# 같은 luid 안에서도 엔진(3D/Copy/VideoDecode 등)이 여러 개 동시에 돌 수
# 있으므로, 어댑터의 전체 사용률은 "가장 바쁜 엔진"의 합산값으로 근사한다
# (작업 관리자가 GPU 사용률을 표시하는 방식과 동일).
# ─────────────────────────────────────────────────────────────
_GPU_ENGINE_RE = re.compile(r"pid_(\d+)_(luid_0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_\d+_eng_\d+_engtype_(\w+)")


class _GpuProcessSampler:
    def __init__(self):
        self._query = None
        self._counters = []
        self._paths = []
        self.last_luid_util: dict[str, float] = {}
        # Windows는 화면에 안 보이는 가상/소프트웨어 어댑터(WARP 등)도 luid를
        # 하나씩 부여해 "GPU Engine"/"GPU Adapter Memory"에 항상 노출시킨다.
        # 이런 유령 어댑터는 실제로 화면을 그리는 일이 없어 사용률이 영원히
        # 0이지만, 진짜 내장 그래픽은 데스크톱 합성(dwm.exe 등) 때문에 언젠가
        # 한 번이라도 0%를 넘는 값이 찍힌다 - 그렇게 "한 번이라도 활동한" luid만
        # 누적해서 신뢰할 후보로 취급한다(세션 내내 유지되는 sticky 집합).
        self.known_real_luids: set[str] = set()

    def sample(self):
        if not HAS_PDH:
            self.last_luid_util = {}
            return []
        try:
            current_paths = win32pdh.ExpandCounterPath(r"\GPU Engine(*)\Utilization Percentage")
        except Exception:
            self.last_luid_util = {}
            return []
        if not current_paths:
            self.last_luid_util = {}
            return []

        try:
            if self._query is None or current_paths != self._paths:
                if self._query is not None:
                    try:
                        win32pdh.CloseQuery(self._query)
                    except Exception:
                        pass
                self._query = win32pdh.OpenQuery()
                self._counters = []
                for p in current_paths:
                    try:
                        self._counters.append((p, win32pdh.AddCounter(self._query, p)))
                    except Exception:
                        continue
                self._paths = current_paths
                # 첫 샘플: 기준점만 잡고 다음 호출에서 실제값을 읽는다
                win32pdh.CollectQueryData(self._query)
                self.last_luid_util = {}
                return []

            win32pdh.CollectQueryData(self._query)
            time.sleep(0.2)  # PDH rate counter는 두 샘플 차이가 필요
            win32pdh.CollectQueryData(self._query)

            usage_by_pid: dict[int, float] = {}
            luid_engine_totals: dict[tuple, float] = {}
            for path, counter in self._counters:
                match = _GPU_ENGINE_RE.search(path)
                if not match:
                    continue
                pid = int(match.group(1))
                luid = match.group(2).lower()  # DXGI 매핑과 대소문자 일치
                engtype = match.group(3)
                try:
                    _, value = win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_DOUBLE)
                except Exception:
                    continue
                usage_by_pid[pid] = usage_by_pid.get(pid, 0.0) + value
                key = (luid, engtype)
                luid_engine_totals[key] = luid_engine_totals.get(key, 0.0) + value
        except Exception:
            self._query = None
            self._counters = []
            self._paths = []
            self.last_luid_util = {}
            return []

        luid_util: dict[str, float] = {}
        for (luid, engtype), value in luid_engine_totals.items():
            luid_util[luid] = max(luid_util.get(luid, 0.0), value)
            if value > 0.05:
                self.known_real_luids.add(luid)
        self.last_luid_util = luid_util

        rows = []
        for pid, gpu_percent in usage_by_pid.items():
            if gpu_percent <= 0:
                continue
            try:
                name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            rows.append({"pid": pid, "name": name, "gpu_percent": gpu_percent})

        rows.sort(key=lambda r: r["gpu_percent"], reverse=True)
        return rows


# ─────────────────────────────────────────────────────────────
# 어댑터별 VRAM 사용량 (PDH "GPU Adapter Memory" 카운터)
#
# "GPU Engine"은 프로세스가 그 순간 실제로 엔진을 점유하고 있을 때만 인스턴스가
# 생기지만, "GPU Adapter Memory"는 어댑터가 존재하는 한 항상 인스턴스가 있다
# (Dedicated Usage 등). luid로 GPU Engine과 동일하게 물리 어댑터를 구분할 수
# 있어, 내장 그래픽처럼 LHM/NVML이 없는 GPU도 항상 VRAM 사용량을 읽을 수 있다.
# Rate counter가 아니라 매 순간 값이라 두 번 샘플링할 필요가 없다.
# ─────────────────────────────────────────────────────────────
_GPU_ADAPTER_MEM_RE = re.compile(r"(luid_0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_\d+")


class _GpuAdapterMemSampler:
    def __init__(self):
        self._query = None
        self._counters = []  # (luid, kind, counter)
        self._paths = []

    def sample(self):
        """반환: {luid: {"dedicated": mb, "shared": mb}}. 실패 시 {}.

        외장 GPU는 dedicated(전용 VRAM), 내장 GPU는 shared(시스템 RAM 공유)를
        주로 쓰므로 둘 다 모아 두고 호출부가 어댑터 성격에 맞게 고른다.
        """
        if not HAS_PDH:
            return {}
        try:
            ded_paths = win32pdh.ExpandCounterPath(r"\GPU Adapter Memory(*)\Dedicated Usage")
            shr_paths = win32pdh.ExpandCounterPath(r"\GPU Adapter Memory(*)\Shared Usage")
        except Exception:
            return {}
        all_paths = (ded_paths or []) + (shr_paths or [])
        if not all_paths:
            return {}

        try:
            if self._query is None or all_paths != self._paths:
                if self._query is not None:
                    try:
                        win32pdh.CloseQuery(self._query)
                    except Exception:
                        pass
                self._query = win32pdh.OpenQuery()
                self._counters = []
                for kind, paths in (("dedicated", ded_paths or []), ("shared", shr_paths or [])):
                    for p in paths:
                        m = _GPU_ADAPTER_MEM_RE.search(p)
                        if not m:
                            continue
                        try:
                            self._counters.append((m.group(1).lower(), kind,
                                                   win32pdh.AddCounter(self._query, p)))
                        except Exception:
                            continue
                self._paths = all_paths

            win32pdh.CollectQueryData(self._query)  # 순간값 카운터라 한 번만 샘플링하면 된다

            usage: dict[str, dict] = {}
            for luid, kind, counter in self._counters:
                try:
                    _, value = win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_DOUBLE)
                except Exception:
                    continue
                slot = usage.setdefault(luid, {"dedicated": 0.0, "shared": 0.0})
                slot[kind] += value / (1024 ** 2)
            return usage
        except Exception:
            self._query = None
            self._counters = []
            self._paths = []
            return {}


# ─────────────────────────────────────────────────────────────
# CPU 전력 (PDH "Energy Meter" = Intel RAPL 텔레메트리)
#
# Windows는 Intel RAPL(Running Average Power Limit) 에너지 카운터를 "Energy
# Meter" 성능 개체로 노출한다. LibreHardwareMonitor 같은 외부 드라이버/도구
# 없이도, AC 전원에 연결된 상태에서도 CPU 패키지/코어/DRAM의 실제 소비 전력을
# 읽을 수 있다(값 단위는 milliwatts). 인스턴스 예:
#   RAPL_Package0_PKG  = 패키지 전체(코어+언코어+iGPU)
#   RAPL_Package0_PP0  = 코어(IA)
#   RAPL_Package0_PP1  = 언코어/내장 GPU
#   RAPL_Package0_DRAM = 메모리
# "Power" 카운터는 두 번째 샘플부터 유효하므로(에너지 차분), 쿼리를 계속 열어
# 두고 매 호출 한 번씩 CollectQueryData 하면 직전 샘플과의 차로 값이 나온다.
# ─────────────────────────────────────────────────────────────
_RAPL_PKG_RE = re.compile(r"RAPL_Package(\d+)_PKG", re.IGNORECASE)
_RAPL_DRAM_RE = re.compile(r"RAPL_Package(\d+)_DRAM", re.IGNORECASE)


class _RaplPowerSampler:
    def __init__(self):
        self._query = None
        self._counters = []  # (instance_name, counter)
        self._primed = False

    def sample(self):
        """반환: {"CPU(패키지)": w, "RAM": w} 형태(있는 것만). 불가 시 {}."""
        if not HAS_PDH:
            return {}
        try:
            if self._query is None:
                paths = win32pdh.ExpandCounterPath(r"\Energy Meter(*)\Power")
                if not paths:
                    return {}
                self._query = win32pdh.OpenQuery()
                self._counters = []
                for p in paths:
                    inst = self._instance_name(p)
                    if inst is None:
                        continue
                    try:
                        self._counters.append((inst, win32pdh.AddCounter(self._query, p)))
                    except Exception:
                        continue
                if not self._counters:
                    self._query = None
                    return {}
                self._primed = False

            win32pdh.CollectQueryData(self._query)
            if not self._primed:
                # 첫 수집은 기준점만. 다음 호출부터 직전 샘플과의 차로 유효값이 나온다.
                self._primed = True
                return {}

            pkg_w = 0.0
            dram_w = 0.0
            have_pkg = False
            have_dram = False
            for inst, counter in self._counters:
                try:
                    _, value = win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_DOUBLE)
                except Exception:
                    continue
                if _RAPL_PKG_RE.search(inst):
                    pkg_w += value / 1000.0  # mW → W
                    have_pkg = True
                elif _RAPL_DRAM_RE.search(inst):
                    dram_w += value / 1000.0
                    have_dram = True

            out = {}
            if have_pkg and pkg_w > 0:
                out["CPU(패키지)"] = pkg_w
            if have_dram and dram_w > 0:
                out["RAM"] = dram_w
            return out
        except Exception:
            self._query = None
            self._counters = []
            self._primed = False
            return {}

    @staticmethod
    def _instance_name(path):
        m = re.search(r"\\Energy Meter\(([^)]+)\)", path)
        return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────
# LibreHardwareMonitor/OpenHardwareMonitor + ThermalZone WMI 센서
#
# WMI 연결(COM 객체)은 자신을 만든 스레드 밖에서 쓰면 예외를 던지거나, 그
# 스레드가 더 이상 메시지 루프를 돌리지 않으면 응답을 영원히 기다리며 멈출
# 수 있다. 그래서 이 클래스의 인스턴스는 반드시 컬렉터 스레드 하나에서만
# 생성·사용·폐기되어야 한다(다른 스레드와 공유 금지).
# ─────────────────────────────────────────────────────────────
_LHM_COOLDOWN = 30.0  # WMI/PowerShell 둘 다 실패한 namespace는 이 시간 동안 재시도 안 함


class _HardwareSensorReader:
    def __init__(self):
        self._lhm_conns: dict = {}
        self._lhm_blacklist: dict = {}

    # ── LibreHardwareMonitor / OpenHardwareMonitor ──
    def lhm_rows(self):
        now = time.time()
        for namespace in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            fail_ts = self._lhm_blacklist.get(namespace)
            if fail_ts is not None and (now - fail_ts) < _LHM_COOLDOWN:
                continue

            rows = self._lhm_rows_via_wmi(namespace)
            if rows:
                self._lhm_blacklist.pop(namespace, None)
                return rows

            rows = self._lhm_rows_via_powershell(namespace)
            if rows:
                self._lhm_blacklist.pop(namespace, None)
                return rows

            self._lhm_blacklist[namespace] = now
        return []

    def _lhm_rows_via_wmi(self, namespace):
        if not HAS_WMI:
            return []
        try:
            conn = self._lhm_conns.get(namespace)
            if conn is None:
                conn = wmi.WMI(namespace=namespace)
                self._lhm_conns[namespace] = conn
            hardware = {h.Identifier: h for h in conn.Hardware()}
            rows = []
            for sensor in conn.Sensor():
                parent = hardware.get(sensor.Parent)
                if parent is None:
                    continue
                rows.append({
                    "HardwareName": str(parent.Name),
                    "HardwareType": str(parent.HardwareType),
                    "SensorName": str(sensor.Name),
                    "SensorType": str(sensor.SensorType),
                    "Value": float(sensor.Value),
                })
            return rows
        except Exception:
            self._lhm_conns.pop(namespace, None)
            return []

    @staticmethod
    def _lhm_rows_via_powershell(namespace):
        script = (
            f"$ns = '{namespace}'; "
            "$hw = @{}; "
            "try { "
            "Get-CimInstance -Namespace $ns -ClassName Hardware -ErrorAction Stop | "
            "ForEach-Object { $hw[$_.Identifier] = $_ }; "
            "Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop | "
            "ForEach-Object { "
            "$p = $hw[$_.Parent]; "
            "if ($p) { [pscustomobject]@{ "
            "HardwareName = $p.Name; HardwareType = $p.HardwareType; "
            "SensorName = $_.Name; SensorType = $_.SensorType; Value = $_.Value "
            "} } "
            "} | ConvertTo-Json -Compress "
            "} catch { '[]' }"
        )
        return _run_powershell_json(script, timeout=8)


def _run_powershell_json(script, timeout=8):
    utf8_prefix = "$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", utf8_prefix + script],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=_NO_WINDOW
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    out = (result.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def get_battery_power_w():
    """노트북 배터리의 방전 전력(W)을 읽는다. LHM 같은 외부 도구가 필요 없다.

    root\\wmi의 BatteryStatus.DischargeRate(mW)는 배터리로 구동 중일 때 시스템
    전체(CPU+GPU+화면 등)가 실제로 끌어다 쓰는 전력이라, 소비전력/전기요금
    추정에 그대로 쓰기 좋다. 단, AC 어댑터에 연결되어 있으면 방전이 0이라
    측정할 수 없다(이 경우 None).

    반환: (watts: float|None, on_battery: bool, has_battery: bool)
    """
    script = (
        "$b = Get-CimInstance -Namespace root\\wmi -ClassName BatteryStatus "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($b) { [pscustomobject]@{ Discharging = [bool]$b.Discharging; "
        "DischargeRate = [int]$b.DischargeRate; PowerOnline = [bool]$b.PowerOnline } "
        "| ConvertTo-Json -Compress } else { '{}' }"
    )
    rows = _run_powershell_json(script, timeout=8)
    if not rows:
        return None, False, False
    row = rows[0]
    if "Discharging" not in row and "PowerOnline" not in row:
        return None, False, False  # 배터리 없음(데스크톱)

    discharging = bool(row.get("Discharging"))
    rate_mw = row.get("DischargeRate") or 0
    if discharging and rate_mw and rate_mw > 0:
        return rate_mw / 1000.0, True, True
    return None, False, True


def _parse_lhm_rows(rows):
    """LHM/OHM 센서 행을 GPU 사용률/메모리, 전력으로 정리한다."""
    empty = {"gpu_stats": {}, "power_w": {}}
    if not rows:
        return empty

    gpu_stats = {}
    power_candidates = {}

    for row in rows:
        hw_type = str(row.get("HardwareType") or "")
        hw_name = str(row.get("HardwareName") or "")
        sensor_name = str(row.get("SensorName") or "")
        sensor_type = str(row.get("SensorType") or "")
        try:
            value = float(row.get("Value"))
        except (TypeError, ValueError):
            continue

        if not hw_name:
            continue

        if sensor_type == "Load" and hw_type.startswith("Gpu"):
            name_l = sensor_name.lower()
            if any(k in name_l for k in ("core", "d3d", "3d", "render", "engine")):
                stats = gpu_stats.setdefault(hw_name, {})
                stats["util_percent"] = max(stats.get("util_percent", 0.0), value)

        elif sensor_type in ("SmallData", "Data") and hw_type.startswith("Gpu"):
            name_l = sensor_name.lower()
            stats = gpu_stats.setdefault(hw_name, {})
            if "memory" in name_l and "used" in name_l:
                stats["mem_used_mb"] = value
            elif "memory" in name_l and ("total" in name_l or "available" in name_l):
                stats["mem_total_mb"] = max(stats.get("mem_total_mb", 0.0), value)

        elif sensor_type == "Power":
            power_candidates.setdefault(hw_name, {})[sensor_name] = value

    power_w = {}
    for hw_name, sensors in power_candidates.items():
        package = next((v for k, v in sensors.items() if "Package" in k), None)
        power_w[hw_name] = package if package is not None else max(sensors.values())

    return {"gpu_stats": gpu_stats, "power_w": power_w}


# ─────────────────────────────────────────────────────────────
# ResourceMonitor: 단일 백그라운드 수집 스레드 + 즉시 반환되는 get_snapshot()
# ─────────────────────────────────────────────────────────────
class ResourceMonitor:
    """CPU/RAM/GPU/디스크/프로세스 스냅샷을 수집한다.

    실제 수집(서브프로세스 spawn, WMI, PDH)은 생성 시 시작되는 단 하나의
    데몬 스레드(_collector_loop)에서만 일어난다. get_snapshot()은 그 결과를
    락으로 보호된 변수에서 즉시 읽기만 하므로, 호출한 스레드(GUI 메인 스레드
    포함)를 절대 블로킹하지 않는다.
    """

    # 각 데이터 종류별 재조회 주기(초)
    _PROC_INTERVAL = 2.0
    _GPU_SMI_INTERVAL = 1.0
    _LHM_INTERVAL = 3.0
    _GPU_PROC_INTERVAL = 1.0
    _STATIC_GPU_RETRY_INTERVAL = 30.0
    _BATTERY_INTERVAL = 3.0
    _LOOP_SLEEP = 0.5

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = self._default_snapshot()

        self.cumulative_wh = 0.0
        self._last_power_w = None
        self._last_power_sample_time = None

        threading.Thread(target=self._collector_loop, daemon=True, name="ResourceCollector").start()

    @staticmethod
    def _default_snapshot():
        return {
            "timestamp": "-",
            "cpu_percent": 0.0,
            "mem_total_gb": 0.0,
            "mem_used_gb": 0.0,
            "mem_percent": 0.0,
            "disks": [],
            "gpus": [],
            "gpu_processes": [],
            "top_cpu": [],
            "top_mem": [],
            "power_components": {},
            "total_power_w": None,
            "cumulative_wh": 0.0,
        }

    def get_snapshot(self):
        """마지막으로 수집된 스냅샷을 즉시 반환한다. 절대 블로킹되지 않는다."""
        with self._lock:
            return self._snapshot

    # ── 수집 스레드 ──
    def _collector_loop(self):
        """이 프로세스 생애주기 동안 단 하나만 도는 수집 루프.

        WMI(COM)와 PDH 핸들은 전부 이 스레드의 지역 변수로만 존재한다 — 다른
        스레드와 공유하지 않으므로 COM 크로스스레드 재사용으로 인한 행(hang)이
        구조적으로 발생할 수 없다.
        """
        if HAS_PYTHONCOM:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
        try:
            self._collector_main()
        finally:
            if HAS_PYTHONCOM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _collector_main(self):
        proc_cache: dict = {}
        hw_reader = _HardwareSensorReader()
        gpu_proc_sampler = _GpuProcessSampler()
        gpu_adapter_mem_sampler = _GpuAdapterMemSampler()
        rapl_sampler = _RaplPowerSampler()
        nvml_sampler = _NvmlGpuSampler()

        static_gpus: list = []
        dxgi_adapters: list = []
        smi_gpus: list | None = None
        lhm = {"gpu_stats": {}, "power_w": {}}
        gpu_processes: list = []
        luid_util: dict = {}
        luid_mem: dict = {}
        top_cpu: list = []
        top_mem: list = []
        rapl_power: dict = {}
        battery_power_w = None

        last_static_gpu = 0.0
        last_dxgi = 0.0
        last_proc = 0.0
        last_smi = 0.0
        last_lhm = 0.0
        last_gpu_proc = 0.0
        last_battery = 0.0

        psutil.cpu_percent(interval=None)  # 기준점

        while True:
            now = time.time()

            if not dxgi_adapters and now - last_dxgi >= self._STATIC_GPU_RETRY_INTERVAL:
                try:
                    dxgi_adapters = get_dxgi_adapters()
                except Exception:
                    dxgi_adapters = []
                last_dxgi = now

            # DXGI가 안 되는 환경(아주 드묾)을 위한 폴백용으로만 Win32도 받아 둔다.
            if not dxgi_adapters and not static_gpus and now - last_static_gpu >= self._STATIC_GPU_RETRY_INTERVAL:
                try:
                    static_gpus = get_static_gpu_info()
                except Exception:
                    static_gpus = []
                last_static_gpu = now

            if now - last_proc >= self._PROC_INTERVAL:
                try:
                    top_cpu, top_mem = self._collect_process_snapshot(proc_cache)
                except Exception:
                    pass
                last_proc = now

            if now - last_smi >= self._GPU_SMI_INTERVAL:
                try:
                    smi_gpus = nvml_sampler.sample()
                    if smi_gpus is None:
                        smi_gpus = get_gpu_snapshot()  # NVML 불가 시 nvidia-smi 폴백
                except Exception:
                    smi_gpus = None
                last_smi = now

            if now - last_lhm >= self._LHM_INTERVAL:
                try:
                    rows = hw_reader.lhm_rows()
                    lhm = _parse_lhm_rows(rows)
                except Exception:
                    pass
                last_lhm = now

            if now - last_battery >= self._BATTERY_INTERVAL:
                try:
                    battery_power_w, _, _ = get_battery_power_w()
                except Exception:
                    battery_power_w = None
                last_battery = now

            # RAPL은 매 루프(0.5s)마다 수집해야 직전 샘플과의 에너지 차로 전력이 나온다.
            try:
                rapl_power = rapl_sampler.sample() or rapl_power
            except Exception:
                pass

            if now - last_gpu_proc >= self._GPU_PROC_INTERVAL:
                try:
                    gpu_processes = gpu_proc_sampler.sample()
                    luid_util = gpu_proc_sampler.last_luid_util
                except Exception:
                    gpu_processes = []
                    luid_util = {}
                try:
                    luid_mem = gpu_adapter_mem_sampler.sample()
                except Exception:
                    luid_mem = {}
                last_gpu_proc = now

            if dxgi_adapters:
                # 정상 경로: luid로 카운터를 정확히 매칭(추측 없음)
                gpus = self._build_gpu_info_by_luid(
                    dxgi_adapters, smi_gpus or [], lhm.get("gpu_stats") or {}, luid_util, luid_mem,
                )
            else:
                # DXGI 실패 시에만 옛 이름-유사도 기반 폴백 사용
                gpus = self._merge_gpu_info(
                    static_gpus, smi_gpus or [], lhm.get("gpu_stats") or {},
                    luid_util, luid_mem, gpu_proc_sampler.known_real_luids,
                )

            # 전력 출처 우선순위(외부 도구 없이도 최대한 측정되게 한다):
            #   1) LHM(관리자 권한 필요)이 있으면 그 컴포넌트별 전력을 우선 사용
            #   2) 없으면 Intel RAPL(CPU 패키지/RAM, AC에서도 측정됨)을 사용
            #   3) NVIDIA GPU 전력(NVML, 지원 GPU에 한함)을 추가로 합산
            #   4) 위 전부 없고 배터리로 구동 중이면, 배터리 방전 전력(시스템 전체)
            power_components = dict(lhm.get("power_w") or {})
            if not power_components and rapl_power:
                power_components.update(rapl_power)

            for g in (smi_gpus or []):
                gpu_power = g.get("power_w")
                gpu_name = g.get("name")
                if gpu_power is not None and gpu_name and gpu_name not in power_components:
                    power_components[gpu_name] = gpu_power

            if not power_components and battery_power_w is not None:
                power_components = {"시스템 전체(배터리)": battery_power_w}

            total_power_w = sum(power_components.values()) if power_components else None
            self._update_energy(total_power_w)

            try:
                mem = psutil.virtual_memory()
                disks = get_disk_snapshot()
                cpu_percent = psutil.cpu_percent(interval=None)
            except Exception:
                mem = None
                disks = []
                cpu_percent = 0.0

            snapshot = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "cpu_percent": cpu_percent,
                "mem_total_gb": (mem.total / (1024 ** 3)) if mem else 0.0,
                "mem_used_gb": (mem.used / (1024 ** 3)) if mem else 0.0,
                "mem_percent": mem.percent if mem else 0.0,
                "disks": disks,
                "gpus": gpus,
                "gpu_processes": gpu_processes[:5],
                "top_cpu": top_cpu,
                "top_mem": top_mem,
                "power_components": power_components,
                "total_power_w": total_power_w,
                "cumulative_wh": self.cumulative_wh,
            }
            with self._lock:
                self._snapshot = snapshot

            time.sleep(self._LOOP_SLEEP)

    # ── 프로세스 스냅샷 (컬렉터 스레드 전용) ──
    @staticmethod
    def _collect_process_snapshot(cache, top_n=7):
        """모든 프로세스의 CPU/MEM%를 읽어 상위 N개를 반환한다.

        프로세스당 cpu_percent()+memory_percent()를 oneshot() 배치로 묶어
        중복 syscall을 줄이고, 개별 속성에 예외 가드를 둔다.
        """
        live_pids = set()
        rows = []

        for pid in psutil.pids():
            live_pids.add(pid)
            item = cache.get(pid)

            if item is None:
                try:
                    proc = psutil.Process(pid)
                    try:
                        name = proc.name() or "?"
                    except Exception:
                        name = "?"
                    try:
                        proc.cpu_percent(interval=None)
                    except Exception:
                        pass
                    cache[pid] = {"proc": proc, "name": name}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception:
                    continue
                continue

            try:
                proc_obj = item["proc"]
                name = item["name"]

                # System Idle Process, System, MemCompression 프로세스는 시스템 기본 프로세스이므로 모니터링 목록에서 제외
                name_lower = name.lower()
                if name_lower in ("system idle process", "system", "memcompression", "memory compression") or "memcompression" in name_lower or "memory compression" in name_lower:
                    continue

                with proc_obj.oneshot():
                    try:
                        cpu_percent = proc_obj.cpu_percent(interval=None) or 0.0
                    except Exception:
                        cpu_percent = 0.0
                    try:
                        mem_percent = proc_obj.memory_percent() or 0.0
                    except Exception:
                        mem_percent = 0.0

                rows.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu_percent,
                    "mem_percent": mem_percent
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        for pid in list(cache.keys()):
            if pid not in live_pids:
                del cache[pid]

        top_cpu = sorted(rows, key=lambda r: r["cpu_percent"], reverse=True)[:top_n]
        top_mem = sorted(rows, key=lambda r: r["mem_percent"], reverse=True)[:top_n]
        return top_cpu, top_mem

    # ── GPU 정보 구성 (luid 기준 정확 매칭) ──
    @staticmethod
    def _build_gpu_info_by_luid(dxgi_adapters, smi_gpus, lhm_gpu_stats: dict,
                                luid_util: dict, luid_mem: dict):
        """DXGI 어댑터(luid→이름/VRAM)를 기준으로 PDH·NVML·LHM 데이터를 붙인다.

        핵심: 사용률·VRAM을 모두 luid로 정확히 매칭한다(이름 유사도 추측 없음).
        PDH "GPU Engine"/"GPU Adapter Memory"는 벤더 무관하게 모든 GPU(내장 포함)를
        luid로 보고하므로, 작업 관리자와 동일한 값을 그대로 각 GPU에 붙일 수 있다.

        NVML/LHM은 이름으로 매칭해 보조적으로만 쓴다(전력 등 PDH가 안 주는 값).
        DXGI가 어댑터를 인식했다는 것 자체가 "실시간 모니터링 가능"을 뜻하므로
        static_only는 False로 둔다 - 사용률이 0%여도 'N/A'가 아니라 '0%'로 보인다.
        """
        luid_util = luid_util or {}
        luid_mem = luid_mem or {}

        gpus = []
        for ad in dxgi_adapters:
            luid = ad["luid"].lower()
            name = ad["name"]
            dedicated_total = ad.get("mem_total_mb") or 0.0
            shared_total = ad.get("shared_total_mb") or 0.0

            # 전용 VRAM이 충분히 큰(>=512MB) 어댑터는 외장 GPU로 보고 dedicated를,
            # 그 외(내장 그래픽)는 시스템 RAM을 공유하므로 shared를 VRAM으로 쓴다.
            is_discrete = dedicated_total >= 512
            mem_slot = luid_mem.get(luid) or {}
            if is_discrete:
                mem_total = dedicated_total
                mem_used = mem_slot.get("dedicated")
            else:
                mem_total = shared_total or dedicated_total
                mem_used = mem_slot.get("shared")
                if mem_used is None:
                    mem_used = mem_slot.get("dedicated")

            util = luid_util.get(luid)
            power_w = None

            # 같은 벤더 이름으로 NVML/nvidia-smi 데이터 매칭(전력·정확한 VRAM 보조)
            best_smi, best_score = None, 0.0
            for smi in smi_gpus:
                score = _name_similarity(name, smi.get("name", ""))
                if score > best_score:
                    best_score, best_smi = score, smi
            if best_smi is not None and best_score >= 0.34:
                if util is None and best_smi.get("util_percent") is not None:
                    util = best_smi["util_percent"]
                if (mem_used is None or mem_used <= 0) and best_smi.get("mem_used_mb"):
                    mem_used = best_smi["mem_used_mb"]
                if not mem_total and best_smi.get("mem_total_mb"):
                    mem_total = best_smi["mem_total_mb"]
                if best_smi.get("power_w") is not None:
                    power_w = best_smi["power_w"]

            # LHM 이름 매칭(사용률/메모리 보조)
            best_stats, best_lscore = None, 0.0
            for lhm_name, stats in (lhm_gpu_stats or {}).items():
                score = 1.0 if lhm_name == name else _name_similarity(name, lhm_name)
                if score > best_lscore:
                    best_lscore, best_stats = score, stats
            if best_stats is not None and best_lscore >= 0.5:
                if util is None and best_stats.get("util_percent") is not None:
                    util = best_stats["util_percent"]
                if (mem_used is None or mem_used <= 0) and best_stats.get("mem_used_mb"):
                    mem_used = best_stats["mem_used_mb"]
                if not mem_total and best_stats.get("mem_total_mb"):
                    mem_total = best_stats["mem_total_mb"]

            gpus.append({
                "name": name,
                "util_percent": util if util is not None else 0.0,
                "mem_used_mb": mem_used if mem_used is not None else 0.0,
                "mem_total_mb": mem_total,
                "static_only": False,
                "power_w": power_w,
                "_dedicated_vram": ad.get("mem_total_mb") or 0.0,
            })

        # 작업 관리자처럼 외장(전용 VRAM이 큰) GPU를 먼저 보여준다 - 내장 그래픽은
        # 전용 VRAM이 매우 작아(보통 수십~128MB) 자연스럽게 뒤로 간다.
        gpus.sort(key=lambda g: g["_dedicated_vram"], reverse=True)
        for i, g in enumerate(gpus):
            g["index"] = i
            g.pop("_dedicated_vram", None)
        return gpus

    # ── GPU 병합 (폴백: DXGI 불가 시 이름 유사도 기반) ──
    @staticmethod
    def _merge_gpu_info(static_gpus, smi_gpus, lhm_gpu_stats: dict,
                        luid_util: dict | None = None, luid_mem: dict | None = None,
                        known_real_luids: set | None = None):
        """static GPU 목록(Win32) + nvidia-smi/NVML + PDH 실시간 데이터를 병합한다.

        매칭은 **이름 유사도 우선**으로 한다. Win32_VideoController 인덱스와
        nvidia-smi 인덱스는 서로 무관하므로(예: 노트북에서 Win32[0]=Intel iGPU,
        nvidia-smi[0]=NVIDIA dGPU) 인덱스로 매칭하면 데이터가 엉뚱한 카드에 붙는다.

        절차:
          1) 각 nvidia-smi/NVML GPU를 이름 유사도가 가장 높은 미사용 static GPU에 매칭
          2) 이름으로 못 찾으면, 미사용 static GPU 중 'NVIDIA' 항목이 하나뿐이면 그곳에 매칭
          3) 그래도 못 찾으면 새 카드로 추가
          4) LHM 사용률/메모리가 있으면 이름 기반으로 보완
          5) 그래도 static_only로 남은 GPU(주로 내장 그래픽)는 PDH "GPU Engine"
             카운터의 어댑터(phys) 인덱스를 Win32_VideoController 순서에 그대로
             대응시켜 실시간 사용률을 채운다. nvidia-smi/NVML로 이미 채워진
             GPU는 phys 인덱스가 겹쳐도 덮어쓰지 않는다.
        """
        merged = [dict(g) for g in static_gpus]
        used_static = set()

        for smi in smi_gpus:
            best_i, best_score = None, 0.0
            for i, st in enumerate(merged):
                if i in used_static or not st.get("static_only", True):
                    continue
                score = _name_similarity(st["name"], smi["name"])
                if score > best_score:
                    best_score, best_i = score, i

            target = best_i if (best_i is not None and best_score >= 0.34) else None

            if target is None:
                nv_remaining = [
                    i for i, st in enumerate(merged)
                    if i not in used_static and st.get("static_only", True)
                    and "nvidia" in st["name"].lower()
                ]
                if len(nv_remaining) == 1:
                    target = nv_remaining[0]

            if target is not None:
                merged[target].update({
                    "util_percent": smi["util_percent"],
                    "mem_used_mb": smi["mem_used_mb"],
                    "mem_total_mb": smi["mem_total_mb"],
                    "static_only": False,
                    "_smi_index": smi.get("smi_index"),
                })
                used_static.add(target)
            else:
                merged.append({
                    "index": len(merged),
                    "name": smi["name"],
                    "util_percent": smi["util_percent"],
                    "mem_used_mb": smi["mem_used_mb"],
                    "mem_total_mb": smi["mem_total_mb"],
                    "static_only": False,
                    "_smi_index": smi.get("smi_index"),
                })
                used_static.add(len(merged) - 1)

        # nvidia-smi/NVML로 이미 채워진(static_only=False) GPU는 여기서 다시
        # 건드리지 않는다. NVML은 그 GPU 자체를 드라이버로 직접 질의한 결과라
        # 이미 권위 있는(authoritative) 값인데, 만약 LHM의 하드웨어 이름이
        # 모호해서(예: 단순히 "GPU"처럼) 다른 GPU와 fuzzy하게 매칭되면 NVML의
        # 정확한 값이 다른 GPU의(엉뚱한) 값으로 덮어써지는 사고가 날 수 있다 -
        # 이게 "NVIDIA 카드에 실제로는 내장 그래픽의 VRAM이 표시되는" 버그의
        # 원인이었다.
        lhm_items = list(lhm_gpu_stats.items())
        for g in merged:
            if not g.get("static_only", True):
                continue
            best_score, best_stats = 0.0, None
            if g["name"] in lhm_gpu_stats:
                best_score, best_stats = 1.0, lhm_gpu_stats[g["name"]]
            for lhm_name, stats in lhm_items:
                score = _name_similarity(g["name"], lhm_name)
                if score > best_score:
                    best_score, best_stats = score, stats
            if best_stats is not None and best_score >= 0.5:
                if best_stats.get("util_percent") is not None:
                    g["util_percent"] = best_stats["util_percent"]
                if best_stats.get("mem_used_mb") is not None:
                    g["mem_used_mb"] = best_stats["mem_used_mb"]
                if best_stats.get("mem_total_mb"):
                    g["mem_total_mb"] = best_stats["mem_total_mb"]
                if any(k in best_stats for k in ("util_percent", "mem_used_mb", "mem_total_mb")):
                    g["static_only"] = False

        if len(merged) == 1 and len(lhm_gpu_stats) == 1:
            only_stats = next(iter(lhm_gpu_stats.values()))
            if only_stats.get("util_percent") is not None:
                merged[0]["util_percent"] = only_stats["util_percent"]
            if only_stats.get("mem_used_mb") is not None:
                merged[0]["mem_used_mb"] = only_stats["mem_used_mb"]
            if only_stats.get("mem_total_mb"):
                merged[0]["mem_total_mb"] = only_stats["mem_total_mb"]
            merged[0]["static_only"] = False

        # PDH의 "GPU Engine"/"GPU Adapter Memory" 카운터는 luid로 물리 어댑터를
        # 정확히 구분해 주지만, luid 자체에는 이름이 없어 "어느 luid가 어느
        # GPU냐"를 알 방법이 없다. "GPU Adapter Memory"는 (가상 어댑터 포함)
        # 항상 모든 luid가 잡혀서 흔히 2~3개가 나오므로, 이미 NVML/nvidia-smi로
        # 정확한 VRAM 사용량을 아는 GPU가 있다면 그 값과 가장 가까운 luid를
        # "그 GPU의 것"으로 먼저 확정해 제외한다(수치 상관관계 매칭).
        claimed_luids = set()
        if luid_mem:
            for g in merged:
                if g.get("static_only", True):
                    continue
                known_mem = g.get("mem_used_mb") or 0.0
                if known_mem <= 32:  # 막 매칭되어 거의 0에 가까우면 비교가 무의미
                    continue
                best_luid, best_diff = None, None
                for luid, mb in luid_mem.items():
                    if luid in claimed_luids:
                        continue
                    diff = abs(mb - known_mem)
                    if best_diff is None or diff < best_diff:
                        best_diff, best_luid = diff, luid
                if best_luid is not None and best_diff <= max(64.0, known_mem * 0.25):
                    claimed_luids.add(best_luid)

        # WARP 같은 화면에 보이지 않는 가상 어댑터도 항상 luid가 잡히는데,
        # known_real_luids가 채워져 있다면(=실제로 한 번이라도 활동을 관찰한
        # luid가 있다면) 그 집합으로 더 좁혀서 유령 어댑터를 걸러낸다. 아직
        # 아무 luid도 활동을 보인 적이 없으면(세션 초반) 전체를 그대로 쓴다.
        def _filter_real(d):
            if not known_real_luids:
                return d
            filtered = {k: v for k, v in d.items() if k in known_real_luids}
            return filtered if filtered else d

        remaining_luid_util = _filter_real({k: v for k, v in (luid_util or {}).items() if k not in claimed_luids})
        remaining_luid_mem = _filter_real({k: v for k, v in (luid_mem or {}).items() if k not in claimed_luids})

        # 남은 luid 데이터를 "아직 실시간 데이터가 없는 GPU가 정확히 하나"이고
        # "남은 luid도 정확히 하나"일 때만(=둘 다 모호하지 않을 때만) 매칭한다.
        # 그렇지 않으면 비워 두는 쪽을 택한다 - 잘못 매칭해 엉뚱한 GPU에 값이
        # 붙는 쪽이 훨씬 나쁘다.
        remaining_static = [i for i, g in enumerate(merged) if g.get("static_only", True)]
        if len(remaining_static) == 1:
            idx = remaining_static[0]
            if len(remaining_luid_util) == 1:
                merged[idx]["util_percent"] = min(next(iter(remaining_luid_util.values())), 100.0)
                merged[idx]["static_only"] = False
            if len(remaining_luid_mem) == 1:
                mem_mb = next(iter(remaining_luid_mem.values()))
                if mem_mb > 0:
                    merged[idx]["mem_used_mb"] = mem_mb
                    merged[idx]["static_only"] = False

        # GPU 0 = 실시간 데이터가 있는 GPU가 되도록 정렬한다(작업관리자/nvidia-smi와
        # 동일한 번호 매김). Win32_VideoController 열거 순서는 내장 그래픽을
        # 먼저 보고하는 경우가 많아 그 순서를 그대로 쓰면 사용자가 보기엔 0번/1번이
        # 뒤바뀐 것처럼 느껴진다.
        #
        # 우선순위 3단계:
        #   0) nvidia-smi/NVML이 자체적으로 부르는 인덱스가 있는 GPU(그 번호 그대로 사용)
        #   1) NVML은 없지만 LHM/PDH로 실시간 사용률·메모리를 얻은 GPU(AMD/Intel
        #      외장 GPU 등) - 정적 정보만 있는 GPU보다 항상 앞에 둔다
        #   2) 실시간 데이터가 전혀 없는(static_only) GPU
        # 같은 단계 안에서는 원래 열거 순서를 유지한다.
        smi_indices = [g.pop("_smi_index", None) for g in merged]

        def _sort_key(item):
            idx, g = item
            smi_idx = smi_indices[idx]
            if smi_idx is not None:
                return (0, smi_idx)
            if not g.get("static_only", True):
                return (1, idx)
            return (2, idx)

        ordered = sorted(enumerate(merged), key=_sort_key)
        merged = [g for _, g in ordered]

        for i, g in enumerate(merged):
            g["index"] = i

        return merged

    def _update_energy(self, power_w):
        now = time.time()
        if power_w is not None and self._last_power_w is not None and self._last_power_sample_time is not None:
            elapsed_hours = (now - self._last_power_sample_time) / 3600.0
            avg_w = (power_w + self._last_power_w) / 2.0
            self.cumulative_wh += avg_w * elapsed_hours

        if power_w is not None:
            self._last_power_w = power_w
            self._last_power_sample_time = now


# ─────────────────────────────────────────────────────────────
# 화이트리스트 및 유틸리티
# ─────────────────────────────────────────────────────────────
def load_whitelist(file_path="whitelist.json"):
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_whitelist(whitelist, file_path="whitelist.json"):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(whitelist, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save whitelist: {e}")

def _format_process_name(name, whitelist):
    if whitelist and name in whitelist:
        return f"{name} (사용자 승인된 작업)"
    return name

# ─────────────────────────────────────────────────────────────
# 스냅샷 → 텍스트 (AI 분석용)
# ─────────────────────────────────────────────────────────────
def snapshot_to_text(snap, electricity_rate_won_per_kwh=DEFAULT_ELECTRICITY_RATE_WON_PER_KWH, whitelist=None):
    if whitelist is None:
        whitelist = []
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
            if g.get("static_only"):
                lines.append(
                    f"GPU {g['index']} ({g['name']}): 하드웨어만 감지 (실시간 센서 미감지), "
                    f"VRAM {g['mem_total_mb']:.0f} MB"
                )
            else:
                lines.append(
                    f"GPU {g['index']} ({g['name']}): 사용률 {g['util_percent']:.0f}%, "
                    f"메모리 {g['mem_used_mb']:.0f}/{g['mem_total_mb']:.0f} MB"
                )
    else:
        lines.append("GPU 정보: 확인 불가")

    lines.append("CPU 사용률 상위 프로세스:")
    for p in snap["top_cpu"]:
        name_str = _format_process_name(p['name'], whitelist)
        lines.append(f"  - {name_str} (PID {p['pid']}): CPU {p['cpu_percent']:.1f}%, MEM {p['mem_percent']:.1f}%")

    lines.append("메모리 사용률 상위 프로세스:")
    for p in snap["top_mem"]:
        name_str = _format_process_name(p['name'], whitelist)
        lines.append(f"  - {name_str} (PID {p['pid']}): MEM {p['mem_percent']:.1f}%, CPU {p['cpu_percent']:.1f}%")

    if snap.get("gpu_processes"):
        lines.append("GPU 사용량 상위 프로세스:")
        for p in snap["gpu_processes"]:
            lines.append(f"  - {p['name']} (PID {p['pid']}): GPU {p['gpu_percent']:.1f}%")

    total_power_w = snap.get("total_power_w")
    if total_power_w is not None:
        lines.append(f"현재 소비 전력: {total_power_w:.1f} W")
        for name, watts in snap.get("power_components", {}).items():
            lines.append(f"  - {name}: {watts:.1f} W")
        cumulative_wh = snap.get("cumulative_wh", 0.0)
        cumulative_cost = (cumulative_wh / 1000.0) * electricity_rate_won_per_kwh
        hourly_cost = (total_power_w / 1000.0) * electricity_rate_won_per_kwh
        lines.append(f"누적 사용량: {cumulative_wh:.1f} Wh (예상 비용 {cumulative_cost:.1f}원)")
        lines.append(f"시간당 예상 비용: {hourly_cost:.1f}원 (전기요금 {electricity_rate_won_per_kwh:.0f}원/kWh)")
    else:
        lines.append(
            "전력 사용량: 측정 불가 (이 시스템은 Intel RAPL/배터리/NVIDIA 전력 "
            "센서를 제공하지 않습니다. LibreHardwareMonitor를 관리자 권한으로 "
            "실행하면 측정될 수 있습니다)"
        )

    return "\n".join(lines)


def get_minimal_snapshot_text(snap, whitelist=None):
    if whitelist is None:
        whitelist = []
        
    """1단계(Triage) 판단을 위한 초소형 스냅샷 텍스트를 생성합니다."""
    # 시스템 총합
    cpu = f"{snap['cpu_percent']:.1f}%"
    ram = f"{snap['mem_percent']:.1f}%"
    gpu_strs = [f"{g['util_percent']:.0f}%" for g in snap["gpus"]]
    gpu = ", ".join(gpu_strs) if gpu_strs else "N/A"
    
    # 프로세스 상위 3개 (이름과 점유율만)
    top_c_strs = []
    for p in snap["top_cpu"][:3]:
        name_str = _format_process_name(p['name'], whitelist)
        top_c_strs.append(f"{name_str} ({p['cpu_percent']:.1f}%)")
        
    top_m_strs = []
    for p in snap["top_mem"][:3]:
        name_str = _format_process_name(p['name'], whitelist)
        top_m_strs.append(f"{name_str} ({p['mem_percent']:.1f}%)")
        
    top_c = ", ".join(top_c_strs)
    top_m = ", ".join(top_m_strs)
    
    return f"CPU:{cpu}, RAM:{ram}, GPU:{gpu} | TopCPU:[{top_c}] | TopRAM:[{top_m}]"


# ─────────────────────────────────────────────────────────────
# LLM 호출
# ─────────────────────────────────────────────────────────────
def ask_llm(snapshot_text, model, temperature):
    response = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": get_dynamic_system_prompt()},
            {"role": "user", "content": f"다음은 현재 시스템 자원 사용 현황입니다.\n\n{snapshot_text}"}
        ],
        temperature=temperature,
        max_tokens=1000
    )
    return response.choices[0].message.content


def ask_llm_question(context_text, question, model, temperature, history=None):
    """분석 컨텍스트를 바탕으로 사용자 질문에 답변한다.

    context_text: 분석 대상 정보 (프로세스/파일/프로그램 등)
    question: 현재 사용자 질문
    history: [(질문, 답변), ...] 이전 대화 목록 (다중턴 컨텍스트 유지)
    """
    ctx_str = str(context_text).strip() if context_text else ""

    system_prompt = (
        "당신은 Windows 시스템 관리 도우미입니다. "
        "사용자가 특정 프로세스, 파일, 프로그램, 시작 항목에 대해 질문하면 "
        "그 항목에 대해 직접적으로 답변하세요. "
        "컴퓨터를 잘 모르는 사람도 이해할 수 있게 쉽고 친절하게 설명하세요. "
        "볼드체(**텍스트**) 없이 일반 텍스트로만 답변하세요."
    )

    messages = [{"role": "system", "content": system_prompt}]

    if ctx_str:
        # 히스토리가 없으면(첫 질문) 컨텍스트를 user 메시지에 직접 붙여서 전달
        # 히스토리가 있으면 첫 번째 user 메시지에 컨텍스트가 이미 포함되어 있음
        if not history:
            first_user_msg = (
                f"다음 항목에 대해 분석 결과가 있습니다:\n\n"
                f"=== 분석 대상 정보 ===\n{ctx_str}\n===================\n\n"
                f"위 항목에 대해 질문합니다: {question}"
            )
            messages.append({"role": "user", "content": first_user_msg})
        else:
            # 히스토리의 첫 번째 질문에 컨텍스트가 붙어있으므로 그대로 재구성
            first_q, first_a = history[0]
            first_user_msg = (
                f"다음 항목에 대해 분석 결과가 있습니다:\n\n"
                f"=== 분석 대상 정보 ===\n{ctx_str}\n===================\n\n"
                f"위 항목에 대해 질문합니다: {first_q}"
            )
            messages.append({"role": "user", "content": first_user_msg})
            messages.append({"role": "assistant", "content": first_a})
            for prev_q, prev_a in history[1:]:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_a})
            messages.append({"role": "user", "content": question})
    else:
        # 컨텍스트 없음 — 일반 질문
        for prev_q, prev_a in (history or []):
            messages.append({"role": "user", "content": prev_q})
            messages.append({"role": "assistant", "content": prev_a})
        messages.append({"role": "user", "content": question})

    response = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=1000
    )
    result = response.choices[0].message.content
    result = result.replace("**", "")
    return result


def ask_llm_triage(minimal_text, model):
    """
    1단계(Triage): 초소형 텍스트를 보고 문제가 있는지(1) 없는지(0)만 반환합니다.
    """
    system_prompt = (
        "당신은 컴퓨터 자원 상태를 사전 진단하는 분류기(Triage)입니다. "
        "주어진 자원 요약을 보고, 비정상적인 자원 낭비나 시스템 과부하(메모리 누수, CPU 과점유 등)가 의심되어 "
        "정밀 분석 및 프로세스 종료 조치가 필요하다면 숫자 '1'을, 정상 범위라면 숫자 '0'만을 출력하십시오. "
        "설명 없이 오직 0 또는 1만 출력하세요."
    )
    
    response = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": minimal_text}
        ],
        temperature=0.1,
        max_tokens=5
    )
    
    result = response.choices[0].message.content.strip()
    
    # 예외 처리: AI가 실수로 문장을 뱉어냈을 경우에 대비한 방어 코드
    if "1" in result:
        return True
    elif "0" in result:
        return False
    else:
        # 0도 1도 아닌 이상한 대답을 했다면, 혹시 모를 위험에 대비해 
        # 무조건 2단계 정밀 분석을 돌리도록 True(비정상)를 반환합니다. (Safe fallback)
        return True
