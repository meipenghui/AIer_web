from langchain.tools import tool
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from config import config
from pathlib import Path
import httpx
import tempfile
import shutil
import subprocess
import shlex
# 挂载进去的本地代码目录
WORKSPACE_DIR = r"/app/workspace"  
# 单次读取最大允许的字符数（约等于 2000-3000 个 Token）
MAX_READ_LENGTH = 30000

# ===================================================================
#    agent项目感知层
# ===================================================================

# 查询项目目录结构
@tool
def list_directory(path: str) -> str:
    """列出指定目录下的所有文件的文件路径"""
    result = []
    start_path = os.path.join(WORKSPACE_DIR, path)
    for root, dirs, files in os.walk(start_path):
        # 排除不需要看的东西
        dirs[:] = [
            d for d in dirs if d not in (".git", "node_modules", "__pycache__", "venv")
        ]

        for file in files:
            if not file.startswith("."):
                # 获取相对于根目录的路径
                rel_path = os.path.relpath(os.path.join(root, file), start_path)
                # 统一使用正斜杠（跨平台友好）
                result.append(rel_path.replace("\\", "/"))
    return result


# 读取项目文件内容，字符数 <= MAX_READ_LENGTH
@tool
def read_file(file_path: str) -> str:
    """
    读取指定文件的内容。
    :param file_path: 相对于工作区根目录的文件路径（如 'backend/main.py'）
    """
    try:
        # 1. 路径安全校验：防止路径穿越漏洞 (Directory Traversal)
        # 把相对路径转为绝对路径，并统一格式
        full_path = os.path.abspath(
            os.path.join(WORKSPACE_DIR, file_path)
        )  # 将传入的路径（无论是相对路径还是带有 ../ 的路径）转换为当前操作系统下的“绝对路径”。

        # 检查该绝对路径是否真的在我们的工作区内
        if not full_path.startswith(os.path.abspath(WORKSPACE_DIR)):
            return "❌ 错误：拒绝访问，不能读取工作区之外的文件。"

        # 2. 检查文件是否存在
        if not os.path.exists(full_path):
            return f"❌ 错误：文件 '{file_path}' 不存在。请先使用 list_directory 工具确认正确的路径。"

        # 3. 检查是否为目录（防止模型误传文件夹）
        if os.path.isdir(full_path):
            return f"❌ 错误：'{file_path}' 是一个文件夹，不能使用 read_file 读取。请使用 list_directory 工具查看。"
        # file_size = os.path.getsize(full_path)  # 文件字节数
        # 4. 读取文件与截断保护
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            # 尝试多读 1 个字符（+1）
            content = f.read(MAX_READ_LENGTH + 1)

            # 如果读出来的长度大于了规定的最大长度
            if len(content) > MAX_READ_LENGTH:
                # 砍掉那多出来的 1 个字符，只保留规定的长度
                content = content[:MAX_READ_LENGTH]
                content += "\n\n[⚠️ 警告：文件内容过长，已被截断...]"
            return content

    except Exception as e:
        # 兜底捕获，返回友好的错误信息给大模型
        return f"❌ 读取文件时发生异常: {str(e)}"

# ===================================================================
#    agent项目编辑层
# ===================================================================



# 精准修改文件特定内容
@tool
def edit_file(file_path, old_string, new_string):
    """修改文件内的特定内容，要求具备唯一性，保证唯一精准匹配，如果要删除文件内的特定内容，也可以用空白字符串覆盖原内容，达到删除效果

    Args:
        file_path (str): 待修改文件的文件路径
        old_string (str): 文件内需要被修改的旧内容，要求具备唯一性，保证唯一精准匹配
        new_string (str): 新内容，用来覆盖被修改的新内容

    Returns:
        str: 修改文件结果
    """
    try:
        # 拼接绝对路径并校验
        full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, file_path))
        if not full_path.startswith(os.path.abspath(WORKSPACE_DIR)):
            return "❌ 错误：拒绝访问，不能读取工作区之外的文件。"

        if not os.path.exists(full_path):
            return f"❌ 错误：文件 '{file_path}' 不存在。请先使用 list_directory 工具确认正确的路径。"

        if os.path.isdir(full_path):
            return f"❌ 错误：'{file_path}' 是一个文件夹，不能使用 read_file 读取。请使用 list_directory 工具查看。"
        # 1. 读取原文件
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()  #原文件很大怎么办？内存承压

        # 2. 校验唯一性
        if content.count(old_string) != 1:
            return "❌ 匹配失败或唯一性不满足"

        # 3. 生成新内容
        new_content = content.replace(old_string, new_string)

        # 4. 👇 核心安全写入：创建临时文件
        dir_name = os.path.dirname(full_path)
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, encoding="utf-8"
        ) as temp_f:
            temp_f.write(new_content)
            temp_file_name = temp_f.name

        # 5. 瞬间替换原文件（这在操作系统层面是原子操作）
        shutil.move(temp_file_name, full_path)
        return "✅ 修改成功"
    except Exception as e:
        return f"❌ 修改文件时发生异常：{str(e)}"


