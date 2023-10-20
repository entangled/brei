from loom.task import Phony

# from entangled.parsing import


def test_phony_parsing():
    x = Phony.from_str("phony(all)")
    assert x == Phony("all")
    assert str(x) == "phony(all)"
