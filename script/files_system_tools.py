# agent文件操作工具脚本：列出特定目录结构，读取特定文件内容，修改文件内容，终端运行命令，新建文件/文件夹，移动/重命名文件，删除文件，代码搜索
import os

WORKSPACE_DIR = r"E:\vscode_python\3.FastAPI_Demo\FastAPI_Demo\9-CI-CD-nginx-docker\script"  # 挂载进去的本地代码目录

# ===================================================列出特定目录结构===================================================================


# 返回指定目录下的文件
def listdir(path: str = ""):
    full_path = os.path.join(WORKSPACE_DIR, path)
    try:
        files = os.listdir(full_path)
        if not files:
            print("该目录为空")
        print("\n".join(files))
    except Exception as e:
        print(str(e))


# listdir()


# 递归返回指定目录下的所有文件
def listdir(path: str):
    full_path = os.path.join(WORKSPACE_DIR, path)
    print(f"开始递归遍历: {full_path}\n")

    try:
        # os.walk 会返回三个值：当前目录路径、当前目录下的子文件夹列表、当前目录下的文件列表
        for root, dirs, files in os.walk(full_path):
            # 打印当前所在的目录层级（为了好看，可以计算一下缩进）
            level = root.replace(full_path, "").count(os.sep)
            indent = " " * 4 * level
            print(f"{indent}📁 {os.path.basename(root)}/")

            # 打印该目录下的所有文件
            for file in files:
                print(f"{indent}    📄 {file}")

    except Exception as e:
        print(f"发生错误: {e}")


# 递归返回指定目录下的所有文件，返回结果为列表
def get_flat_file_list(start_path):
    result = []
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


# print(get_flat_file_list(WORKSPACE_DIR))
# 返回结果类似：
# ['b.txt', 'list_directory.py', 'dir/a.txt', 'dir/oo/asda.txt']


# 递归返回指定目录下的所有文件，返回结果为json格式
def get_json_tree(start_path):
    tree = {}
    for root, dirs, files in os.walk(start_path):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]

        # 只取当前目录的相对路径作为键
        rel_path = os.path.relpath(root, start_path)
        if rel_path == ".":
            rel_path = ""

        # 纯文件列表
        tree[rel_path] = [f for f in files if not f.startswith(".")]
    return tree


# 返回结果类似：
# {
#   "": ["main.py", "config.json"],
#   "sub_folder": ["utils.py"],
#   "sub_folder/deep_folder": ["test.txt"]
# }
# ===================================================读取特定文件内容==================================================================
# 读取特定文件内容，简单实现
def read_file(file_path: str) -> str:
    """读取指定文件的内容"""
    full_path = os.path.join(WORKSPACE_DIR, file_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return str(e)


# print(read_file("list_directory.py"))


# 单次读取最大允许的字符数（约等于 2000-3000 个 Token）
MAX_READ_LENGTH = 10000


# 读取特定文件内容，生产实现
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


# ===================================================修改特定文件内容==================================================================
# 修改特定文件内容，简单版
def edit_file(file_path: str, old_string: str, new_string: str):
    """修改文件内的特定内容，要求具备唯一性，保证唯一精准匹配

    Args:
        file_path (str): 待修改文件的文件路径
        old_string (str): 文件内需要被修改的旧内容，要求具备唯一性，保证唯一精准匹配
        new_string (str): 新内容，用来覆盖被修改的新内容

    Returns:
        str: 修改文件结果
    """
    # 1. 路径安全校验（参照之前讲的 pathlib）
    full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, file_path))
    if not full_path.startswith(os.path.abspath(WORKSPACE_DIR)):
        return "❌ 错误：拒绝访问，不能读取工作区之外的文件。"

    if not os.path.exists(full_path):
        return f"❌ 错误：文件 '{file_path}' 不存在。请先使用 list_directory 工具确认正确的路径。"

    if os.path.isdir(full_path):
        return f"❌ 错误：'{file_path}' 是一个文件夹，不能使用 read_file 读取。请使用 list_directory 工具查看。"
    # 2. 读取原文件内容
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 3. 唯一性校验（极度重要！）
    count = content.count(old_string)
    if count == 0:
        return "❌ 失败：在文件中未找到 old_string，请先 read_file 确认原代码。"
    elif count > 1:
        return "❌ 失败：找到多处匹配，请提供更长的上下文来确保唯一性。"

    # 4. 执行替换并写回
    new_content = content.replace(old_string, new_string)
    with open(full_path, "w") as f:
        f.write(new_content)

    return "✅ 修改成功。"


