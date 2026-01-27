# AIChat Agents Setup Guide

This guide documents how to create and configure AIChat agents with function calling capabilities.

## Directory Structure

AIChat expects the following structure in its `functions_dir` (default: `~/.config/aichat/functions/`):

```
~/.config/aichat/functions/
├── agents.txt              # List of agent names (one per line)
├── tools.txt               # List of tool filenames (one per line)
├── tools/                  # Tool implementation scripts
│   ├── tool_name.sh        # Bash tool (uses argc)
│   ├── tool_name.py        # Python tool
│   └── tool_name.js        # JavaScript tool
├── bin/                    # Executable wrappers (called by AIChat)
│   └── tool_name           # Wrapper that parses JSON and calls tool
└── agents/
    └── <agent_name>/
        ├── index.yaml      # Agent definition
        ├── functions.json  # Tool declarations (OpenAI format)
        └── tools.txt       # Tools available to this agent
```

## Step-by-Step Setup

### 1. Create Directory Structure

```bash
FUNCTIONS_DIR=~/.config/aichat/functions
mkdir -p $FUNCTIONS_DIR/{tools,bin,agents}
```

### 2. Create a Tool Script

Tools can be written in Bash, Python, or JavaScript. They receive arguments and return output.

**Example: `tools/file_list.sh`**

```bash
#!/usr/bin/env bash
set -e

# @describe List files and directories
# @option --path The directory path to list (default: current directory)
# @flag --all Show hidden files
# @flag --long Show detailed information

main() {
    local target="${argc_path:-.}"
    local opts=""

    [[ -n "$argc_all" ]] && opts="$opts -a"
    [[ -n "$argc_long" ]] && opts="$opts -lh"

    ls $opts "$target"
}

eval "$(argc --argc-eval "$0" "$@")"
```

Make it executable:
```bash
chmod +x $FUNCTIONS_DIR/tools/file_list.sh
```

### 3. Create Bin Wrapper

AIChat calls executables in `bin/` with a JSON string as the first argument. The wrapper parses JSON and calls the tool.

**Example: `bin/file_list`**

```bash
#!/usr/bin/env bash
set -e

# AIChat passes arguments as a single JSON string argument
input="$1"

# Parse JSON arguments using jq
path=$(echo "$input" | jq -r '.path // empty')
all=$(echo "$input" | jq -r '.all // empty')
long=$(echo "$input" | jq -r '.long // empty')

# Build command arguments
args=()
[[ -n "$path" && "$path" != "null" ]] && args+=(--path "$path")
[[ "$all" == "true" ]] && args+=(--all)
[[ "$long" == "true" ]] && args+=(--long)

# Execute the tool
"$(dirname "$0")/../tools/file_list.sh" "${args[@]}"
```

Make it executable:
```bash
chmod +x $FUNCTIONS_DIR/bin/file_list
```

### 4. Register Tool in tools.txt

Add the tool filename to `tools.txt`:

```bash
echo "file_list.sh" >> $FUNCTIONS_DIR/tools.txt
```

### 5. Create Agent Directory

```bash
mkdir -p $FUNCTIONS_DIR/agents/my_agent
```

### 6. Create Agent Definition (index.yaml)

**Example: `agents/my_agent/index.yaml`**

```yaml
name: my_agent
description: A helpful agent that can manage files
version: 0.1.0
instructions: |
  You are a file management agent.

  ## Your Capabilities
  - List files and directories
  - Read file contents
  - Write files

  ## Rules
  1. Always confirm before writing files
  2. Be concise in your responses

conversation_starters:
  - List files in my home directory
  - Show me what's in /tmp
```

### 7. Create Function Declarations (functions.json)

This file defines the tools in OpenAI function-calling format:

**Example: `agents/my_agent/functions.json`**

