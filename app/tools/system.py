"""System tools for the system agent."""
import os
import shutil
import subprocess

from langchain_core.tools import tool


@tool
def shell_execute(command: str) -> str:
    """Execute a shell command and return its output. Use for running system commands like ls, grep, df, etc."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\nSTDERR: {result.stderr.strip()}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds"
    except Exception as e:
        return f"Error: {e}"


@tool
def file_read(path: str) -> str:
    """Read the contents of a file at the given path."""
    try:
        path = os.path.expanduser(path)
        with open(path, "r") as f:
            content = f.read()
        if len(content) > 10000:
            return content[:10000] + f"\n... (truncated, total {len(content)} chars)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def file_write(path: str, content: str) -> str:
    """Write content to a file at the given path. Creates parent directories if needed."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def file_list(directory: str = ".") -> str:
    """List files and directories in the given path."""
    try:
        directory = os.path.expanduser(directory)
        entries = os.listdir(directory)
        lines = []
        for entry in sorted(entries):
            full = os.path.join(directory, entry)
            if os.path.isdir(full):
                lines.append(f"  {entry}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"  {entry} ({size} bytes)")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


@tool
def disk_usage(path: str = "/") -> str:
    """Show disk usage for the given path."""
    try:
        usage = shutil.disk_usage(os.path.expanduser(path))
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        pct = usage.used / usage.total * 100
        return (
            f"Disk usage for {path}:\n"
            f"  Total: {total_gb:.1f} GB\n"
            f"  Used:  {used_gb:.1f} GB ({pct:.1f}%)\n"
            f"  Free:  {free_gb:.1f} GB"
        )
    except Exception as e:
        return f"Error: {e}"


@tool
def process_list() -> str:
    """List running processes sorted by CPU usage."""
    try:
        result = subprocess.run(
            ["ps", "aux", "--sort=-%cpu"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")
        # Header + top 20 processes
        return "\n".join(lines[:21])
    except Exception as e:
        return f"Error: {e}"


def get_system_tools() -> list:
    """Return all system tools."""
    return [shell_execute, file_read, file_write, file_list, disk_usage, process_list]
