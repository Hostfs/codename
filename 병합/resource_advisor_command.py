import os
import re
import psutil

# -------------------------------------------------------------------
# 명령어 레지스트리 (Registry)
# -------------------------------------------------------------------
COMMANDS = []

def advisor_command(name: str, format_str: str, example_str: str, description: str):
    """
    명령어 설명과 실행 함수를 함께 등록하는 데코레이터입니다.
    """
    def decorator(func):
        COMMANDS.append({
            "name": name,
            "format": format_str,
            "example": example_str,
            "description": description,
            "func": func
        })
        return func
    return decorator

def get_commands_prompt() -> str:
    """
    등록된 모든 명령어의 설명을 모아 AI 프롬프트용 텍스트를 생성합니다.
    """
    lines = []
    for cmd in COMMANDS:
        lines.append(f"- {cmd['description']} 시: {cmd['format']} (예: {cmd['example']})")
    return "\n".join(lines)


# -------------------------------------------------------------------
# 안전을 위한 블랙리스트 정책 설정
# -------------------------------------------------------------------
PROTECTED_PROCESSES = {
    "explorer.exe", "svchost.exe", "csrss.exe", "smss.exe", "wininit.exe",
    "lsass.exe", "services.exe", "winlogon.exe", "taskmgr.exe", "system",
    "system idle process", "registry", "spoolsv.exe", "lsaiso.exe",
    "memcompression", "memory compression", "memcompression.exe", "memory compression.exe"
}

PROTECTED_PATHS = [
    os.path.normpath(os.environ.get("WINDIR", "C:\\Windows")).lower(),
    os.path.normpath(os.environ.get("PROGRAMFILES", "C:\\Program Files")).lower(),
    os.path.normpath(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")).lower()
]

def is_safe_to_kill(pid: int) -> tuple[bool, str]:
    """해당 PID가 시스템 중요 프로세스인지 확인합니다."""
    if pid == os.getpid():
        return False, "어드바이저 앱 자기 자신(Self)은 강제 종료할 수 없습니다."
        
    try:
        proc = psutil.Process(pid)
        name = proc.name().lower()
        if name in PROTECTED_PROCESSES or name in ["python.exe", "pythonw.exe"]:
            return False, f"보호된 시스템 프로세스({name})는 강제 종료할 수 없습니다."
        return True, name
    except psutil.NoSuchProcess:
        return False, "이미 존재하지 않는 프로세스입니다."
    except psutil.AccessDenied:
        return False, "접근 권한이 거부되었습니다. (관리자 권한 필요)"
    except Exception as e:
        return False, f"프로세스 확인 중 오류: {e}"

def is_safe_to_delete(file_path: str) -> tuple[bool, str]:
    """해당 경로가 삭제 가능한 안전한 경로인지 확인합니다."""
    path_lower = os.path.normpath(os.path.abspath(file_path)).lower()
    
    for protected in PROTECTED_PATHS:
        if path_lower.startswith(protected):
            return False, f"보호된 시스템 경로({protected}) 내의 파일은 삭제할 수 없습니다."
            
    if not os.path.exists(file_path):
        return False, "파일이 존재하지 않습니다."
        
    if os.path.isdir(file_path):
        return False, "디렉토리(폴더)는 이 명령으로 삭제할 수 없습니다."
        
    return True, "안전한 파일입니다."


# -------------------------------------------------------------------
# 실제 명령어 구현부
# -------------------------------------------------------------------

@advisor_command(
    name="KILL_PROCESS",
    format_str="[COMMAND:KILL_PROCESS:PID]",
    example_str="[COMMAND:KILL_PROCESS:1234]",
    description="비정상적인 자원 점유 프로세스 종료"
)
def execute_kill_process(target: str) -> tuple[bool, str]:
    try:
        pid = int(target)
    except ValueError:
        return False, f"잘못된 PID 형식입니다: {target}"
        
    safe, msg = is_safe_to_kill(pid)
    if not safe:
        return False, msg
        
    try:
        psutil.Process(pid).kill()
        return True, f"프로세스 '{msg}' (PID {pid})를 강제 종료했습니다."
    except Exception as e:
        return False, f"프로세스 종료 실패: {e}"

@advisor_command(
    name="DELETE_FILE",
    format_str="[COMMAND:DELETE_FILE:파일절대경로]",
    example_str="[COMMAND:DELETE_FILE:C:\\temp\\dummy.txt]",
    description="불필요한 파일 삭제"
)
def execute_delete_file(target: str) -> tuple[bool, str]:
    safe, msg = is_safe_to_delete(target)
    if not safe:
        return False, msg
        
    try:
        os.remove(target)
        return True, f"파일 삭제 성공: {target}"
    except Exception as e:
        return False, f"파일 삭제 실패: {e}"


# -------------------------------------------------------------------
# 파서 및 라우터
# -------------------------------------------------------------------

def parse_actions(text: str) -> list[dict]:
    """
    LLM 응답 텍스트에서 [COMMAND:유형:타겟] 형태를 찾아 동적으로 파싱합니다.
    """
    pattern = r"\[COMMAND:([^:]+):(.*?)\]"
    actions = []
    
    valid_commands = {cmd["name"] for cmd in COMMANDS}
    
    for match in re.finditer(pattern, text):
        action_type = match.group(1).strip()
        target = match.group(2).strip()
        
        if action_type in valid_commands:
            actions.append({"type": action_type, "target": target})
            
    return actions

def execute_action(action_type: str, target: str) -> tuple[bool, str]:
    """파싱된 액션을 알맞은 명령어 함수로 연결하여 실행합니다."""
    for cmd in COMMANDS:
        if cmd["name"] == action_type:
            return cmd["func"](target)
            
    return False, f"알 수 없는 명령어: {action_type}"