```json
[
  {
    "name": "file_list",
    "description": "List files and directories",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "The directory path to list (default: current directory)"
        },
        "all": {
          "type": "boolean",
          "description": "Show hidden files"
        },
        "long": {
          "type": "boolean",
          "description": "Show detailed information"
        }
      }
    }
  }
]
```

### 8. Create Agent's tools.txt

List which tools this agent can use:

**Example: `agents/my_agent/tools.txt`**

```
file_list.sh
file_read.sh
file_write.sh
```

### 9. Register Agent in agents.txt

```bash
echo "my_agent" >> $FUNCTIONS_DIR/agents.txt
```

### 10. Verify Setup

```bash
# List available agents
aichat --list-agents

# Test the agent
aichat --agent my_agent "list files in /tmp"
```

## Complete Example: System Agent

Here's a complete setup script for the system_agent:

```bash
#!/usr/bin/env bash
set -e

FUNCTIONS_DIR="${1:-$HOME/.config/aichat/functions}"

echo "Setting up system_agent in $FUNCTIONS_DIR"

# Create directories
mkdir -p "$FUNCTIONS_DIR"/{tools,bin,agents/system_agent}

# Create tools.txt
cat > "$FUNCTIONS_DIR/tools.txt" << 'EOF'
shell_execute.sh
file_read.sh
file_write.sh
file_list.sh
process_list.sh
disk_usage.sh
EOF

# Create agents.txt
cat > "$FUNCTIONS_DIR/agents.txt" << 'EOF'
system_agent
EOF

# Create shell_execute tool
cat > "$FUNCTIONS_DIR/tools/shell_execute.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe Execute a shell command safely
# @option --command! The shell command to execute

BLOCKLIST=("rm -rf /" "rm -rf /*" "dd if=/dev/" "mkfs" "> /dev/sd" "chmod 777 /")

main() {
    for blocked in "${BLOCKLIST[@]}"; do
        if [[ "$argc_command" == *"$blocked"* ]]; then
            echo "ERROR: Command blocked for safety"
            exit 1
        fi
    done
    timeout 60 bash -c "$argc_command" 2>&1
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create file_list tool
cat > "$FUNCTIONS_DIR/tools/file_list.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe List files and directories
# @option --path The directory path to list
# @flag --all Show hidden files
# @flag --long Show detailed information

main() {
    local target="${argc_path:-.}"
    local opts=""
    [[ -n "$argc_all" ]] && opts="$opts -a"
    [[ -n "$argc_long" ]] && opts="$opts -lh"
    ls $opts "$target"
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create file_read tool
cat > "$FUNCTIONS_DIR/tools/file_read.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe Read the contents of a file
# @option --path! The path to the file to read
# @option --lines The number of lines to read

main() {
    if [[ ! -f "$argc_path" ]]; then
        echo "ERROR: File not found: $argc_path"
        exit 1
    fi
    if [[ -n "$argc_lines" ]]; then
        head -n "$argc_lines" "$argc_path"
    else
        cat "$argc_path"
    fi
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create file_write tool
cat > "$FUNCTIONS_DIR/tools/file_write.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe Write content to a file
# @option --path! The path to the file
# @option --content! The content to write
# @flag --append Append instead of overwrite

main() {
    mkdir -p "$(dirname "$argc_path")"
    if [[ -n "$argc_append" ]]; then
        echo "$argc_content" >> "$argc_path"
    else
        echo "$argc_content" > "$argc_path"
    fi
    echo "Wrote to: $argc_path"
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create process_list tool
cat > "$FUNCTIONS_DIR/tools/process_list.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe List running processes
# @option --filter Filter processes by name
# @flag --all Show all processes

main() {
    if [[ -n "$argc_all" ]]; then
        if [[ -n "$argc_filter" ]]; then
            ps aux | head -1 && ps aux | grep -i "$argc_filter" | grep -v grep
        else
            ps aux | head -20
        fi
    else
        if [[ -n "$argc_filter" ]]; then
            ps ux | head -1 && ps ux | grep -i "$argc_filter" | grep -v grep
        else
            ps ux
        fi
    fi
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create disk_usage tool
cat > "$FUNCTIONS_DIR/tools/disk_usage.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe Show disk usage information
# @option --path Show usage for specific path
# @flag --summary Show only total

main() {
    if [[ -n "$argc_path" ]]; then
        if [[ -n "$argc_summary" ]]; then
            du -sh "$argc_path"
        else
            du -h "$argc_path" | tail -20
        fi
    else
        df -h
    fi
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Make tools executable
chmod +x "$FUNCTIONS_DIR/tools/"*.sh

# Create bin wrappers
for tool in shell_execute file_list file_read file_write process_list disk_usage; do
    cat > "$FUNCTIONS_DIR/bin/$tool" << WRAPPER
#!/usr/bin/env bash
set -e
input="\$1"
WRAPPER

    case "$tool" in
        shell_execute)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
command=$(echo "$input" | jq -r '.command // empty')
[[ -z "$command" ]] && { echo "ERROR: command required"; exit 1; }
"$(dirname "$0")/../tools/shell_execute.sh" --command "$command"
WRAPPER
            ;;
        file_list)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
path=$(echo "$input" | jq -r '.path // empty')
all=$(echo "$input" | jq -r '.all // empty')
long=$(echo "$input" | jq -r '.long // empty')
args=()
[[ -n "$path" && "$path" != "null" ]] && args+=(--path "$path")
[[ "$all" == "true" ]] && args+=(--all)
[[ "$long" == "true" ]] && args+=(--long)
"$(dirname "$0")/../tools/file_list.sh" "${args[@]}"
WRAPPER
            ;;
        file_read)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
path=$(echo "$input" | jq -r '.path // empty')
lines=$(echo "$input" | jq -r '.lines // empty')
[[ -z "$path" ]] && { echo "ERROR: path required"; exit 1; }
args=(--path "$path")
[[ -n "$lines" && "$lines" != "null" ]] && args+=(--lines "$lines")
"$(dirname "$0")/../tools/file_read.sh" "${args[@]}"
WRAPPER
            ;;
        file_write)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
path=$(echo "$input" | jq -r '.path // empty')
content=$(echo "$input" | jq -r '.content // empty')
append=$(echo "$input" | jq -r '.append // empty')
[[ -z "$path" ]] && { echo "ERROR: path required"; exit 1; }
[[ -z "$content" ]] && { echo "ERROR: content required"; exit 1; }
args=(--path "$path" --content "$content")
[[ "$append" == "true" ]] && args+=(--append)
"$(dirname "$0")/../tools/file_write.sh" "${args[@]}"
WRAPPER
            ;;
        process_list)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
filter=$(echo "$input" | jq -r '.filter // empty')
all=$(echo "$input" | jq -r '.all // empty')
args=()
[[ -n "$filter" && "$filter" != "null" ]] && args+=(--filter "$filter")
[[ "$all" == "true" ]] && args+=(--all)
"$(dirname "$0")/../tools/process_list.sh" "${args[@]}"
WRAPPER
            ;;
        disk_usage)
            cat >> "$FUNCTIONS_DIR/bin/$tool" << 'WRAPPER'
path=$(echo "$input" | jq -r '.path // empty')
summary=$(echo "$input" | jq -r '.summary // empty')
args=()
[[ -n "$path" && "$path" != "null" ]] && args+=(--path "$path")
[[ "$summary" == "true" ]] && args+=(--summary)
"$(dirname "$0")/../tools/disk_usage.sh" "${args[@]}"
WRAPPER
            ;;
    esac
    chmod +x "$FUNCTIONS_DIR/bin/$tool"
done

# Create agent index.yaml
cat > "$FUNCTIONS_DIR/agents/system_agent/index.yaml" << 'EOF'
name: system_agent
description: System administration agent for executing commands and managing files
version: 0.1.0
instructions: |
  You are a system administration agent for a Linux home server.

  ## Capabilities
  - Execute shell commands (with safety restrictions)
  - Read, write, and list files
  - Check running processes
  - Show disk usage

  ## Safety Rules
  1. NEVER execute destructive commands (rm -rf /, dd, mkfs)
  2. Verify paths before writing
  3. Always show command output

conversation_starters:
  - List files in my home directory
  - Check disk usage
  - Show running processes
EOF

# Create agent tools.txt
cat > "$FUNCTIONS_DIR/agents/system_agent/tools.txt" << 'EOF'
shell_execute.sh
file_read.sh
file_write.sh
file_list.sh
process_list.sh
disk_usage.sh
EOF

# Create agent functions.json
cat > "$FUNCTIONS_DIR/agents/system_agent/functions.json" << 'EOF'
[
  {
    "name": "shell_execute",
    "description": "Execute a shell command safely",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "description": "The shell command to execute"
        }
      },
      "required": ["command"]
    }
  },
  {
    "name": "file_list",
    "description": "List files and directories",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Directory path to list"
        },
        "all": {
          "type": "boolean",
          "description": "Show hidden files"
        },
        "long": {
          "type": "boolean",
          "description": "Show detailed information"
        }
      }
    }
  },
  {
    "name": "file_read",
    "description": "Read the contents of a file",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to the file"
        },
        "lines": {
          "type": "integer",
          "description": "Number of lines to read"
        }
      },
      "required": ["path"]
    }
  },
  {
    "name": "file_write",
    "description": "Write content to a file",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to the file"
        },
        "content": {
          "type": "string",
          "description": "Content to write"
        },
        "append": {
          "type": "boolean",
          "description": "Append instead of overwrite"
        }
      },
      "required": ["path", "content"]
    }
  },
  {
    "name": "process_list",
    "description": "List running processes",
    "parameters": {
      "type": "object",
      "properties": {
        "filter": {
          "type": "string",
          "description": "Filter by process name"
        },
        "all": {
          "type": "boolean",
          "description": "Show all processes"
        }
      }
    }
  },
  {
    "name": "disk_usage",
    "description": "Show disk usage information",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to check"
        },
        "summary": {
          "type": "boolean",
          "description": "Show only total"
        }
      }
    }
  }
]
EOF

echo "Setup complete!"
echo ""
echo "Verify with:"
echo "  aichat --list-agents"
echo "  aichat --agent system_agent 'list files in /tmp'"
```

