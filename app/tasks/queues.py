"""RQ queue definitions and Redis connection."""
from redis import Redis
from rq import Queue

from app.config import settings

# Redis connection
redis_conn = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
)

# Priority queues
high_queue = Queue("high", connection=redis_conn)  # Commands, small messages
default_queue = Queue("default", connection=redis_conn)  # Normal chat
low_queue = Queue("low", connection=redis_conn)  # Compression, cleanup
browser_queue = Queue("browser", connection=redis_conn)  # Browser agent (single worker)


def get_queue(priority: str = "default") -> Queue:
    """Get queue by priority name."""
    queues = {
        "high": high_queue,
        "default": default_queue,
        "low": low_queue,
        "browser": browser_queue,
    }
    return queues.get(priority, default_queue)