# ===================================================================
#    agent项目终端执行层
# ===================================================================
# 终端执行命令

# 禁止高危终端命令列表
FORBIDDEN_COMMANDS = [
    "rm -rf",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "chmod",
    "chown",
    "rd /s",
    "del /q",
    "format",
    "> /dev/sda",
]


@tool
def execute_terminal(command: str) -> str:
    """在项目根目录下执行终端命令，如 git diff, ls, pytest 等"""

    # 1. 基础安全过滤：检查是否包含高危操作
    command_lower = command.lower()
    if any(forbidden in command_lower for forbidden in FORBIDDEN_COMMANDS):
        return "❌ 拒绝执行：该命令包含高危操作，系统已拦截。"

    # 2. 限制危险的重定向（防止恶意覆盖重要文件）
    if ">" in command and not "2>&1" in command:  # 允许 2>&1，但禁止单独用 > 覆盖文件
        return "❌ 拒绝执行：请勿使用重定向符 '>'，如需写文件请使用 edit_file 工具。"

    try:
        # 3. 在 Windows 下，shell=True 可能会导致命令挂起，建议尽量用 False
        # 如果必须用 shell=True（比如需要执行管道符 | 或者 &&），请务必保证 cwd 的安全
        result = subprocess.run(
            command,
            shell=True,  # 允许执行系统自带命令，但配合上面的黑名单
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,  # 最长 30 秒，防止大模型跑个死循环把服务器卡死
        )

        output = result.stdout + result.stderr   #捕获终端标准输出与错误

        # 4. 🛑 极其重要：限制输出长度（截断）
        # 如果模型执行了一个 `cat 巨型日志.log` 或 `find /`，输出会撑爆上下文
        MAX_OUTPUT_LENGTH = 5000
        if len(output) > MAX_OUTPUT_LENGTH:
            output = (
                output[:MAX_OUTPUT_LENGTH] + "\n\n[⚠️ 警告：终端输出过长，已被截断...]"
            )

        return output if output.strip() else "✅ 命令执行成功，无控制台输出。"

    except subprocess.TimeoutExpired:
        return "❌ 执行超时：命令超过 30 秒被强制终止。"
    except Exception as e:
        return f"❌ 终端命令执行异常: {str(e)}"


# 创建新文件/文件夹
@tool
def create_file(file_path: str, content: str = "") -> str:
    """
    创建新文件或文件夹，并写入初始内容。

    :param file_path: 相对于工作区的路径。如果要建文件夹，请在末尾加上 '/'（例如 'src/utils/'）
    :param content: 文件的初始内容（如果是创建文件夹，此参数会被忽略）
    """
    try:
        # 1. 安全校验：路径防穿越
        base_dir = Path(WORKSPACE_DIR).resolve()
        target_path = (base_dir / file_path).resolve()

        if base_dir not in target_path.parents and target_path != base_dir:
            return "❌ 错误：拒绝访问，不能在非工作区目录创建文件。"

        # 2. 防呆校验：防止模型误覆盖已有文件或目录
        if target_path.exists():
            return f"❌ 错误：'{file_path}' 已存在。如果需要修改内容，请使用 edit_file 工具；如果需要新建同名文件，请先使用 delete_item 删除原文件。"

        # 3. 判断是建文件夹还是建文件（根据路径末尾是否有斜杠）
        if file_path.endswith("/") or file_path.endswith("\\"):
            # 创建文件夹
            target_path.mkdir(parents=True, exist_ok=True)  # parents=True递归创建
            return f"✅ 文件夹 '{file_path}' 创建成功。"
        else:
            # 创建文件
            # 自动创建缺失的父级目录（例如文件在 src/models/user.py，会自动建 src 和 models 文件夹）
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入初始内容
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)

            return f"✅ 文件 '{file_path}' 创建成功并写入了 {len(content)} 个字符。"

    except PermissionError:
        return "❌ 错误：权限不足，无法在此目录创建文件。"
    except Exception as e:
        return f"❌ 创建失败: {str(e)}"