Save as `scripts/setup_system_agent.sh` and run:
```bash
chmod +x scripts/setup_system_agent.sh
./scripts/setup_system_agent.sh
```

## Prerequisites

- **argc**: Required for bash tools. Install via cargo:
  ```bash
  cargo install argc
  ```

- **jq**: Required for JSON parsing in bin wrappers:
  ```bash
  # Debian/Ubuntu
  sudo apt install jq

  # macOS
  brew install jq
  ```

## Troubleshooting

### Agent not listed
```bash
# Check agents.txt exists and contains agent name
cat ~/.config/aichat/functions/agents.txt

# Check agent directory structure
ls -la ~/.config/aichat/functions/agents/my_agent/
```

### "Unknown agent" error
- Ensure `functions.json` exists in agent directory
- Ensure agent name in `index.yaml` matches directory name

### Tool not found (os error 2)
- Check bin wrapper exists and is executable
- Check wrapper path to tool is correct
- Test wrapper manually: `echo '{"path":"/tmp"}' | ~/.config/aichat/functions/bin/file_list`

### Tool receives empty input
- AIChat passes JSON as first argument (`$1`), not stdin
- Update wrapper to use `input="$1"` instead of `input=$(cat)`

## Adding Tools Programmatically

See `app/services/agent_setup.py` for Python functions to create agents and tools programmatically.
