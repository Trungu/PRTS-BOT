# this file contains settings
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# this file contains settings
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

def get_env_var(name: str, required: bool = True) -> Optional[str]:
    value = os.getenv(name)
    if required and (value is None or value.strip() == ""):
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value

# Discord Bot
DISCORD_TOKEN = get_env_var("DISCORD_TOKEN")

# LLM API Key
LLM_API_KEY = get_env_var("LLM_API_KEY")
LLM_BASE_URL = get_env_var("LLM_BASE_URL", required=False)
LLM_MODEL = get_env_var("LLM_MODEL", required=False)



