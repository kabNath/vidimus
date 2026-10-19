"""Golden canonical-form vectors, shared by the Python and Node (browser verifier) suites.

Each entry is ``(name, value, expected canonical UTF-8 bytes, expected SHA-256 hex)``. The
bytes are fixed forever: if one of them changes, previously signed attestations stop
verifying. Source is pure ASCII (escapes only) so no locale can alter the vectors.
"""

from __future__ import annotations

from typing import Any

GOLDEN: list[tuple[str, Any, bytes, str]] = [
    (
        "ascii_object",
        {"b": 1, "a": [True, None, "x"], "c": {"z": 1, "y": 2}},
        b'{"a":[true,null,"x"],"b":1,"c":{"y":2,"z":1}}',
        "9a477b86a6cb8243d07b75b998233f915bd54225f826ce99149a443c5ebca207",
    ),
    (
        "non_ascii",
        {"ä": 1, "Z": 2, "中": "é \U0001f600", "a": "plain"},
        b'{"Z":2,"a":"plain","\xc3\xa4":1,"\xe4\xb8\xad":"\xc3\xa9 \xf0\x9f\x98\x80"}',
        "470f022189c19e492b4cd1ce2c84ca137215ff0519f7cd41af2ef392e6e3ae3f",
    ),
    (
        "controls_and_escapes",
        'q"\\ \n\t\r\b\f \x01\x1f /',
        b'"q\\"\\\\ \\n\\t\\r\\b\\f \\u0001\\u001f /"',
        "c6cbd03a5f33888fe04f3511d6f660ff99b8acb60636aa85348ecd45960e072d",
    ),
    (
        "floats",
        [
            0.1,
            0.30000000000000004,
            1e-05,
            1.5e-07,
            1e16,
            1e21,
            1e22,
            123456789012345680.0,
            12345.678,
            -2.5e-10,
            5e-324,
            1.7976931348623157e308,
            1.0,
            -0.0,
            100.0,
        ],
        b"[0.1,0.30000000000000004,1e-05,1.5e-07,1e+16,1e+21,1e+22,1.2345678901234568e+17,"
        b"12345.678,-2.5e-10,5e-324,1.7976931348623157e+308,1,0,100]",
        "7131a83dbd456e9d82fa2b926804b407917c4cc53c2efc116295d9f10e766f04",
    ),
    (
        "integers",
        [0, -7, 2**53 - 1, -(2**53 - 1), 2**53],
        b"[0,-7,9007199254740991,-9007199254740991,9007199254740992]",
        "93399ba79de4a9be1d697f6f832670e9e8778be501229acb44f4d222571e038c",
    ),
    (
        "nested_and_empty",
        [{"k": 1e-05}, [], {}, [[]], {"": None}],
        b'[{"k":1e-05},[],{},[[]],{"":null}]',
        "e3fb72146308e6d7c3ab2ecd54d063c40190d2bdb0bb24d205013c740945483f",
    ),
]
