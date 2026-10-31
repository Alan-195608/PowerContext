# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encode the prepared-context JSON envelope so it stays on one physical line."""

from __future__ import annotations

import json
from typing import Any

# Python's ``str.splitlines`` treats these three characters as line breaks, but
# ``json.dumps`` leaves them unescaped even though JSON allows them literally
# inside a string. The other five line-breaking characters (``\v``, ``\f``,
# ``\x1c``, ``\x1d``, ``\x1e``) are already escaped by ``json.dumps``.
_LINE_BREAKING_CHARACTERS = ("\u0085", "\u2028", "\u2029")


def encode_envelope(payload: Any) -> str:
    """Encode ``payload`` as compact JSON that occupies exactly one physical line.

    The decoded payload is unchanged: only the *serialised* form differs, so the
    original characters survive a JSON round trip exactly and a literal
    ``\\uXXXX`` sequence in the source text stays a literal backslash sequence.
    Escaping only the line-breaking characters keeps non-ASCII content compact
    instead of paying for a full ``\\uXXXX`` escape of every character.
    """
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for character in _LINE_BREAKING_CHARACTERS:
        encoded = encoded.replace(character, f"\\u{ord(character):04x}")
    return encoded
