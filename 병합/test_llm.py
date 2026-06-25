import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "지정한 프로세스를 강제 종료합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "종료할 프로세스의 PID"
                    }
                },
                "required": ["pid"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are an assistant that kills bad processes by calling the kill_process tool."},
        {"role": "user", "content": "Please kill process 1234."}
    ],
    tools=TOOLS,
    tool_choice="auto",
    temperature=0.3
)

print(response.choices[0].message)
