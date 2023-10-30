# ~/~ begin <<docs/implementation.md#brei/logging.py>>[init]
import logging
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler

def logger():
    return logging.getLogger("brei")

def configure_logger(debug: bool):
    class BackTickHighlighter(RegexHighlighter):
        highlights = [r"`(?P<bold>[^`]*)`"]

    FORMAT = "%(message)s"
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=FORMAT,
        datefmt="[%X]",
        handlers=[RichHandler(show_path=debug, highlighter=BackTickHighlighter())],
    )

# logging.basicConfig(level=logging.INFO)
# logger().level = logging.INFO
# ~/~ end