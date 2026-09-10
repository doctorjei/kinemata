"""Citation stamps: the time coordinate a citation does not carry.

A citation names a place. Without a time it cannot be judged, because a record
written in August that cites what was read in August stays correct after the
target moves -- and nothing in the target settles that, since the missing
information is in the document. The mechanism this replaces put currency in
configuration instead, exempting whole directories by glob, which cannot
separate a live section from an honest historical record inside one file.

This module is the **codec and the token, and deliberately nothing else**.
Whether an undated citation is a finding, which kinds of citation need a stamp,
and how old a stamp must be before it is surfaced are policy, left to the
adopting project by section 5 of ``docs/citations.md``. A knob for any of them
does not belong here.

The form is twelve characters in one bracket group -- seven timestamp
characters, a hyphen, a two-letter type -- and four more when the citation names
a bibliography entry::

    The registry contract is `docs/design.md` [0TMQDKB-Ty].
    The registry contract is `docs/design.md` [0TMQDKB-Pa0003].

**The number is optional because the two halves answer different questions.**
The stamp says *when*; the key says *which source*, and the entry for that key
says *where* -- so the volatile half, the address or the path, is declared once
in a bibliography and edited once when it moves. A citation that has not been
given an entry is still dated and still typed. Resolving a key is
:mod:`kinemata.adapters.bibliography`'s job, not this module's: nothing here
knows what a key points at.

**Square brackets, and not the three alternatives.** Angle brackets are literal
HTML in CommonMark whenever a letter follows, so a sanitizer would strip some
stamps from the rendered page while leaving them in the source -- a marker the
checker sees and the reader cannot is exactly backwards. Braces are inert in
CommonMark but claimed by Pandoc attributes, by MyST roles, and by Python string
formatting, which any document passing through an assembler meets. The at sign
addresses files and agents on the surfaces these documents are read on. Brackets
survive all of it and are already the universal reference-marker convention, so
a reader who has never seen this format still reads the stamp as an annotation.

**The hyphen, and not a colon.** Both are inert in markdown, so the choice was
made on behavior outside it: in YAML flow context a colon followed by a space
turns the token into a single-key mapping rather than a string, making the colon
form correct only until somebody inserts a space. The hyphen has no equivalent
failure, is legal in filenames where a colon is not, and is inert in URLs where
a colon means a scheme or a port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Crockford base32. I, L, O and U are absent so that no symbol can be confused
#: with 1 or 0, and the remaining thirty-two are in ASCII order -- which is what
#: makes a fixed-width big-endian encoding sort lexicographically as it sorts
#: numerically. Reordering this string would silently break that.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

BITS_PER_CHARACTER = 5

#: Years since :data:`EPOCH_YEAR`. **The year occupies the high bits, and that
#: is load-bearing**: it is the whole reason a stamp sorts chronologically as a
#: string, which ``tests/test_stamps.py`` verifies across a year boundary and
#: over the representable range rather than taking on trust.
YEAR_BITS = 10

#: Seconds since January 1, 00:00:00 UTC of the encoded year. Twenty-five bits
#: is sufficient with room to spare: a leap year holds 31,622,400 seconds
#: against a field capacity of 33,554,432, which is 22.4 days of headroom, so
#: leap seconds need no thought. That headroom is also unreachable, and
#: :func:`decode` refuses it -- see there.
SECOND_BITS = 25

#: Seven times five is thirty-five, with no padding and no waste. Six characters
#: would give thirty bits, which buys only 2000 through 2031.
STAMP_LENGTH = 7

#: Two letters, matched case-insensitively, which leaves 676 codes -- far more
#: than this needs, so each can be a mnemonic rather than an opaque index. The
#: rendered case pattern (first capital, second lowercase) is a reading aid and
#: carries no meaning: if it did, any pipeline that lowercases identifiers would
#: rewrite the type rather than merely making it harder to read.
TYPE_LENGTH = 2

#: Digits in a reference key's number, zero-padded to exactly this width.
#:
#: **Fixed width is not cosmetic.** Variable width makes ``Ru169`` and
#: ``Ru0169`` two spellings of one fact, which is the re-derivation this
#: project exists to catch, so a wrong width is refused rather than padded out
#: to the right one.
#:
#: **Four, so that an existing sequence migrates without being renumbered.** A
#: live corpus crossing a three-digit ceiling forces a renumber, and a renumber
#: breaks every cross-reference already pointing into it -- the exact churn this
#: scheme exists to prevent. One character is cheap against that.
KEY_DIGITS = 4

#: The separator is not redundant. The case shift alone does not mark the field
#: boundary, because the type's first letter is capitalized like the stamp, so
#: the seam only becomes visible at the second letter -- too late to read
#: comfortably.
SEPARATOR = "-"

EPOCH_YEAR = 2000
LAST_YEAR = EPOCH_YEAR + (1 << YEAR_BITS) - 1

_CHARACTERS = f"[{ALPHABET}]{{{STAMP_LENGTH}}}"
_TYPE = f"[A-Za-z]{{{TYPE_LENGTH}}}"

#: A reference key as it appears inside a token: the type, then the number or
#: nothing.
#:
#: **Any run of digits is matched here and the width checked afterward**, on
#: purpose. Pinning the count in the pattern would make ``[0TMQDKB-Ru169]``
#: match nothing at all, and a token nothing matches is a stamp the extractor
#: walks past -- a check that quietly stopped checking, which this package
#: treats as worse than no check. Matched loosely and refused loudly is the
#: shape used everywhere else here.
_KEY = f"{_TYPE}[0-9]*"
_KEY_ONLY = re.compile(_KEY)

#: A stamp's bracket contents. ``fullmatch`` against the text inside a bracket
#: group answers "is this a stamp rather than link text", which is what
#: :mod:`kinemata.claims` needs and all it needs.
CONTENT = re.compile(f"{_CHARACTERS}{SEPARATOR}{_KEY}", re.IGNORECASE)

#: The whole token, brackets included.
#:
#: **The character class is the alphabet, not "any alphanumeric", and that is a
#: deliberate trade.** Roughly one stamp in 119 encodes to seven characters that
#: are entirely hexadecimal, so an undelimited stamp is indistinguishable from a
#: short commit hash; the brackets close that without constraining the alphabet.
#: They do not, however, stop ordinary bracketed prose from having the shape --
#: ``[outline-Ab]`` is seven letters, a hyphen and two more. Restricting to the
#: alphabet keeps such prose from matching at all, so it is passed over rather
#: than dragged into a refusal it has nothing to do with. The cost is that a
#: stamp mistyped into a letter Crockford omits is invisible here instead of
#: reported; a loud wrong refusal on prose is the worse of the two.
TOKEN = re.compile(rf"\[({_CHARACTERS}{SEPARATOR}{_KEY})\]", re.IGNORECASE)


class StampError(Exception):
    """Text offered as a stamp that cannot be read as one.

    Raised rather than returning ``None`` or a plausible-looking moment. A
    decoder that quietly hands back a far-future date for a corrupt field is a
    check that has stopped checking while still reporting.
    """


def _year_start(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


def _year_seconds(year: int) -> int:
    """How long that year actually is.

    Taken from the calendar rather than from a leap-year rule written out here.
    The rule already has one home; a second copy is the re-derivation this
    project exists to catch, and it would be a copy of the exact fact the
    seconds field is validated against.
    """
    return int((_year_start(year + 1) - _year_start(year)).total_seconds())


def canonical_key(key: str) -> str:
    """A reference key written the way it is compared: ``Ru0169``.

    The case convention has one home here, for the reason
    :attr:`Stamp.canonical` gives: matching is case-insensitive everywhere, so a
    bibliography that resolves ``ru0169`` and one that resolves ``Ru0169`` must
    fold them the same way the token does. Two modules each deciding what a key
    looks like is how two matchers come to disagree about one string, which this
    package has already had to fix once between its own boundary rules.
    """
    return f"{key[:TYPE_LENGTH].capitalize()}{key[TYPE_LENGTH:]}"


def _reference(key: str) -> tuple[str, str | None]:
    """A key's type, and the whole key when a bibliography entry is named.

    **The number is optional and its absence is not a defect.** The number is
    what binds a citation to a bibliography entry, and a citation may be dated
    and typed without being bound -- ``[0TMQDKB-Pa]`` says when a path was
    looked at and what kind of thing it is, which is the whole of what a stamp
    promised before the key existed. A *wrong-width* number is a defect, because
    that is one fact with two spellings.
    """
    type_code, digits = key[:TYPE_LENGTH], key[TYPE_LENGTH:]
    if not digits:
        return type_code, None
    if len(digits) != KEY_DIGITS:
        raise StampError(
            f"{key!r} is not a reference key: the number is exactly "
            f"{KEY_DIGITS} digits, zero-padded, and {digits!r} is "
            f"{len(digits)}. Refused rather than padded -- two widths would be "
            "two spellings of one key."
        )
    return type_code, key


def reference_key(text: str) -> str:
    """Validate a key given on its own, and return it canonically spelled.

    What a bibliography declares and what a citation carries have to agree about
    the key's shape, so the shape is settled here -- in the module that owns the
    token -- rather than a second time beside the declarations. A second pattern
    is where two matchers begin to disagree about one string.

    Refuses a bare type, unlike :func:`parse`. A citation may be typed without
    being bound to an entry; a bibliography *entry* is the binding, so a key with
    no number declares nothing that could be cited.
    """
    if not _KEY_ONLY.fullmatch(text):
        raise StampError(
            f"{text!r} is not a reference key: {TYPE_LENGTH} letters naming a "
            f"type, then {KEY_DIGITS} digits"
        )
    _, key = _reference(text)
    if key is None:
        raise StampError(
            f"{text!r} names a type but no entry: a key carries its "
            f"{KEY_DIGITS}-digit number, which is what binds a citation to a "
            "bibliography entry."
        )
    return canonical_key(key)


@dataclass(frozen=True)
class Stamp:
    """One stamp, decoded, and where it was found.

    ``span`` is carried because association between a stamp and the citation it
    annotates is not built yet and will need position when it is. Recording it
    at extraction costs nothing; recovering it afterward means matching the text
    a second time against the line it came from, and the second match is free to
    disagree with the first.
    """

    #: Aware, UTC, second precision.
    moment: datetime

    #: ``None`` for a bare seven-character body, which carries no type.
    type_code: str | None

    #: Exactly as it appeared, before any case folding.
    text: str

    #: Half-open offsets into the line :func:`find` was given. ``(0, len(text))``
    #: when the stamp was parsed on its own rather than found in a line.
    span: tuple[int, int]

    #: The whole reference key -- type and number together, ``Ru0169`` -- when
    #: the citation names a bibliography entry, and ``None`` when it carries a
    #: type alone.
    #:
    #: Type *and* number, never the number by itself, because digits are unique
    #: only *within* a type: ``Ru0169`` and ``De0169`` are two different sources
    #: and the composite is what a bibliography indexes.
    key: str | None = None

    @property
    def canonical(self) -> str:
        """The stamp as it should be written: uppercase, key ``Xy`` or ``Xy0000``.

        Rendering lives here so the case convention has one home. Matching is
        case-insensitive everywhere, so this is a preference about how a stamp
        is written and never a condition on reading one.
        """
        body = encode(self.moment)
        if self.type_code is None:
            return body
        tail = canonical_key(self.key or self.type_code)
        return f"[{body}{SEPARATOR}{tail}]"


def encode(moment: datetime) -> str:
    """The seven-character timestamp for an aware moment.

    Truncated to the second, which is the precision the format has. A naive
    datetime is refused rather than assumed to be UTC: the assumption is right
    about half the time in a codebase that also builds local times, and when it
    is wrong it records a moment that is off by hours and looks entirely
    ordinary.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise StampError(
            "a naive datetime names no moment; give one with a time zone"
        )
    moment = moment.astimezone(UTC)
    if not EPOCH_YEAR <= moment.year <= LAST_YEAR:
        raise StampError(
            f"{moment.year} is outside the representable range "
            f"{EPOCH_YEAR}-{LAST_YEAR}"
        )
    seconds = int((moment - _year_start(moment.year)).total_seconds())
    value = ((moment.year - EPOCH_YEAR) << SECOND_BITS) | seconds
    return "".join(
        ALPHABET[(value >> shift) & (len(ALPHABET) - 1)]
        for shift in range(
            (STAMP_LENGTH - 1) * BITS_PER_CHARACTER, -1, -BITS_PER_CHARACTER
        )
    )


