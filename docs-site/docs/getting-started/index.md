# Getting Started

Welcome to Pipelit! This section will guide you through installing, configuring, and running the platform for the first time.

## Prerequisites

Before you begin, make sure you have:

- **Python 3.10+** — Backend runtime
- **Redis 8.0+** — Task queue, pub/sub, and search (includes RediSearch natively)
- **Node.js 18+** — Frontend build toolchain

## Steps

<div class="grid" markdown>

<div class="card" markdown>

### 1. [Installation](installation.md)

Clone the repository, set up a Python virtual environment, and install backend and frontend dependencies.

</div>

<div class="card" markdown>

### 2. [Configuration](configuration.md)

Generate an encryption key, configure Redis, and set up your `.env` file.

</div>

<div class="card" markdown>

### 3. [First Run](first-run.md)

Start the backend, RQ worker, and frontend dev server. Create your admin account through the setup wizard.

</div>

<div class="card" markdown>

### 4. [Quickstart Tutorial](quickstart-tutorial.md)

Build your first workflow end-to-end — a chat agent that can answer questions using tools.

</div>

</div>
