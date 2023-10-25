# ~/~ begin <<docs/index.md#loom/logging.py>>[init]
import logging


def logger():
    return logging.getLogger("loom")


logger().level = logging.DEBUG
# ~/~ end
