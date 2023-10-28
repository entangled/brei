# ~/~ begin <<docs/index.md#loom/logging.py>>[init]
import logging


def logger():
    return logging.getLogger("loom")


logging.basicConfig(level=logging.INFO)
logger().level = logging.INFO
# ~/~ end
