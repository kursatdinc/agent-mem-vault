import math
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
_PARTIAL_SHARE = 0.5
_FILLER_WORDS = frozenset(
    "a an the and or of to in on for with is are was were be do does did why how what when which who we it this that "
    "vs from by at as if not no".split()
)


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


def _match(record: Record, wanted: frozenset[str]) -> tuple[frozenset[str], int]:
    """The query stems a record holds in its title, aliases, content or tags, and their weighted hit count."""
    title = stems(record.title)
    aliases = stems(" ".join(record.aliases))
    content = stems(record.content)
    tags = stems(" ".join(record.tags))
    hits = (
        _TITLE_WEIGHT * sum(1 for stem in title if stem in wanted)
        + _ALIAS_WEIGHT * sum(1 for stem in aliases if stem in wanted)
        + sum(1 for stem in content if stem in wanted)
    )
    return wanted & {*title, *aliases, *content, *tags}, hits


def score(record: Record, wanted: frozenset[str], now: datetime) -> float | None:
    """Rank a record for a query, or return None when it does not match.

    A record matches when every query stem occurs in its title, aliases, content or tags. The text score is 3 per
    title stem hit, 2 per alias stem hit and 1 per content stem hit, multiplied by the record's age weight, so a
    record more than twice another's text score still ranks above it however old it is.
    """
    if not wanted:
        return None
    matched, hits = _match(record, wanted)
    if matched != wanted:
        return None
    return hits * _age_weight(record.created, now)


def partial_stems(query: str) -> frozenset[str]:
    """The stems of a query without its filler words, for a search that need not match every word."""
    return frozenset(_stem(token) for token in _TOKEN.findall(query.lower()) if token not in _FILLER_WORDS)


def partial_score(record: Record, wanted: frozenset[str], now: datetime) -> float | None:
    """Rank a record that holds at least half of the query stems, or return None.

    The score of `score` is multiplied by the square of the share of query stems the record holds, so a record
    holding more of the query ranks above one that only repeats a word.
    """
    matched, hits = _match(record, wanted)
    if len(matched) < max(1, math.ceil(len(wanted) * _PARTIAL_SHARE)):
        return None
    return hits * (len(matched) / len(wanted)) ** 2 * _age_weight(record.created, now)
