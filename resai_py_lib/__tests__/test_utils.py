import pickle

import jsonpickle
import pytest

from resai_py_lib.utils import Serializable


class A(Serializable):
    def __init__(self, a: Serializable):
        self.a = a


class B(Serializable):
    def __init__(self, b: Serializable):
        self.b = b


class C(Serializable):
    exclude_serialization = ["c2"]

    def __init__(self, c1: str, c2: str):
        self.c1 = c1
        self.c2 = c2


def test_serializable():
    a = A(B(C("inner data", "inner data 2")))

    a_unpickled = pickle.loads(pickle.dumps(a))
    assert isinstance(a_unpickled, A)
    assert isinstance(a_unpickled.a, B)
    assert isinstance(a_unpickled.a.b, C)
    with pytest.raises(AttributeError):
        # noinspection PyStatementEffect
        a_unpickled.a.b.c2

    a_unpickled = jsonpickle.loads(jsonpickle.dumps(a))
    assert isinstance(a_unpickled, A)
    assert isinstance(a_unpickled.a, B)
    assert isinstance(a_unpickled.a.b, C)
    with pytest.raises(AttributeError):
        # noinspection PyStatementEffect
        a_unpickled.a.b.c2