# 移动/重命名文件
@tool
def move_file(source_path: str, target_path: str) -> str:
    """
    移动或重命名文件/文件夹。

    :param source_path: 原文件的相对路径（如 'src/old_name.py'）
    :param target_path: 目标路径的相对路径（如 'src/new_name.py' 或 'utils/new_name.py'）
    """
    try:
        # 1. 安全路径解析
        base_dir = Path(WORKSPACE_DIR).resolve()
        src_full = (base_dir / source_path).resolve()
        tgt_full = (base_dir / target_path).resolve()

        # 2. 越权校验
        for p in [src_full, tgt_full]:
            if base_dir not in p.parents and p != base_dir:
                return "❌ 错误：拒绝访问，路径超出了工作区范围。"

        # 3. 防呆校验：原文件必须存在
        if not src_full.exists():
            return f"❌ 错误：源路径 '{source_path}' 不存在，无法移动。请先使用 list_directory 确认路径。"

        # 4. 防呆校验：防止覆盖已有文件（极其重要！）
        if tgt_full.exists():
            return f"❌ 错误：目标路径 '{target_path}' 已存在。为防止代码丢失，拒绝覆盖。如果确实要覆盖，请先删除目标文件。"

        # 5. 自动创建目标父级目录
        # 比如要把文件移动到 'new_dir/file.py'，但 new_dir 不存在，会自动帮你建
        tgt_full.parent.mkdir(parents=True, exist_ok=True)

        # 6. 执行移动/重命名（shutil.move 非常强大，文件和文件夹都能移）
        shutil.move(str(src_full), str(tgt_full))

        return f"✅ 成功：已将 '{source_path}' 移动/重命名为 '{target_path}'。"

    except Exception as e:
        return f"❌ 移动/命名命名时发生异常: {str(e)}"


# 删除文件/文件夹
@tool
def delete_item(target_path: str) -> str:
    """
    删除指定的文件或文件夹（如果是文件夹，将递归删除其内部所有内容）。
    请谨慎使用此工具。

    :param target_path: 相对于工作区根目录的路径（例如 'temp/test.txt' 或 'old_dir/'）
    """
    try:
        # 1. 基础清理与路径解析
        # 去掉路径首尾的空格，防止大模型多输入了空格
        target_path = target_path.strip()

        base_dir = Path(WORKSPACE_DIR).resolve()
        target_full = (base_dir / target_path).resolve()

        # 2. 🚨 极度危险拦截：不允许删除工作区根目录本身
        if target_full == base_dir:
            return "❌ 错误：拒绝执行！绝对不允许删除工作区根目录。"

        # 3. 越权拦截：防止路径穿越
        if base_dir not in target_full.parents:
            return f"❌ 错误：拒绝访问。路径 '{target_path}' 超出了工作区范围。"

        # 4. 防呆拦截：如果路径不存在，直接返回，不要报错（模型经常重复删）
        if not target_full.exists():
            return f"⚠️ 提示：'{target_path}' 根本不存在，无需删除。"

        # 5. 防呆拦截：禁止使用通配符（防止 rm -rf * 类似操作）
        if "*" in target_path or "?" in target_path:
            return (
                "❌ 错误：禁止使用通配符（* 或 ?）进行批量删除，请提供明确的具体路径。"
            )

        # 6. 执行删除
        if target_full.is_file() or target_full.is_symlink():
            target_full.unlink()  # 删除文件或软链接
            return f"✅ 成功：文件 '{target_path}' 已删除。"

        elif target_full.is_dir():
            # 递归删除文件夹及其内部所有内容
            shutil.rmtree(target_full)
            return f"✅ 成功：文件夹 '{target_path}' 及其所有子内容已递归删除。"

        else:
            return f"❌ 错误：未知的文件类型，无法删除 '{target_path}'。"

    except PermissionError:
        return (
            f"❌ 错误：权限不足，无法删除 '{target_path}'。可能有程序正在占用该文件。"
        )
    except Exception as e:
        return f"❌ 删除失败: {str(e)}"


# 代码检索
import re


