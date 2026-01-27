#!/usr/bin/env bash
# Setup script for system_agent with AIChat function calling
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

BLOCKLIST=("rm -rf /" "rm -rf /*" "dd if=/dev/" "mkfs" "> /dev/sd" "chmod 777 /" ":(){ :|:& };:")

main() {
    for blocked in "${BLOCKLIST[@]}"; do
        if [[ "$argc_command" == *"$blocked"* ]]; then
            echo "ERROR: Command blocked for safety: contains '$blocked'"
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
EOF

# Create file_read tool
cat > "$FUNCTIONS_DIR/tools/file_read.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe Read the contents of a file
# @option --path! The path to the file to read
# @option --lines The number of lines to read (default: all)

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
# @option --path! The path to the file to write
# @option --content! The content to write to the file
# @flag --append Append to file instead of overwriting

main() {
    mkdir -p "$(dirname "$argc_path")"
    if [[ -n "$argc_append" ]]; then
        echo "$argc_content" >> "$argc_path"
        echo "Appended to: $argc_path"
    else
        echo "$argc_content" > "$argc_path"
        echo "Wrote to: $argc_path"
    fi
}

eval "$(argc --argc-eval "$0" "$@")"
EOF

# Create process_list tool
cat > "$FUNCTIONS_DIR/tools/process_list.sh" << 'EOF'
#!/usr/bin/env bash
set -e

# @describe List running processes
# @option --filter Filter processes by name
# @flag --all Show all processes (not just user's)

main() {
    if [[ -n "$argc_all" ]]; then
        if [[ -n "$argc_filter" ]]; then
            ps aux | head -1
            ps aux | grep -i "$argc_filter" | grep -v grep
        else
            ps aux | head -20
        fi
    else
        if [[ -n "$argc_filter" ]]; then
            ps ux | head -1
            ps ux | grep -i "$argc_filter" | grep -v grep
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
# @flag --summary Show only total for directories

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

echo "Created tools..."

# Create bin wrappers
cat > "$FUNCTIONS_DIR/bin/shell_execute" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
command=$(echo "$input" | jq -r '.command // empty')
[[ -z "$command" ]] && { echo "ERROR: command is required"; exit 1; }
"$(dirname "$0")/../tools/shell_execute.sh" --command "$command"
EOF

cat > "$FUNCTIONS_DIR/bin/file_list" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
path=$(echo "$input" | jq -r '.path // empty')
all=$(echo "$input" | jq -r '.all // empty')
long=$(echo "$input" | jq -r '.long // empty')
args=()
[[ -n "$path" && "$path" != "null" ]] && args+=(--path "$path")
[[ "$all" == "true" ]] && args+=(--all)
[[ "$long" == "true" ]] && args+=(--long)
"$(dirname "$0")/../tools/file_list.sh" "${args[@]}"
EOF

cat > "$FUNCTIONS_DIR/bin/file_read" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
path=$(echo "$input" | jq -r '.path // empty')
lines=$(echo "$input" | jq -r '.lines // empty')
[[ -z "$path" ]] && { echo "ERROR: path is required"; exit 1; }
args=(--path "$path")
[[ -n "$lines" && "$lines" != "null" ]] && args+=(--lines "$lines")
"$(dirname "$0")/../tools/file_read.sh" "${args[@]}"
EOF

cat > "$FUNCTIONS_DIR/bin/file_write" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
path=$(echo "$input" | jq -r '.path // empty')
content=$(echo "$input" | jq -r '.content // empty')
append=$(echo "$input" | jq -r '.append // empty')
[[ -z "$path" ]] && { echo "ERROR: path is required"; exit 1; }
[[ -z "$content" ]] && { echo "ERROR: content is required"; exit 1; }
args=(--path "$path" --content "$content")
[[ "$append" == "true" ]] && args+=(--append)
"$(dirname "$0")/../tools/file_write.sh" "${args[@]}"
EOF

cat > "$FUNCTIONS_DIR/bin/process_list" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
filter=$(echo "$input" | jq -r '.filter // empty')
all=$(echo "$input" | jq -r '.all // empty')
args=()
[[ -n "$filter" && "$filter" != "null" ]] && args+=(--filter "$filter")
[[ "$all" == "true" ]] && args+=(--all)
"$(dirname "$0")/../tools/process_list.sh" "${args[@]}"
EOF

cat > "$FUNCTIONS_DIR/bin/disk_usage" << 'EOF'
#!/usr/bin/env bash
set -e
input="$1"
path=$(echo "$input" | jq -r '.path // empty')
summary=$(echo "$input" | jq -r '.summary // empty')
args=()
[[ -n "$path" && "$path" != "null" ]] && args+=(--path "$path")
[[ "$summary" == "true" ]] && args+=(--summary)
"$(dirname "$0")/../tools/disk_usage.sh" "${args[@]}"
EOF

chmod +x "$FUNCTIONS_DIR/bin/"*

echo "Created bin wrappers..."

# Create agent index.yaml
cat > "$FUNCTIONS_DIR/agents/system_agent/index.yaml" << 'EOF'
name: system_agent
description: System administration agent for executing commands and managing files
version: 0.1.0
instructions: |
  You are a system administration agent for a Linux home server.

  ## Your Capabilities
  - Execute shell commands (with safety restrictions)
  - Read, write, and list files
  - Check running processes
  - Show disk usage

  ## Safety Rules
  1. NEVER execute destructive commands (rm -rf /, dd, mkfs, fork bombs)
  2. Be careful with file operations - verify paths before writing
  3. Always show command output to the user
  4. For potentially dangerous operations, explain what you're about to do first

  ## Response Format
  - Be concise and direct
  - Show relevant output from commands
  - If a command fails, explain why and suggest alternatives

conversation_starters:
  - List files in my home directory
  - Check disk usage
  - Show running processes
  - What's in /etc/hostname?
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
  },
  {
    "name": "file_read",
    "description": "Read the contents of a file",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "The path to the file to read"
        },
        "lines": {
          "type": "integer",
          "description": "The number of lines to read (default: all)"
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
          "description": "The path to the file to write"
        },
        "content": {
          "type": "string",
          "description": "The content to write to the file"
        },
        "append": {
          "type": "boolean",
          "description": "Append to file instead of overwriting"
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
          "description": "Filter processes by name"
        },
        "all": {
          "type": "boolean",
          "description": "Show all processes (not just user's)"
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
          "description": "Show usage for specific path"
        },
        "summary": {
          "type": "boolean",
          "description": "Show only total for directories"
        }
      }
    }
  }
]
EOF

echo "Created agent configuration..."

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Directory structure:"
ls -la "$FUNCTIONS_DIR/"
echo ""
echo "Verify with:"
echo "  aichat --list-agents"
echo "  aichat --agent system_agent 'check disk usage'"
