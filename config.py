import os, logging, sys
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 当前文件所在目录

##
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(str(ENV_PATH))

AMAP_KEY = os.getenv("AMAP_KEY")
LLM_API_KEY = os.getenv("LLM_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL")
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")

## 读取提示词模板
def load_prompt(filename: str) -> str:
    with open(filename, "r", encoding="utf-8") as f:
        return f.read()

STRUCT_PROMPT = load_prompt(os.path.join(BASE_DIR, "struct_prompt.md"))

##
log_dir = os.path.join(BASE_DIR, "logs")
os.makedirs(log_dir, exist_ok=True)
logger = logging.getLogger("address") # 命名 logger
logger.setLevel(logging.INFO)
logger.propagate = False # 防止重复打印到 root logger

if not logger.handlers:
    
    # 文件日志
    fh = logging.FileHandler(os.path.join(log_dir, "address_resolver.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # 控制台日志
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # 添加 handler
    logger.addHandler(fh)
    logger.addHandler(ch)