@tool
def search_code(keyword: str, file_pattern: str = "*") -> str:
    """
    在整个工作区中搜索包含指定关键字的代码,返回结果格式为:[代码所在文件路径：代码所在行数：关键字代码]。

    :param keyword: 要搜索的关键字或正则表达式（如 'def login' 或 'class User'）
    :param file_pattern: 限定搜索的文件类型（如 '*.py' 或 '*.html'），默认为 '*' 表示搜索所有文件
    """
    try:
        # 1. 基础安全校验：禁止搜索特殊字符导致命令注入
        if not keyword or "'" in keyword or '"' in keyword or "`" in keyword:
            return "❌ 错误：关键字包含非法字符，或为空。请提供普通的字符串。"

        # 2. 排除垃圾目录，防止搜索到 node_modules 把内存撑爆
        exclude_dirs = [
            "--exclude-dir=.git",
            "--exclude-dir=node_modules",
            "--exclude-dir=__pycache__",
            "--exclude-dir=.venv",
            "--exclude-dir=venv",
        ]

        # 3. 拼接 grep 命令
        # -r: 递归搜索
        # -n: 显示行号
        # -I: 忽略二进制文件（防止搜出乱码）
        # -m 50: 每个文件最多匹配 50 次（防刷屏）
        cmd = ["grep", "-rnI", "-m", "50"] + exclude_dirs
        if file_pattern != "*":
            cmd.extend(["--include", file_pattern])

        cmd.extend([keyword, "."])

        # 4. 执行命令
        result = subprocess.run(
            cmd,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,  # 搜索操作必须快，超过 10 秒直接掐断
        )

        output = result.stdout

        # 5. 防刷屏截断（极其重要，防止大模型 Token 爆炸）
        if not output.strip():
            return f"🔍 未找到包含 '{keyword}' 的代码。"

        if len(output) > 5000:
            output = (
                output[:5000]
                + "\n\n[⚠️ 警告：搜索结果过多，已截断。请使用更精确的关键字。]"
            )

        return output

    except subprocess.TimeoutExpired:
        return "❌ 错误：搜索超时。请尝试缩小搜索范围或使用更具体的文件后缀。"
    except FileNotFoundError:
        return "❌ 错误：当前系统（可能是 Windows）未找到 grep 命令。请在 Docker 环境中运行此工具。"
    except Exception as e:
        return f"❌ 搜索失败: {str(e)}"


# 发送邮件工具，任务跑完可通过邮件通知
@tool
def send_mail(to: str, subject: str, body: str) -> str:
    """
    发送特定邮件到指定收件人
    Args:
        to: 收件人邮箱地址
        subject: 邮件主题
        body: 邮件正文内容
    Returns:
        邮件发送结果
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = config.MAIL_FROM
        msg["To"] = to
        msg["Subject"] = Header(subject, "utf-8")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT) as server:
            server.starttls()
            server.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
            server.sendmail(config.MAIL_FROM, to, msg.as_string())
        return f"邮件已成功发送给 {to}"
    except smtplib.SMTPAuthenticationError:
        return "SMTP认证失败，请检查邮箱和密码是否正确"
    except smtplib.SMTPException as e:
        return f"SMTP发送失败: {str(e)}"
    except Exception as e:
        return f"发送邮件时发生错误: {str(e)}"


# 实时联网搜索
@tool  #基于request的博查客户端收缩工具
async def bocha_websearch_tool(query: str, count: int = 5) -> str:
    """
    使用Bocha Web Search API 进行网页搜索。当你需要查找实时信息、最新新闻、或者你不确定的知识时，请调用此工具。

    参数:
    - query: 搜索关键词
    - count: 返回的搜索结果数量

    返回:
    - 搜索结果的详细信息，包括网页标题、网页URL、网页摘要、网站名称、网站Icon、网页发布时间等。
    """
    # 查询目的url
    url = 'https://api.bochaai.com/v1/web-search'
    # 构造请求头
    headers = {
        'Authorization': f'Bearer {bocha_key}',  # 请替换为你的API密钥,函数内直接使用全局变量为只读
        'Content-Type': 'application/json'
    }
    # 构造请求体
    data = {
        "query": query,
        "freshness": "noLimit", # 搜索的时间范围，例如 "oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"
        "summary": True, # 是否返回长文本摘要
        "count": count
    }
    # 异常查询，返回结果
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(url, headers=headers, json=data)
            
            if response.status_code != 200:
                return f"搜索API请求失败，状态码: {response.status_code}, 错误信息: {response.text}"

            json_response = response.json()
            
            if json_response.get("code") != 200 or not json_response.get("data"):
                return f"搜索API请求失败，原因是: {json_response.get('msg', '未知错误')}"
            
            webpages = json_response["data"].get("webPages", {}).get("value", [])
            if not webpages:
                return "未找到相关结果。请尝试更换搜索关键词。"
            # 格式化搜索结果
            formatted_results = ""
            for idx, page in enumerate(webpages, start=1):
                # 使用 .get() 防止某个字段缺失导致程序崩溃
                formatted_results += (
                    f"引用: {idx}\n"
                    f"标题: {page.get('name', '无标题')}\n"
                    f"URL: {page.get('url', '无链接')}\n"
                    f"摘要: {page.get('summary', '无摘要')}\n"
                    f"网站名称: {page.get('siteName', '未知')}\n"
                    f"发布时间: {page.get('dateLastCrawled', '未知')}\n\n"
                )
            return formatted_results.strip()
            
        except httpx.TimeoutException:
            return "❌ 搜索请求超时，请稍后再试。"
        except Exception as e:
            return f"❌ 搜索API发生异常: {str(e)}"