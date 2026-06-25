"""시스템 동작(프로세스 종료 / 파일 삭제 / 프로그램 제거)과
AI 판단(프로세스 최적화 / 보안 프로그램 / 악성파일) 백엔드.

UI(resource_advisor_gui.py)에서 호출하며, 모든 함수는 예외를 던지지 않고
결과/오류를 구조화해 반환하는 것을 원칙으로 한다(스레드에서 안전하게 사용).
"""

import json
import hashlib
import os
import re
import subprocess
import time
from datetime import datetime

import psutil

from resource_core import _get_client, OPENROUTER_API_KEY

# send2trash가 있으면 휴지통으로 보내고, 없으면 영구 삭제로 폴백한다.
try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

# 종료/삭제하면 안 되는 핵심 시스템 프로세스 (안전장치)
# 이 목록에 있는 프로세스를 강제 종료하면 화면이 멈추거나(검은 화면/로그오프)
# 최악의 경우 블루스크린(BSOD)·재부팅으로 이어질 수 있다. AI가 추천하더라도
# list_running_processes()에서 미리 제외해 사용자가 선택지로조차 보지 못하게 하고,
# kill_process_by_name()에서도 한 번 더 막는 이중 안전장치다.
PROTECTED_PROCESS_NAMES = {
    "system", "system idle process", "registry", "secure system", "memcompression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "lsaiso.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe",
    "explorer.exe", "spoolsv.exe", "sihost.exe", "conhost.exe", "userinit.exe",
    "logonui.exe", "wudfhost.exe", "dashost.exe", "taskhostw.exe", "ctfmon.exe",
    "python.exe", "pythonw.exe",  # 본 앱 자신
}

# 악성파일 스캔 대상 경로 (사용자 폴더 기준)
def _default_scan_dirs():
    home = os.path.expanduser("~")
    return [
        os.path.join(home, "Downloads"),
        os.path.join(home, "AppData", "Local", "Temp"),
        os.environ.get("TEMP", os.path.join(home, "AppData", "Local", "Temp")),
        os.path.join(home, "Desktop"),
    ]


