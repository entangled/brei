from pathlib import Path
from typing import Optional
from loom.lazy import Phony
from loom.utility import construct


def test_construct_path():
    assert isinstance(construct(Path, "hello.txt"), Path)
    assert construct(Optional[Path], None) is None
    assert isinstance(construct(Phony | Path, "hello.txt"), Path)
    assert isinstance(construct(Phony | Path, "#all"), Phony)
