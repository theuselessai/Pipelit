# Getting Started

Welcome to Pipelit! This section guides you through installing, configuring, and running the platform.

## Two Ways to Run Pipelit

### Via plit CLI (Recommended)

The easiest way to run Pipelit is through the [plit](https://github.com/theuselessai/plit) CLI, which manages Pipelit as a Docker container alongside the message gateway:

```bash
curl -fsSL https://raw.githubusercontent.com/theuselessai/plit/main/install.sh | bash
plit init
plit start
```

See the [plit documentation](https://github.com/theuselessai/plit) for details.

### Standalone (Development)

If you're contributing to Pipelit or want to run it outside Docker, follow the steps below.

## Prerequisites

| Requirement | Minimum Version | Purpose |
|-------------|----------------|---------|
| Python | 3.10+ | Backend runtime |
| Redis | 8.0+ | Task queue, pub/sub, search |
| Node.js | 18+ | Frontend build |
| bubblewrap | 0.4+ | Sandboxed shell execution (Linux) |

## Steps

<div class="grid" markdown>

<div class="card" markdown>

### 1. [Installation](installation.md)

Clone the repository, set up a Python virtual environment, and install dependencies.

</div>

<div class="card" markdown>

### 2. [Configuration](configuration.md)

Generate an encryption key, configure Redis, and set up your `.env` file.

</div>

<div class="card" markdown>

### 3. [First Run](first-run.md)

Start the backend, workers, and frontend. Create your admin account via CLI.

</div>

<div class="card" markdown>

### 4. [Quickstart Tutorial](quickstart-tutorial.md)

Build your first workflow end-to-end — a chat agent that can answer questions using tools.

</div>

</div>
