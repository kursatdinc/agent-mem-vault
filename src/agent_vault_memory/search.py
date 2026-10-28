import re
from functools import lru_cache

import Stemmer

from agent_vault_memory.records import Record

_STEMMER = Stemmer.Stemmer("english")
_TOKEN = re.compile(r"\w+")
_TITLE_WEIGHT = 3


@lru_cache(maxsize=50_000)
def _stem(word: str) -> str:
    return _STEMMER.stemWord(word)


def stems(text: str) -> list[str]:
    return [_stem(token) for token in _TOKEN.findall(text.lower())]


def query_stems(query: str) -> frozenset[str]:
    return frozenset(stems(query))


def score(record: Record, wanted: frozenset[str]) -> int | None:
    """Rank a record for a query, or return None when it does not match.

    A record matches when every query stem occurs in its title, content or tags.
    The score is 3 per title stem hit plus 1 per content stem hit.
    """
    if not wanted:
        return None
    title = stems(record.title)
    content = stems(record.content)
    tags = stems(" ".join(record.tags))
    if not wanted <= {*title, *content, *tags}:
        return None
    return _TITLE_WEIGHT * sum(1 for stem in title if stem in wanted) + sum(1 for stem in content if stem in wanted)