def decode(body: str) -> datetime:
    """The moment a seven-character timestamp names, as aware UTC.

    **Confusable substitutions are refused, not folded.** Crockford's spec
    suggests a decoder read I and L as 1 and O as 0, which is right for a value
    a person retypes off a screen. Nothing retypes these: ``kinemata stamp``
    emits a stamp and a document carries it verbatim, so the transcription error
    that leniency exists for does not arise. What does arise is a hand-edited
    stamp with a typo, and folding turns that into a different, entirely
    plausible moment reported as fact. Folding would also give one moment up to
    several spellings, at which point comparing stamps as text stops agreeing
    with comparing them as moments -- and comparing them as text is exactly what
    the high-bit year field was arranged to make work. :func:`encode` cannot
    emit them in the first place.

    **A seconds field longer than the year is refused too.** The field holds
    33,554,432 values and the longest year is 31,622,400 seconds, so 22.4 days
    of encodings name no time at all. A stamp landing there is malformed, and
    the only alternative -- rolling it into the following year -- would report a
    corrupt stamp as a real date in the wrong year.
    """
    if len(body) != STAMP_LENGTH:
        raise StampError(
            f"a timestamp is {STAMP_LENGTH} characters; {body!r} is {len(body)}"
        )
    value = 0
    for character in body.upper():
        digit = ALPHABET.find(character)
        if digit < 0:
            raise StampError(
                f"{character!r} is not a Crockford base32 symbol; I, L, O and U "
                "are absent from the alphabet and are refused rather than read "
                "as 1, 1, 0 and 0"
            )
        value = (value << BITS_PER_CHARACTER) | digit
    year = EPOCH_YEAR + (value >> SECOND_BITS)
    seconds = value & ((1 << SECOND_BITS) - 1)
    length = _year_seconds(year)
    if seconds >= length:
        raise StampError(
            f"{body!r} names second {seconds} of {year}, which has only "
            f"{length}; the field is wider than any year, so this is malformed "
            "rather than a later date"
        )
    return _year_start(year) + timedelta(seconds=seconds)


