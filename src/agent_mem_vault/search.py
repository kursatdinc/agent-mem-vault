import re
from datetime import UTC, datetime
from functools import lru_cache

import Stemmer

from agent_mem_vault.records import Record

_STEMMER = Stemmer.Stemmer("english")
_TOKEN = re.compile(r"\w+")
_TITLE_WEIGHT = 3
_ALIAS_WEIGHT = 2
_HALF_LIFE_DAYS = 30
_AGE_FLOOR = 0.5


@lru_cache(maxsize=50_000)
def _stem(word: str) -> str:
    return _STEMMER.stemWord(word)


def stems(text: str) -> list[str]:
    return [_stem(token) for token in _TOKEN.findall(text.lower())]


def query_stems(query: str) -> frozenset[str]:
    return frozenset(stems(query))


def _age_weight(created: str, now: datetime) -> float:
    """1 for a record created now, falling towards 0.5 with a 30-day half-life: 0.75 at 30 days, 0.625 at 60.

    A missing or unreadable `created` counts as old (0.5); a date without a zone is read as UTC.
    """
    try:
        moment = datetime.fromisoformat(created)
    except ValueError:
        return _AGE_FLOOR
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    age_days = max((now - moment).total_seconds() / 86_400, 0.0)
    return _AGE_FLOOR + (1 - _AGE_FLOOR) * 2 ** (-age_days / _HALF_LIFE_DAYS)


def score(record: Record, wanted: frozenset[str], now: datetime) -> float | None:
    """Rank a record for a query, or return None when it does not match.

    A record matches when every query stem occurs in its title, aliases, content or tags. The text score is 3 per
    title stem hit, 2 per alias stem hit and 1 per content stem hit, multiplied by the record's age weight, so a
    record more than twice another's text score still ranks above it however old it is.
    """
    if not wanted:
        return None
    title = stems(record.title)
    aliases = stems(" ".join(record.aliases))
    content = stems(record.content)
    tags = stems(" ".join(record.tags))
    if not wanted <= {*title, *aliases, *content, *tags}:
        return None
    hits = (
        _TITLE_WEIGHT * sum(1 for stem in title if stem in wanted)
        + _ALIAS_WEIGHT * sum(1 for stem in aliases if stem in wanted)
        + sum(1 for stem in content if stem in wanted)
    )
    return hits * _age_weight(record.created, now)
