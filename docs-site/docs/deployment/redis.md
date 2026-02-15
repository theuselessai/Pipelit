# Redis Setup

Pipelit requires **Redis 8.0+** which includes the RediSearch module natively. This module powers full-text search capabilities used by the memory system. Older Redis versions will fail with `unknown command 'FT._LIST'`.

## Why Redis 8+?

Prior to Redis 8, the RediSearch module had to be installed separately (via Redis Stack or manual module loading). Redis 8.0 integrated RediSearch directly into the core server, removing the need for separate module installation.

Pipelit uses Redis for three purposes:

| Purpose | Redis Feature |
|---------|--------------|
| **Task queue** | RQ (Redis Queue) for background job processing |
| **Pub/sub** | Real-time WebSocket event broadcasting |
| **Full-text search** | RediSearch (`FT.*` commands) for memory recall |

## Installation

=== "Docker (easiest)"

    ```bash
    docker run -d --name redis -p 6379:6379 redis:8
    ```

    This is the fastest way to get Redis 8 running. The container exposes port 6379 on localhost.

=== "Debian / Ubuntu"

    Add the official Redis repository and install:

    ```bash
    curl -fsSL https://packages.redis.io/gpg | \
        sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
    sudo chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg

    echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] \
        https://packages.redis.io/deb $(lsb_release -cs) main" | \
        sudo tee /etc/apt/sources.list.d/redis.list

    sudo apt-get update
    sudo apt-get install redis
    ```

    The service starts automatically after installation.

=== "macOS"

    ```bash
    brew install redis
    brew services start redis
    ```

    Homebrew installs the latest Redis version (8.0+) by default.

## Verification

After installation, verify that the RediSearch module is available:

```bash
redis-cli MODULE LIST
```

The output should include the `search` module. Example:

```
1) 1) "name"
   2) "search"
   3) "ver"
   4) 80000
```

You can also verify with a quick connectivity check:

```bash
redis-cli ping
# Expected: PONG

redis-cli FT._LIST
# Expected: (empty array) — no error means the module is loaded
```

## Removing Older Redis Versions

If you have an older Redis version installed, remove it before installing Redis 8:

=== "Debian / Ubuntu"

    ```bash
    sudo systemctl stop redis-server
    sudo systemctl disable redis-server
    sudo apt remove --purge redis-server
    ```

=== "macOS"

    ```bash
    brew services stop redis
    brew uninstall redis
    ```

=== "Docker"

    ```bash
    docker stop redis
    docker rm redis
    ```

After removal, follow the [installation](#installation) instructions above to install Redis 8.

## Configuration

For production deployments, edit `/etc/redis/redis.conf` (or the equivalent for your platform):

```ini
# Bind to localhost only (security)
bind 127.0.0.1

# Set a password (recommended for production)
requirepass your-redis-password

# Enable persistence
save 900 1
save 300 10
save 60 10000

# Set max memory (adjust for your server)
maxmemory 256mb
maxmemory-policy allkeys-lru
```

If you set a Redis password, update your `.env` file:

```env
REDIS_URL=redis://:your-redis-password@localhost:6379/0
```

## Workaround Without Redis 8

If you cannot upgrade to Redis 8, there is a partial workaround:

Enable `conversation_memory` on agent nodes that use `spawn_and_await`. This switches the checkpointer from `RedisSaver` to `SqliteSaver`, bypassing the RediSearch requirement for that specific feature.

!!! warning "Limited functionality"
    This workaround only addresses the checkpointer. Other features that rely on RediSearch (such as memory recall with full-text search) will not function without Redis 8+. Upgrading Redis is strongly recommended.

## Troubleshooting

### `unknown command 'FT._LIST'`

Your Redis version is older than 8.0. Check your version:

```bash
redis-cli INFO server | grep redis_version
```

If the version is below 8.0, follow the [installation](#installation) instructions to upgrade.

### `Connection refused` on port 6379

Redis is not running. Start it:

```bash
# systemd
sudo systemctl start redis

# Docker
docker start redis

# macOS
brew services start redis
```

### `NOAUTH Authentication required`

Redis has a password set. Update your `REDIS_URL` in `.env`:

```env
REDIS_URL=redis://:your-password@localhost:6379/0
```