def parse(text: str) -> Stamp:
    """Read one stamp, given on its own.

    Accepts the full token, the same thing without its brackets, and a bare
    seven-character body. All three are spellings a person has in hand when they
    reach for the decoder -- pasted from a document, retyped without the
    punctuation, or copied out of the encoder, which emits no type. Refusing the
    last two would make the command awkward without catching anything, because
    nothing reads a stamp out of prose through here; :func:`find` does that, and
    it insists on the brackets.
    """
    candidate = text.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    # Split before validating, so the timestamp's own refusals reach the caller.
    # Testing the whole shape first would answer every defect with "not a
    # stamp", which is the least useful thing that can be said about a stamp
    # that is one character wrong -- and the confusable letters, the defect this
    # format most invites, would be reported as if the form were unrecognizable.
    body, separator, key = candidate.partition(SEPARATOR)
    if not separator:
        return Stamp(decode(body), None, text, (0, len(text)))
    if not _KEY_ONLY.fullmatch(key):
        raise StampError(
            f"{key!r} is not a type: expected {TYPE_LENGTH} letters after "
            f"{SEPARATOR!r}, optionally followed by a {KEY_DIGITS}-digit "
            "reference number"
        )
    type_code, reference = _reference(key)
    return Stamp(decode(body), type_code, text, (0, len(text)), reference)


def find(line: str) -> list[Stamp]:
    """Every stamp in one line, in the order they appear.

    Refuses on a token that has the declared shape and does not decode. Within
    brackets the shape is unambiguous -- that is what the delimiters were chosen
    to buy -- so text matching it is a stamp, and a stamp that names no moment is
    an error in the document rather than something to walk past.
    """
    found = []
    for match in TOKEN.finditer(line):
        body, _, key = match.group(1).partition(SEPARATOR)
        type_code, reference = _reference(key)
        found.append(
            Stamp(decode(body), type_code, match.group(0), match.span(),
                  reference)
        )
    return found
