"""Strict OpenFootball normalization with stable fixture and club identities."""
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
import itertools
from pathlib import Path

from .storage import digest, read_json

SEASONS = tuple(f"{y}-{str(y+1)[2:]}" for y in range(2020, 2026))
HOLDOUT = "2025-26"
CLUBS = (
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton & Hove Albion",
    "Burnley", "Chelsea", "Coventry City", "Crystal Palace", "Everton", "Fulham",
    "Hull City", "Ipswich Town", "Leeds United", "Leicester City", "Liverpool",
    "Luton Town", "Manchester City", "Manchester United", "Newcastle United",
    "Norwich City", "Nottingham Forest", "Sheffield United", "Southampton",
    "Sunderland", "Tottenham Hotspur", "Watford", "West Bromwich Albion",
    "West Ham United", "Wolverhampton Wanderers",
)
ALIASES = {label: club.lower().replace(" & ", "-").replace(" ", "-")
           for club in CLUBS for label in (club, club+" FC", club+" AFC")}
ALIASES["AFC Bournemouth"] = ALIASES["Bournemouth"]


@dataclass(frozen=True)
class Fixture:
    season: str
    played_date: str
    home: str
    away: str
    home_goals: int | None = None
    away_goals: int | None = None

    @property
    def fixture_id(self):
        return ":".join((self.season, self.home, self.away))

    @property
    def key(self):
        return self.season, self.home, self.away

    @property
    def complete(self):
        return all(type(x) is int and x >= 0 for x in (self.home_goals, self.away_goals))

    def metadata(self):
        return {"fixture_id": self.fixture_id, "season": self.season, "played_date": self.played_date,
                "home": self.home, "away": self.away}


def pair(value):
    if not isinstance(value, list) or len(value) != 2 or not all(type(x) is int and x >= 0 for x in value):
        raise ValueError("Full-time goals must be two non-negative integers")
    return tuple(value)


def normalize(items, season):
    result = []
    for item in items:
        day = date.fromisoformat(item["date"]).isoformat()
        home, away = ALIASES[item["team1"].strip()], ALIASES[item["team2"].strip()]
        if home == away:
            raise ValueError("A club cannot play itself")
        score = item.get("score")
        if score is None:
            goals = (None, None)
        elif isinstance(score, list):
            goals = pair(score)
        elif isinstance(score, dict) and "ft" in score and not set(score)-{"ft", "ht"}:
            goals = pair(score["ft"])
            if "ht" in score and any(h > f for h, f in zip(pair(score["ht"]), goals)):
                raise ValueError("Half-time goals exceed full-time goals")
        else:
            raise ValueError("Unresolved score representation")
        result.append(Fixture(season, day, home, away, *goals))
    return result


def validate_season(fixtures, season):
    clubs = {m.home for m in fixtures} | {m.away for m in fixtures}
    counts = Counter(m.key for m in fixtures)
    expected = {(season,h,a) for h,a in itertools.permutations(clubs,2)}
    yr = int(season[:4])
    if (len(fixtures) != 380 or len(clubs) != 20 or set(counts) != expected
            or any(n != 1 for n in counts.values()) or not all(m.complete for m in fixtures)
            or not all(date(yr,7,1) <= date.fromisoformat(m.played_date) <= date(yr+1,6,30) for m in fixtures)):
        raise ValueError(f"Season {season} violates the 380-fixture completed-season contract")


def load_pinned(input_path, manifest_path):
    input_path = Path(input_path)
    manifest = read_json(manifest_path)
    fixtures, pins = [], []
    for season in SEASONS:
        path = input_path/season/"en.1.json"
        candidates = [x for x in manifest["files"] if x["path"].endswith(f"football.json/{season}/en.1.json")]
        if len(candidates) != 1 or digest(path) != candidates[0]["sha256"]:
            raise ValueError(f"Missing or changed input pin for {season}")
        rows = normalize(read_json(path)["matches"], season)
        validate_season(rows,season)
        fixtures.extend(rows)
        pins.append({"season":season,"sha256":digest(path),"url":candidates[0]["url"]})
    fixtures.sort(key=lambda m:(m.played_date,m.home,m.away))
    return fixtures, {"files":pins,"repositories":manifest.get("repositories",{})}
