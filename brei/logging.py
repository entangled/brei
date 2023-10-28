# ~/~ begin <<docs/index.md#brei/logging.py>>[init]
import logging


def logger():
    return logging.getLogger("brei")


logging.basicConfig(level=logging.INFO)
logger().level = logging.INFO
# ~/~ end