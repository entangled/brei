# ~/~ begin <<docs/implementation.md#brei/logging.py>>[init]
import logging
import sys
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler

def logger():
    return logging.getLogger("brei")

def configure_logger(debug: bool, rich: bool = True):
    class BackTickHighlighter(RegexHighlighter):
        highlights = [r"`(?P<bold>[^`]*)`"]

    if rich:
        FORMAT = "%(message)s"
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format=FORMAT,
            datefmt="[%X]",
            handlers=[RichHandler(show_path=debug, highlighter=BackTickHighlighter())],
        )
    else:
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            handlers=[logging.StreamHandler(sys.stdout)]
        )
# ~/~ end