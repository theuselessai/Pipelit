"""
Programmatic setup for AIChat agents and tools.

This module provides functions to create and manage AIChat agents
and their associated tools without manual file editing.
"""

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ToolParameter:
    """A parameter for a tool function."""

    name: str
    type: str  # "string", "integer", "boolean", "number"
    description: str
    required: bool = False


@dataclass
class Tool:
    """Definition of an AIChat tool."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    script_content: Optional[str] = None  # Bash script content
    wrapper_content: Optional[str] = None  # Bin wrapper content

    def to_function_schema(self) -> dict:
        """Convert to OpenAI function calling schema."""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)

        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        }

        if required:
            schema["parameters"]["required"] = required

        return schema


@dataclass
class Agent:
    """Definition of an AIChat agent."""

    name: str
    description: str
    instructions: str
    tools: list[Tool] = field(default_factory=list)
    version: str = "0.1.0"
    conversation_starters: list[str] = field(default_factory=list)


class AgentSetup:
    """Manages AIChat agent and tool setup."""

    def __init__(self, functions_dir: Optional[str] = None):
        """
        Initialize with AIChat functions directory.

        Args:
            functions_dir: Path to functions directory.
                          Defaults to ~/.config/aichat/functions
        """
        if functions_dir:
            self.functions_dir = Path(functions_dir).expanduser()
        else:
            self.functions_dir = Path.home() / ".config" / "aichat" / "functions"

        self.tools_dir = self.functions_dir / "tools"
        self.bin_dir = self.functions_dir / "bin"
        self.agents_dir = self.functions_dir / "agents"

    def setup_directories(self) -> None:
        """Create required directory structure."""
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def create_tool(self, tool: Tool) -> None:
        """
        Create a tool with its script and bin wrapper.

        Args:
            tool: Tool definition
        """
        self.setup_directories()

        # Create tool script
        if tool.script_content:
            script_path = self.tools_dir / f"{tool.name}.sh"
            script_path.write_text(tool.script_content)
            script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        # Create bin wrapper
        if tool.wrapper_content:
            wrapper_path = self.bin_dir / tool.name
            wrapper_path.write_text(tool.wrapper_content)
            wrapper_path.chmod(wrapper_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

        # Update tools.txt
        self._update_list_file(self.functions_dir / "tools.txt", f"{tool.name}.sh")

    def create_agent(self, agent: Agent) -> None:
        """
        Create an agent with its configuration files.

        Args:
            agent: Agent definition
        """
        self.setup_directories()

        agent_dir = self.agents_dir / agent.name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create index.yaml
        index_content = self._generate_index_yaml(agent)
        (agent_dir / "index.yaml").write_text(index_content)

        # Create functions.json
        functions = [tool.to_function_schema() for tool in agent.tools]
        (agent_dir / "functions.json").write_text(
            json.dumps(functions, indent=2)
        )

        # Create tools.txt for agent
        tools_list = "\n".join(f"{t.name}.sh" for t in agent.tools)
        (agent_dir / "tools.txt").write_text(tools_list + "\n")

        # Update agents.txt
        self._update_list_file(self.functions_dir / "agents.txt", agent.name)

        # Create tools
        for tool in agent.tools:
            self.create_tool(tool)

    def _generate_index_yaml(self, agent: Agent) -> str:
        """Generate index.yaml content for an agent."""
        lines = [
            f"name: {agent.name}",
            f"description: {agent.description}",
            f"version: {agent.version}",
            "instructions: |",
        ]

        # Indent instructions
        for line in agent.instructions.strip().split("\n"):
            lines.append(f"  {line}")

        if agent.conversation_starters:
            lines.append("")
            lines.append("conversation_starters:")
            for starter in agent.conversation_starters:
                lines.append(f"  - {starter}")

        return "\n".join(lines) + "\n"

    def _update_list_file(self, path: Path, item: str) -> None:
        """Add item to a list file if not already present."""
        existing = set()
        if path.exists():
            existing = set(path.read_text().strip().split("\n"))

        if item not in existing:
            existing.add(item)
            path.write_text("\n".join(sorted(existing)) + "\n")

    def list_agents(self) -> list[str]:
        """List all configured agents."""
        agents_file = self.functions_dir / "agents.txt"
        if not agents_file.exists():
            return []
        return [a for a in agents_file.read_text().strip().split("\n") if a]

    def list_tools(self) -> list[str]:
        """List all configured tools."""
        tools_file = self.functions_dir / "tools.txt"
        if not tools_file.exists():
            return []
        return [t for t in tools_file.read_text().strip().split("\n") if t]

    def remove_agent(self, name: str) -> bool:
        """Remove an agent and its configuration."""
        import shutil

        agent_dir = self.agents_dir / name
        if not agent_dir.exists():
            return False

        shutil.rmtree(agent_dir)

        # Update agents.txt
        agents_file = self.functions_dir / "agents.txt"
        if agents_file.exists():
            agents = [a for a in agents_file.read_text().strip().split("\n") if a != name]
            agents_file.write_text("\n".join(agents) + "\n")

        return True


def generate_bash_tool(
    name: str,
    description: str,
    parameters: list[ToolParameter],
    main_logic: str,
) -> Tool:
    """
    Generate a bash tool with argc parsing.

    Args:
        name: Tool name
        description: Tool description
        parameters: List of parameters
        main_logic: Bash code for the main function body

    Returns:
        Tool object with script and wrapper content
    """
    # Generate tool script
    script_lines = [
        "#!/usr/bin/env bash",
        "set -e",
        "",
        f"# @describe {description}",
    ]

    for param in parameters:
        if param.type == "boolean":
            script_lines.append(f"# @flag --{param.name} {param.description}")
        else:
            required = "!" if param.required else ""
            script_lines.append(f"# @option --{param.name}{required} {param.description}")

    script_lines.extend([
        "",
        "main() {",
        main_logic,
        "}",
        "",
        'eval "$(argc --argc-eval "$0" "$@")"',
    ])

    # Generate bin wrapper
    wrapper_lines = [
        "#!/usr/bin/env bash",
        "set -e",
        'input="$1"',
    ]

    # Parse each parameter
    for param in parameters:
        jq_default = "empty" if param.type != "boolean" else "false"
        wrapper_lines.append(
            f'{param.name}=$(echo "$input" | jq -r \'.{param.name} // {jq_default}\')'
        )

    # Add required checks
    for param in parameters:
        if param.required:
            wrapper_lines.append(
                f'[[ -z "${param.name}" ]] && {{ echo "ERROR: {param.name} is required"; exit 1; }}'
            )

    # Build args array
    wrapper_lines.append("args=()")
    for param in parameters:
        if param.type == "boolean":
            wrapper_lines.append(
                f'[[ "${param.name}" == "true" ]] && args+=(--{param.name})'
            )
        else:
            wrapper_lines.append(
                f'[[ -n "${param.name}" && "${param.name}" != "null" ]] && args+=(--{param.name} "${param.name}")'
            )

    wrapper_lines.append(
        f'"$(dirname "$0")/../tools/{name}.sh" "${{args[@]}}"'
    )

    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        script_content="\n".join(script_lines),
        wrapper_content="\n".join(wrapper_lines),
    )


# Predefined tools
def create_file_list_tool() -> Tool:
    """Create the file_list tool."""
    return generate_bash_tool(
        name="file_list",
        description="List files and directories",
        parameters=[
            ToolParameter("path", "string", "Directory path to list"),
            ToolParameter("all", "boolean", "Show hidden files"),
            ToolParameter("long", "boolean", "Show detailed information"),
        ],
        main_logic='''    local target="${argc_path:-.}"
    local opts=""
    [[ -n "$argc_all" ]] && opts="$opts -a"
    [[ -n "$argc_long" ]] && opts="$opts -lh"
    ls $opts "$target"''',
    )


def create_shell_execute_tool() -> Tool:
    """Create the shell_execute tool."""
    return generate_bash_tool(
        name="shell_execute",
        description="Execute a shell command safely",
        parameters=[
            ToolParameter("command", "string", "The shell command to execute", required=True),
        ],
        main_logic='''    BLOCKLIST=("rm -rf /" "rm -rf /*" "dd if=/dev/" "mkfs" "> /dev/sd" "chmod 777 /")
    for blocked in "${BLOCKLIST[@]}"; do
        if [[ "$argc_command" == *"$blocked"* ]]; then
            echo "ERROR: Command blocked for safety"
            exit 1
        fi
    done
    timeout 60 bash -c "$argc_command" 2>&1''',
    )


def create_file_read_tool() -> Tool:
    """Create the file_read tool."""
    return generate_bash_tool(
        name="file_read",
        description="Read the contents of a file",
        parameters=[
            ToolParameter("path", "string", "Path to the file", required=True),
            ToolParameter("lines", "integer", "Number of lines to read"),
        ],
        main_logic='''    if [[ ! -f "$argc_path" ]]; then
        echo "ERROR: File not found: $argc_path"
        exit 1
    fi
    if [[ -n "$argc_lines" ]]; then
        head -n "$argc_lines" "$argc_path"
    else
        cat "$argc_path"
    fi''',
    )


def create_disk_usage_tool() -> Tool:
    """Create the disk_usage tool."""
    return generate_bash_tool(
        name="disk_usage",
        description="Show disk usage information",
        parameters=[
            ToolParameter("path", "string", "Path to check"),
            ToolParameter("summary", "boolean", "Show only total"),
        ],
        main_logic='''    if [[ -n "$argc_path" ]]; then
        if [[ -n "$argc_summary" ]]; then
            du -sh "$argc_path"
        else
            du -h "$argc_path" | tail -20
        fi
    else
        df -h
    fi''',
    )


def setup_system_agent(functions_dir: Optional[str] = None) -> None:
    """
    Set up the system_agent with all its tools.

    Args:
        functions_dir: Optional custom functions directory
    """
    setup = AgentSetup(functions_dir)

    agent = Agent(
        name="system_agent",
        description="System administration agent for executing commands and managing files",
        instructions="""You are a system administration agent for a Linux home server.

## Your Capabilities
- Execute shell commands (with safety restrictions)
- Read, write, and list files
- Check running processes
- Show disk usage

## Safety Rules
1. NEVER execute destructive commands (rm -rf /, dd, mkfs, fork bombs)
2. Be careful with file operations - verify paths before writing
3. Always show command output to the user

## Response Format
- Be concise and direct
- Show relevant output from commands
- If a command fails, explain why and suggest alternatives""",
        tools=[
            create_shell_execute_tool(),
            create_file_list_tool(),
            create_file_read_tool(),
            create_disk_usage_tool(),
        ],
        conversation_starters=[
            "List files in my home directory",
            "Check disk usage",
            "Show running processes",
        ],
    )

    setup.create_agent(agent)
    print(f"System agent created in {setup.functions_dir}")


if __name__ == "__main__":
    setup_system_agent()