# ─────────────────────────────────────────────────────────────
# 공용 헬퍼
# ─────────────────────────────────────────────────────────────
def _run_powershell_json(script, timeout=30):
    """PowerShell 스크립트를 실행하고 JSON 결과를 list로 반환한다. 실패 시 []."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
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


def _extract_json(text):
    """LLM 응답에서 JSON 객체를 추출해 파싱한다. 실패 시 None."""
    if not text:
        return None
    # ```json ... ``` 코드펜스 제거
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # 가장 바깥 중괄호 구간 추출
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = candidate[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return _repair_truncated_json(snippet)


def _repair_truncated_json(snippet):
    """max_tokens에 걸려 응답이 "items" 배열 중간에서 끊긴 경우를 복구한다.

    설치 프로그램이 많을 때처럼 입력이 크면 모델이 항목을 나열하다 토큰
    한도에서 잘릴 수 있다. 마지막으로 완전히 닫힌 객체까지만 살리고
    배열/객체를 닫아주면, 일부 항목이라도 정상적으로 보여줄 수 있다.
    """
    idx = snippet.find('"items"')
    if idx == -1:
        return None
    arr_start = snippet.find("[", idx)
    if arr_start == -1:
        return None

    in_string = False
    escape = False
    obj_depth = 0
    last_good = -1
    for i in range(arr_start, len(snippet)):
        ch = snippet[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            obj_depth += 1
        elif ch == "}":
            obj_depth -= 1
            if obj_depth == 0:
                last_good = i

    if last_good == -1:
        return None
    repaired = snippet[:last_good + 1] + "]}"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def _ask_llm_json(system_prompt, user_prompt, model, temperature=0.2, max_tokens=1500):
    """LLM에 JSON 응답을 요청하고 파싱한 dict를 반환한다.

    반환: (data_dict, error_str). 성공 시 error_str=None.
    """
    if not OPENROUTER_API_KEY:
        return None, "OPENROUTER_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요."
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
    except Exception as e:  # API 오류, 네트워크 오류 등
        return None, f"AI 호출 실패: {e}"

    data = _extract_json(content)
    if data is None:
        return None, "AI 응답을 JSON으로 해석하지 못했습니다."
    return data, None


def _human_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def _file_sha256(path, limit_bytes=None):
    h = hashlib.sha256()
    read_total = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk_size = 1024 * 1024
                if limit_bytes is not None:
                    remaining = limit_bytes - read_total
                    if remaining <= 0:
                        break
                    chunk_size = min(chunk_size, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
                read_total += len(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _file_content_sample(path, max_bytes=24576):
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
    except OSError:
        return ""
    if not data:
        return ""

    text_exts = {
        ".txt", ".log", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".jse", ".wsf",
        ".hta", ".py", ".pyw", ".json", ".xml", ".ini", ".cfg", ".reg",
        ".html", ".htm", ".url",
    }
    ext = os.path.splitext(path)[1].lower()
    if ext in text_exts or b"\x00" not in data[:4096]:
        for enc in ("utf-8-sig", "utf-16", "cp949", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("latin-1", errors="replace")
        text = text.replace("\x00", "")
        return "TEXT SAMPLE:\n" + text[:12000]

    head = data[:4096].hex(" ")
    tail = data[-4096:].hex(" ") if len(data) > 4096 else ""
    sample = "BINARY HEX HEAD:\n" + head
    if tail:
        sample += "\nBINARY HEX TAIL:\n" + tail
    return sample


# ─────────────────────────────────────────────────────────────
# 1. 프로세스 최적화
# ─────────────────────────────────────────────────────────────
def list_running_processes(limit=40):
    """실행 중 프로세스를 CPU+메모리 사용량 기준으로 정렬해 반환한다.

    각 속성을 개별 try-except로 감싸 Windows 일반 사용자 권한에서도
    AccessDenied나 로우 레벨 시스템 에러에 의해 프로세스 목록 수집이 중단되거나
    특정 프로세스가 누락되지 않도록 극도의 안정성을 제공한다.

    username()은 의도적으로 호출하지 않는다: 내부적으로 LookupAccountSid를 타는데
    도메인 조인 환경에서 DC를 못 찾으면 프로세스 하나당 수십 초씩 멈출 수 있고,
    어차피 분석 프롬프트에서도 쓰이지 않는 값이다.

    PROTECTED_PROCESS_NAMES(핵심 시스템 프로세스)와 본 프로그램 자신의 PID는
    여기서부터 제외한다 - AI가 추천할 후보 자체에 들어가지 않게 해야 "분석에서
    제외됨"이 아니라 처음부터 종료 대상 목록에 나타나지 않는다.
    """
    own_pid = os.getpid()
    procs = []
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                pid = p.pid
                if pid == own_pid:
                    continue

                try:
                    name = p.name() or "?"
                except Exception:
                    name = "?"

                if name.lower() in PROTECTED_PROCESS_NAMES:
                    continue

                try:
                    exe = p.exe() or ""
                except Exception:
                    exe = ""

                try:
                    cpu_percent = p.cpu_percent(interval=None) or 0.0
                except Exception:
                    cpu_percent = 0.0

                try:
                    mem = p.memory_info()
                    mem_mb = (mem.rss / (1024 ** 2)) if mem else 0.0
                except Exception:
                    mem_mb = 0.0

                procs.append({
                    "pid": pid,
                    "name": name,
                    "exe": exe,
                    "cpu_percent": cpu_percent,
                    "mem_mb": mem_mb,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue

    procs.sort(key=lambda r: (r["cpu_percent"], r["mem_mb"]), reverse=True)
    return procs[:limit]


def analyze_unnecessary_processes(processes, model, temperature=0.2):
    """AI로 불필요한(낭비성) 프로세스를 판단한다.

    반환: (items, error). items = [{name, reason, severity, safe_to_kill}]
    """
    lines = [
        f"- {p['name']} (PID {p['pid']}): CPU {p['cpu_percent']:.1f}%, "
        f"메모리 {p['mem_mb']:.0f}MB, 경로 {p['exe'] or 'N/A'}"
        for p in processes
    ]
    system_prompt = (
        "당신은 Windows 시스템 최적화 전문가입니다. 실행 중인 프로세스 목록을 보고 "
        "사용자 작업에 불필요하거나 자원을 낭비하는, 종료해도 안전한 프로세스를 식별합니다.\n"
        "OS 핵심 프로세스(svchost, csrss, wininit, lsass, dwm, explorer 등)나 보안 솔루션의 "
        "실시간 보호 코어는 절대 종료 대상으로 추천하지 마세요.\n"
        "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트는 출력하지 마세요.\n"
        '{"items":[{"name":"프로세스명","reason":"왜 불필요한지 한 문장","severity":"high|medium|low",'
        '"safe_to_kill":true}]}'
    )
    user_prompt = "현재 실행 중인 프로세스 목록입니다:\n" + "\n".join(lines)

    data, err = _ask_llm_json(system_prompt, user_prompt, model, temperature)
    if err:
        return [], err

    # 프로세스명 → 실행 중 PID 매핑
    name_to_pids = {}
    for p in processes:
        name_to_pids.setdefault(p["name"].lower(), []).append(p["pid"])

    items = []
    for it in data.get("items", []):
        name = (it.get("name") or "").strip()
        if not name:
            continue
        items.append({
            "name": name,
            "reason": (it.get("reason") or "").strip() or "사유 없음",
            "severity": (it.get("severity") or "low").lower(),
            "safe_to_kill": bool(it.get("safe_to_kill", False)),
            "pids": name_to_pids.get(name.lower(), []),
        })
    return items, None


def kill_process_by_name(name):
    """이름이 일치하는 모든 프로세스를 종료한다. (보호 목록·본 프로그램 자신은 건너뜀)

    반환: {killed:[pid...], failed:[(pid, error)...], skipped:bool}
    """
    if name.lower() in PROTECTED_PROCESS_NAMES:
        return {"killed": [], "failed": [], "skipped": True}

    own_pid = os.getpid()
    killed, failed = [], []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info.get("name") or "").lower() != name.lower():
                continue
            if p.info.get("pid") == own_pid:
                continue
            p.terminate()
            try:
                p.wait(timeout=3)
            except psutil.TimeoutExpired:
                p.kill()
            killed.append(p.info["pid"])
        except (psutil.NoSuchProcess,):
            continue
        except psutil.AccessDenied as e:
            failed.append((p.info.get("pid"), f"권한 거부: {e}"))
        except Exception as e:
            failed.append((p.info.get("pid"), str(e)))
    return {"killed": killed, "failed": failed, "skipped": False}


# ─────────────────────────────────────────────────────────────
# 2. 저장공간 분석
# ─────────────────────────────────────────────────────────────
def _temp_dirs():
    dirs = []
    for key in ("TEMP", "TMP"):
        v = os.environ.get(key)
        if v and os.path.isdir(v) and v not in dirs:
            dirs.append(v)
    win_temp = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")
    if os.path.isdir(win_temp) and win_temp not in dirs:
        dirs.append(win_temp)
    return dirs


def _iter_file_entries(dirs):
    """os.walk + os.stat() 조합 대신 os.scandir()가 디렉터리를 읽을 때 함께
    캐싱해 주는 stat 정보를 그대로 쓴다. os.walk는 내부적으로 scandir를 쓰면서도
    DirEntry를 버리고 파일명만 넘기기 때문에, 호출자가 os.stat(path)을 다시
    부르면 파일마다 디스크에 한 번 더 접근하는 syscall이 추가된다. 파일이
    수만 개인 폴더에서는 이 차이가 체감 속도를 좌우한다."""
    stack = [d for d in dirs if os.path.isdir(d)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            yield entry
                    except OSError:
                        continue
        except OSError:
            continue


def _count_files(dirs):
    """stat 없이 디렉터리만 훑어 전체 파일 수를 빠르게 센다(진행률의 분모)."""
    total = 0
    for _ in _iter_file_entries(dirs):
        total += 1
    return total


def _is_under(path, root):
    path_n = os.path.normcase(os.path.normpath(path))
    root_n = os.path.normcase(os.path.normpath(root))
    return path_n == root_n or path_n.startswith(root_n + os.sep)


def _format_progress(done, total, elapsed):
    if total <= 0:
        return f"스캔 중... {done}개 파일 확인"
    pct = min(done / total * 100, 100.0)
    if done <= 0 or elapsed <= 0:
        return f"스캔 중... {pct:.0f}% ({done}/{total}개)"
    rate = done / elapsed
    remaining_sec = max(total - done, 0) / rate if rate > 0 else 0
    eta_txt = f"{remaining_sec / 60:.1f}분" if remaining_sec >= 60 else f"{remaining_sec:.0f}초"
    return f"스캔 중... {pct:.0f}% ({done}/{total}개) · 남은 시간 약 {eta_txt}"


def scan_temp_files():
    """Temp 폴더의 파일 목록과 총 용량을 반환한다.

    반환: {dirs:[...], files:[{path, size, size_h, mtime}], total_bytes, total_h, count}
    """
    files = []
    total = 0
    for entry in _iter_file_entries(_temp_dirs()):
        try:
            stt = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        files.append({
            "path": entry.path, "size": stt.st_size,
            "size_h": _human_size(stt.st_size),
            "mtime": stt.st_mtime,
        })
        total += stt.st_size
    files.sort(key=lambda f: f["size"], reverse=True)
    return {
        "dirs": _temp_dirs(), "files": files, "count": len(files),
        "total_bytes": total, "total_h": _human_size(total),
    }


def scan_storage(min_large_mb=100, older_than_days=180, old_min_size_mb=10, limit=50, progress_cb=None):
    """Temp 파일, 대용량 파일, 오래된 파일을 단일 폴더 순회로 함께 수집한다.

    이전에는 scan_temp_files/find_large_files/find_old_files가 같은 폴더들을
    각각 따로 훑어서(거의 같은 대상을 3번 walk) 체감 시간이 늘어났다. 한 번의
    순회에서 세 기준을 동시에 판단해 시간을 줄이고, progress_cb(done, total,
    elapsed_sec)를 주기적으로 호출해 호출자가 진행률·예상 잔여 시간을 표시할
    수 있게 한다.
    """
    temp_dirs = _temp_dirs()
    scan_dirs = _default_scan_dirs()

    all_dirs, seen = [], set()
    for d in temp_dirs + scan_dirs:
        key = os.path.normcase(os.path.normpath(d))
        if key not in seen:
            seen.add(key)
            all_dirs.append(d)

    if progress_cb:
        progress_cb("대상 파일 수를 세는 중...")
    total = _count_files(all_dirs)

    min_large_bytes = min_large_mb * 1024 * 1024
    old_cutoff = time.time() - older_than_days * 86400
    old_min_bytes = old_min_size_mb * 1024 * 1024

    temp_files, large_files, old_files = [], [], []
    temp_total_bytes = 0
    done = 0
    start = time.time()
    last_report = start

    for entry in _iter_file_entries(all_dirs):
        done += 1
        try:
            stt = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        fp = entry.path
        size_h = _human_size(stt.st_size)

        if any(_is_under(fp, td) for td in temp_dirs):
            temp_files.append({"path": fp, "size": stt.st_size, "size_h": size_h, "mtime": stt.st_mtime})
            temp_total_bytes += stt.st_size

        if stt.st_size >= min_large_bytes:
            large_files.append({"path": fp, "size": stt.st_size, "size_h": size_h, "mtime": stt.st_mtime})

        if stt.st_mtime < old_cutoff and stt.st_size >= old_min_bytes:
            old_files.append({
                "path": fp, "size": stt.st_size, "size_h": size_h, "mtime": stt.st_mtime,
                "age_days": int((time.time() - stt.st_mtime) / 86400),
            })

        now = time.time()
        if progress_cb and (now - last_report >= 0.3 or done == total):
            progress_cb(_format_progress(done, total, now - start))
            last_report = now

    temp_files.sort(key=lambda f: f["size"], reverse=True)
    large_files.sort(key=lambda f: f["size"], reverse=True)
    old_files.sort(key=lambda f: f["mtime"])

    return {
        "temp": {
            "dirs": temp_dirs, "files": temp_files, "count": len(temp_files),
            "total_bytes": temp_total_bytes, "total_h": _human_size(temp_total_bytes),
        },
        "large": large_files[:limit],
        "old": old_files[:limit],
    }


def delete_files(paths):
    """파일 목록을 삭제한다. send2trash가 있으면 휴지통, 없으면 영구 삭제.

    반환: {deleted:[path...], freed_bytes, freed_h, failed:[(path, error)...]}
    """
    deleted, failed, freed = [], [], 0
    for p in paths:
        try:
            size = os.path.getsize(p) if os.path.exists(p) else 0
        except OSError:
            size = 0
        try:
            if HAS_SEND2TRASH:
                send2trash(p)
            else:
                os.remove(p)
            deleted.append(p)
            freed += size
        except (PermissionError, OSError) as e:
            failed.append((p, str(e)))
    return {
        "deleted": deleted, "freed_bytes": freed,
        "freed_h": _human_size(freed), "failed": failed,
        "to_trash": HAS_SEND2TRASH,
    }


# ─────────────────────────────────────────────────────────────
# 3. 설치된 프로그램 / 보안 프로그램(구라제거기)
# ─────────────────────────────────────────────────────────────
def list_installed_programs():
    """레지스트리 Uninstall 키에서 설치된 프로그램 목록을 읽는다.

    Get-ItemProperty에 와일드카드 경로(...\\Uninstall\\*)를 한 번에 넘기면
    일부 항목의 값 타입(REG_NONE 등) 때문에 "Specified cast is not valid" 오류로
    전체 호출이 깨져 결과가 0개가 되는 PowerShell 5.1 버그가 있다.
    서브키 단위로 순회하며 개별 try/catch로 격리해 우회한다.
    """
    script = (
        "$keys = @("
        "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',"
        "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall',"
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'); "
        "$results = foreach ($k in $keys) { "
        "if (Test-Path $k) { "
        "Get-ChildItem $k -ErrorAction SilentlyContinue | ForEach-Object { "
        "try { "
        "$p = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction Stop; "
        "if ($p.DisplayName) { "
        "[pscustomobject]@{ DisplayName = $p.DisplayName; Publisher = $p.Publisher; "
        "DisplayVersion = $p.DisplayVersion; EstimatedSize = $p.EstimatedSize; "
        "UninstallString = $p.UninstallString; QuietUninstallString = $p.QuietUninstallString } "
        "} } catch {} } } }; "
        "$results | Sort-Object DisplayName -Unique | ConvertTo-Json -Compress"
    )
    raw = _run_powershell_json(script, timeout=40)
    programs = []
    for item in raw:
        name = (item.get("DisplayName") or "").strip()
        if not name:
            continue
        size_kb = item.get("EstimatedSize") or 0
        programs.append({
            "name": name,
            "publisher": (item.get("Publisher") or "").strip(),
            "version": (item.get("DisplayVersion") or "").strip(),
            "size_mb": (size_kb / 1024.0) if size_kb else 0.0,
            "uninstall_string": (item.get("QuietUninstallString")
                                 or item.get("UninstallString") or "").strip(),
        })
    return programs


# 거의 항상 '구라백신/PUP' 판단 대상이 될 수 없는 보일러플레이트 설치 항목.
# 레지스트리 Uninstall 키에는 보통 수백 개가 잡히는데, 이런 런타임/드라이버/
# 업데이트 패키지를 그대로 AI에게 다 보내면 프롬프트가 비대해져 응답이
# max_tokens에서 잘려 JSON 파싱이 깨지는 원인이 된다.
_BLOATWARE_NOISE_RE = re.compile(
    r"(microsoft visual c\+\+|\.net (framework|core|runtime)|"
    r"windows driver package|security update for|update for (microsoft|windows)|"
    r"hotfix for|servicing stack update|visual studio (2015|2017|2019|2022)|"
    r"directx|redistributable)",
    re.IGNORECASE,
)

# 설치 목록이 매우 많을 때 AI에게 보내는 프롬프트/응답 크기를 한계 내로 유지하기
# 위한 상한선. (프로그램당 응답 토큰을 ~30~40으로 잡아도 250개면 max_tokens=4000
# 안에 충분히 들어간다.)
_BLOATWARE_MAX_PROGRAMS = 250


def analyze_security_bloatware(programs, running_names, model, temperature=0.2):
    """AI로 '구라백신' / 불필요 보안·최적화 프로그램을 판단한다.

    반환: (items, error). items=[{name, reason, recommendation, severity}]
    """
    running_lower = {n.lower() for n in running_names}

    candidates = [p for p in programs if not _BLOATWARE_NOISE_RE.search(p["name"])]
    if len(candidates) > _BLOATWARE_MAX_PROGRAMS:
        candidates = candidates[:_BLOATWARE_MAX_PROGRAMS]

    prog_lines = [
        f"- {p['name']} | 게시자: {p['publisher'] or '미상'} | "
        f"크기: {p['size_mb']:.0f}MB | 실행중: {'예' if p['name'].lower() in running_lower else '아니오'}"
        for p in candidates
    ]
    running_note = "현재 실행 중인 프로세스: " + ", ".join(sorted(running_names)[:40])

    system_prompt = (
        "당신은 Windows의 불필요한 보안/최적화 소프트웨어를 가려내는 '구라제거기' 전문가입니다. "
        "설치 목록에서 다음을 식별하세요: 효과가 과장된 '최적화/클리너/부스터' 류, 중복 백신, "
        "동의 없이 끼워팔기로 설치되는 PUP(잠재적 원치 않는 프로그램), 광고성 보안 토스트를 띄우는 프로그램, "
        "리소스를 과도하게 점유하는 보안 프로그램.\n"
        "정상적인 주류 백신(Windows Defender, 알약/V3 등 정식 제품)이나 OS 구성요소는 신중히 다루고, "
        "확실치 않으면 항목 자체를 결과에 포함하지 마세요. recommendation이 'keep'인 프로그램은 "
        "결과에 넣지 말고 생략하세요(문제 있는 항목만 응답에 포함).\n"
        "반드시 아래 JSON 형식으로만 답하세요.\n"
        '{"items":[{"name":"프로그램명(설치목록과 동일하게)","reason":"판단 근거 한두 문장",'
        '"recommendation":"uninstall|disable","severity":"high|medium|low"}]}'
    )
    user_prompt = running_note + "\n\n설치된 프로그램 목록:\n" + "\n".join(prog_lines)

    data, err = _ask_llm_json(system_prompt, user_prompt, model, temperature, max_tokens=4000)
    if err:
        return [], err

    by_name = {p["name"].lower(): p for p in programs}
    items = []
    for it in data.get("items", []):
        name = (it.get("name") or "").strip()
        if not name:
            continue
        prog = by_name.get(name.lower())
        items.append({
            "name": name,
            "reason": (it.get("reason") or "").strip() or "사유 없음",
            "recommendation": (it.get("recommendation") or "keep").lower(),
            "severity": (it.get("severity") or "low").lower(),
            "uninstall_string": prog["uninstall_string"] if prog else "",
            "running": name.lower() in running_lower,
        })
    return items, None


def uninstall_program(uninstall_string):
    """프로그램 제거 명령을 실행한다.

    반환: (success, message). 제거 관리자 창이 뜰 수 있어 사용자 상호작용이 필요할 수 있다.
    """
    if not uninstall_string:
        return False, "제거 명령(UninstallString)을 찾을 수 없습니다."
    try:
        # UninstallString은 보통 'msiexec /X{GUID}' 또는 'C:\...\unins000.exe /...'
        subprocess.Popen(uninstall_string, shell=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True, "제거 관리자를 실행했습니다. 화면의 안내를 따르세요."
    except Exception as e:
        return False, f"제거 실행 실패: {e}"


# ─────────────────────────────────────────────────────────────
# 4. 악성파일 분석
# ─────────────────────────────────────────────────────────────
_SUSPICIOUS_EXTS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".vbe",
    ".js", ".jse", ".ps1", ".wsf", ".hta", ".jar", ".msi", ".lnk", ".dll",
}


def collect_files_for_malware_scan(dirs=None, max_files=120):
    """주요 경로에서 실행/스크립트 계열 파일을 수집하고 서명 정보를 붙인다."""
    dirs = dirs or _default_scan_dirs()
    collected = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _, names in os.walk(d):
            for n in names:
                ext = os.path.splitext(n)[1].lower()
                if ext not in _SUSPICIOUS_EXTS:
                    continue
                fp = os.path.join(root, n)
                try:
                    stt = os.stat(fp)
                except OSError:
                    continue
                collected.append({
                    "path": fp, "name": n, "ext": ext,
                    "size": stt.st_size, "size_h": _human_size(stt.st_size),
                    "mtime": datetime.fromtimestamp(stt.st_mtime).strftime("%Y-%m-%d"),
                    "signature": "Unknown", "signer": "",
                })
                if len(collected) >= max_files:
                    break
            if len(collected) >= max_files:
                break

    _attach_signatures(collected)
    return collected


def collect_selected_files_for_malware_scan(paths, include_content=True, max_files=5):
    """사용자가 직접 고른 파일을 악성파일 분석용 레코드로 변환한다."""
    collected = []
    for fp in list(paths or [])[:max_files]:
        if not os.path.isfile(fp):
            continue
        try:
            stt = os.stat(fp)
        except OSError:
            continue
        rec = {
            "path": fp,
            "name": os.path.basename(fp),
            "ext": os.path.splitext(fp)[1].lower(),
            "size": stt.st_size,
            "size_h": _human_size(stt.st_size),
            "mtime": datetime.fromtimestamp(stt.st_mtime).strftime("%Y-%m-%d"),
            "signature": "Unknown",
            "signer": "",
            "sha256": _file_sha256(fp),
        }
        if include_content:
            rec["content_sample"] = _file_content_sample(fp)
        collected.append(rec)

    _attach_signatures(collected)
    return collected


def _attach_signatures(files):
    """Get-AuthenticodeSignature로 서명 상태를 일괄 조회해 채운다(best-effort)."""
    if not files:
        return
    path_list = [f["path"] for f in files]
    # 경로 배열을 JSON으로 넘겨 한 번에 처리
    paths_json = json.dumps(path_list)
    script = (
        "$paths = '" + paths_json.replace("'", "''") + "' | ConvertFrom-Json; "
        "$paths | ForEach-Object { $p = $_; "
        "try { $s = Get-AuthenticodeSignature -LiteralPath $p -ErrorAction Stop; "
        "$signer = ''; if ($s.SignerCertificate) { $signer = $s.SignerCertificate.Subject }; "
        "[pscustomobject]@{ Path = $p; Status = $s.Status.ToString(); Signer = $signer } } "
        "catch { [pscustomobject]@{ Path = $p; Status = 'Error'; Signer = '' } } } | "
        "ConvertTo-Json -Compress"
    )
    rows = _run_powershell_json(script, timeout=60)
    by_path = {}
    for r in rows:
        by_path[(r.get("Path") or "")] = r
    for f in files:
        r = by_path.get(f["path"])
        if r:
            f["signature"] = r.get("Status") or "Unknown"
            signer = r.get("Signer") or ""
            m = re.search(r"CN=([^,]+)", signer)
            f["signer"] = m.group(1).strip() if m else signer[:60]


def analyze_malware(files, model, temperature=0.1):
    """AI로 파일들의 위험도를 판단한다.

    반환: (items, error). items=[{path, name, risk, threat_type, reason}]
    """
    lines = [
        f"- {f['name']} | 경로: {f['path']} | 크기: {f['size_h']} | "
        f"수정일: {f['mtime']} | 서명: {f['signature']}"
        f"{(' (' + f['signer'] + ')') if f.get('signer') else ''}"
        f"{(' | SHA256: ' + f['sha256']) if f.get('sha256') else ''}"
        for f in files
    ]
    for idx, f in enumerate(files):
        sample = (f.get("content_sample") or "").strip()
        if sample:
            lines[idx] += "\n  파일 내용 샘플:\n" + sample[:16000]

    system_prompt = (
        "당신은 악성코드 분석가입니다. 파일명, 경로, 크기, 코드서명 상태를 근거로 각 파일의 위험도를 "
        "평가합니다. 파일 내용 샘플이나 hex 샘플이 제공되면 난독화, 다운로드/실행, 자동시작, 권한상승, "
        "방어 회피, 의심 URL/명령어 패턴을 함께 확인하세요. 정밀 백신 스캔이 아닌 휴리스틱 판단임을 전제로, 의심스러운 패턴(서명 없음/위조 의심, "
        "이중 확장자, 임시폴더 내 실행파일, 랜섬웨어/드로퍼/크랙 유사 파일명 등)을 식별하세요.\n"
        "위험도(risk)는 '위험' / '주의' / '정상' 중 하나로 판단하고, 정상으로 보이는 파일은 생략해도 됩니다.\n"
        "반드시 아래 JSON 형식으로만 답하세요.\n"
        '{"items":[{"path":"전체경로(입력과 동일하게)","risk":"위험|주의|정상",'
        '"threat_type":"위협 유형(예: 드로퍼, 크랙, PUP, 불명)","reason":"판단 근거 한두 문장"}]}'
    )
    user_prompt = "다음 파일들을 분석하세요:\n" + "\n".join(lines)

    data, err = _ask_llm_json(system_prompt, user_prompt, model, temperature, max_tokens=2500)
    if err:
        return [], err

    by_path = {f["path"]: f for f in files}
    items = []
    for it in data.get("items", []):
        path = (it.get("path") or "").strip()
        risk = (it.get("risk") or "").strip()
        if not path or risk == "정상":
            continue
        src = by_path.get(path, {})
        items.append({
            "path": path,
            "name": src.get("name") or os.path.basename(path),
            "risk": risk or "주의",
            "threat_type": (it.get("threat_type") or "불명").strip(),
            "reason": (it.get("reason") or "").strip() or "사유 없음",
            "size_h": src.get("size_h", ""),
            "signature": src.get("signature", ""),
        })
    # 위험 → 주의 순 정렬
    order = {"위험": 0, "주의": 1}
    items.sort(key=lambda r: order.get(r["risk"], 2))
    return items, None
