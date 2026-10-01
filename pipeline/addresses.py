"""
Address normalisation for Companies House registered offices.

Why this exists
---------------
Two questions in this study depend on deciding whether two companies sit at
the same address:

  1. Succession. When a restaurant dies and a takeaway is incorporated at the
     same premises six months later, that is the thesis made visible. Finding
     those pairs requires matching addresses across companies that typed them
     differently ("12 High St", "12 HIGH STREET", "Unit 1, 12 High Street").

  2. Mass registration. Many small companies register at their accountant's
     office rather than their shop. An address with 40 companies at it is a service
     address, not a high street. Those addresses must be detected and excluded
     from the succession analysis, or the study would "discover" that a
     Finchley accountant's front door is the most turbulent restaurant site in
     London.

The normalisation is deliberately conservative. It is better to fail to match
two spellings of the same address (losing a true succession pair) than to
merge two genuinely different addresses (inventing one). Recall is sacrificed
for precision, and the report states the resulting undercount.

The approach follows one developed earlier for an address-search tool over
the same Companies House dataset.
"""

from __future__ import annotations

import re

# "C/O SOME FIRM LTD, 12 HIGH STREET" -- the company is care-of an agent.
_CO_PREFIX = re.compile(r"^\s*(?:C/O|C\.O\.?|CARE\s+OF)\s+", re.I)

# UK street-type words, full and abbreviated. Used to find where the agent's
# name stops and the real street begins.
_STREET_TYPES = (
    r"ROAD|RD|STREET|ST|AVENUE|AVE|LANE|LN|CLOSE|DRIVE|DR|WAY|PLACE|PL"
    r"|COURT|CT|ROW|GARDENS?|GDNS?|GROVE|HILL|WALK|RISE|CRESCENT|CRES"
    r"|TERRACE|PARADE|BROADWAY|MEWS|BUILDINGS?|CHAMBERS?|HOUSE|YARD|GATE"
    r"|WHARF|SQUARE|SQ|CIRCUS|PRECINCT|CENTRE|CENTER|QUAY|BANK|VILLAS?"
    r"|MARKET|GREEN|COMMON|PARK|HIGH\s+ROAD|HIGH\s+STREET"
)
_STREET_TYPE_WORD = re.compile(rf"^(?:{_STREET_TYPES})$", re.I)

# Unit designators that describe a subdivision of a building rather than a
# different building. Dropped so that "Unit 3, 12 High Street" and
# "12 High Street" resolve to the same premises -- correct for succession,
# since a new tenant of the same shop often numbers the unit differently.
_UNIT_PREFIX = re.compile(
    r"^\s*(?:UNIT|SUITE|FLAT|APT|APARTMENT|ROOM|OFFICE|SHOP|STUDIO|FLOOR|"
    r"GROUND\s+FLOOR|FIRST\s+FLOOR|SECOND\s+FLOOR|BASEMENT|REAR\s+OF|"
    r"PART\s+(?:GROUND|FIRST|SECOND)\s+FLOOR)\s*[-:,]?\s*\w{0,4}\s*[-:,]?\s*",
    re.I,
)

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

# Some registers append the post town to the street line and some do not.
# Food Standards Agency records from Barnet read "378 Ballards Lane London"
# where Companies House holds "378 Ballards Lane" -- one trailing word apart,
# and without stripping it the two never match. Removing a trailing post town
# is safe: none of these words is a street name on its own, and the postcode
# stays in the key to preserve precision.
_TRAILING_TOWN = re.compile(
    r"\s+(?:LONDON|GREATER LONDON|MIDDLESEX|MIDDX|ESSEX|SURREY|KENT|HERTS"
    r"|HERTFORDSHIRE|UNITED KINGDOM|UK|ENGLAND)$",
    re.I,
)


def strip_care_of(addr1: str, addr2: str = "") -> tuple[str, str | None]:
    """Remove a care-of agent from an address line.

    Returns (address_without_agent, agent_name_or_None). The agent name is
    kept because a company registered care-of an accountant tells us something
    real -- it is almost certainly not trading from that postcode -- and the
    succession analysis needs to know.
    """
    a1 = (addr1 or "").strip()
    if not a1:
        return (addr2 or "").strip(), None

    m = _CO_PREFIX.match(a1)
    if m:
        rest = a1[m.end():].strip()
        # "C/O AGENT NAME, 12 HIGH STREET" -- split on the first house number.
        num = re.search(r"[,\s](\d+[A-Z]?\s+\w.*)$", rest)
        if num:
            return num.group(1).strip(), rest[: num.start()].strip()
        return (addr2 or "").strip(), rest

    # "12 C/O AGENT NAME HIGH STREET" -- the number leads, agent is infixed.
    infix = re.match(r"^(\S+)\s+C[/.]O\s+(.*)$", a1, re.I)
    if infix:
        number, rest = infix.group(1), infix.group(2)
        words = rest.split()
        for i in range(len(words) - 1, -1, -1):
            if _STREET_TYPE_WORD.match(words[i]):
                start = max(0, i - 1)  # keep one descriptor: HIGH ROAD, BOND STREET
                street = " ".join(words[start: i + 1])
                agent = " ".join(words[:start])
                return f"{number} {street}", agent or None
        return f"{number} {rest}", None

    return a1, None


def address_key(addr1: str, addr2: str, postcode: str) -> str:
    """A comparable key for a physical premises.

    Built from the house number and street of the first address line plus the
    full postcode. Punctuation, unit designators and whitespace variation are
    removed. Two companies sharing a key are treated as sharing premises.

    An empty postcode returns an empty key: without a postcode the match is
    not safe enough to use, and those companies drop out of the succession
    analysis rather than being guessed at.
    """
    pc = _WS.sub("", (postcode or "").upper())
    if not pc:
        return ""

    street, _agent = strip_care_of(addr1, addr2)
    street = _UNIT_PREFIX.sub("", street.upper())
    street = _PUNCT.sub(" ", street)
    street = _WS.sub(" ", street).strip()

    # Fall back to the second line if stripping emptied the first.
    if not street:
        street = _WS.sub(" ", _PUNCT.sub(" ", (addr2 or "").upper())).strip()

    # Repeatedly, because "High Road London Greater London" occurs.
    previous = None
    while previous != street:
        previous = street
        street = _TRAILING_TOWN.sub("", street).strip()

    return f"{street}|{pc}" if street else ""


def postcode_area(postcode: str) -> str:
    """The alphabetic area prefix of a UK postcode: 'N12 0NL' -> 'N'."""
    m = re.match(r"^([A-Z]{1,2})", (postcode or "").strip().upper())
    return m.group(1) if m else ""


def postcode_district(postcode: str) -> str:
    """The outward code of a UK postcode: 'N12 0NL' -> 'N12'."""
    pc = _WS.sub(" ", (postcode or "").strip().upper())
    return pc.split(" ")[0] if pc else ""


def normalise_postcode(postcode: str) -> str:
    """Canonical 'N12 0NL' form, or '' if it does not look like a postcode."""
    pc = re.sub(r"[^A-Z0-9]", "", (postcode or "").upper())
    if len(pc) < 5 or len(pc) > 7:
        return ""
    return f"{pc[:-3]} {pc[-3:]}"