import tempfile
import shutil


# 生产级临时文件
def edit_file(file_path, old_string, new_string):
    """修改文件内的特定内容，要求具备唯一性，保证唯一精准匹配

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
            content = f.read()

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


# ======================================================终端运行命令==================================================================
import subprocess
import shlex


# 简写实现
def execute_terminal(command: str) -> str:
    """在项目根目录下执行终端命令，如 git diff, ls, pytest 等"""
    import subprocess

    try:
        # ⚠️ 必须使用 subprocess.run 并设置 timeout
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout + result.stderr
    except Exception as e:
        return str(e)


# 🚫 黑名单：绝对禁止执行的命令前缀/关键字
# 注意：黑名单永远是不完美的，但能防住 90% 的低级误操作
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


# 生产实现
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

        output = result.stdout + result.stderr

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


print(execute_terminal("echo %VIRTUAL_ENV%"))

# ======================================================新建文件/文件夹==================================================================

from pathlib import Path


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


# print(create_file("adc.py", "hello world!"))


# ======================================================移动/重命名文件==================================================================

import shutil
from pathlib import Path


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
        return f"❌ 移动失败: {str(e)}"


# print(move_file("adc.txt", "dc/adc.txt"))
# ======================================================删除文件/文件夹（递归删除）==================================================================

import shutil
from pathlib import Path


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


# print(delete_item("dir/"))
# =========================================================代码检索====================================================================

import subprocess
from pathlib import Path


# linux系统下运行
def search_code(keyword: str, file_pattern: str = "*") -> str:
    """
    在整个工作区中搜索包含指定关键字的代码。

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


import re
import os
from pathlib import Path


# windows版本
def search_code(keyword: str, file_pattern: str = "*") -> str:
    """
    在整个工作区中搜索包含指定关键字的代码。

    :param keyword: 要搜索的字符串或正则表达式（如 'def login' 或 'class User'）
    :param file_pattern: 限定搜索的文件类型（如 '*.py' 或 '*.html'），默认为 '*' 表示搜索所有文件
    """
    try:
        if not keyword:
            return "❌ 错误：搜索关键字不能为空。"

        # 1. 编译正则表达式（忽略大小写，让搜索更宽容）
        try:
            pattern = re.compile(keyword, re.IGNORECASE)
        except re.error as e:
            return f"❌ 错误：关键字不是合法的正则表达式。{str(e)}"

        base_dir = Path(WORKSPACE_DIR).resolve()

        # 2. 定义要跳过的垃圾目录
        ignore_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            "dist",
            "build",
        }

        results = []
        match_count = 0
        max_results = 100  # 最多返回 100 条结果，防止 Token 爆炸

        # 3. 遍历工作区
        for root, dirs, files in os.walk(base_dir):
            # 过滤掉垃圾目录
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for file in files:
                # 根据 file_pattern 过滤文件后缀（比如只看 .py 文件）
                if file_pattern != "*" and not file.endswith(
                    file_pattern.replace("*", "")
                ):
                    continue

                file_path = Path(root) / file

                # 跳过二进制文件和超大文件（比如超过 2MB 的文件不搜）
                try:
                    if file_path.stat().st_size > 2 * 1024 * 1024:
                        continue
                except OSError:
                    continue

                # 4. 逐行读取并匹配
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern.search(line):
                                # 获取相对路径
                                rel_path = file_path.relative_to(base_dir).as_posix()
                                # 组装结果：文件路径:行号: 代码内容
                                clean_line = line.strip()
                                results.append(f"{rel_path}:{line_num}: {clean_line}")
                                match_count += 1

                                # 达到最大返回数量，提前终止
                                if match_count >= max_results:
                                    results.append(
                                        f"\n\n[⚠️ 警告：匹配结果超过 {max_results} 条，已截断。请使用更精确的关键字。]"
                                    )
                                    return "\n".join(results)
                except Exception:
                    # 如果某个文件读不了（比如权限不够），跳过它，不影响整体搜索
                    continue

        if not results:
            return f"🔍 未找到包含 '{keyword}' 的代码。"

        return "\n".join(results)

    except Exception as e:
        return f"❌ 搜索失败: {str(e)}"


# print(search_code("pydantic", "*.txt"))
