from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, MutableMapping, Optional, Sequence

JsonDict = Dict[str, Any]
JsonList = List[Any]
PathLike = str | Path
TextEmbedder = Callable[[Sequence[str]], List[List[float]]]
Metadata = MutableMapping[str, Any]
OptionalStrList = Optional[List[str]]
TextSequence = Iterable[str]
