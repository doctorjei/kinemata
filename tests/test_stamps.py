"""Citation stamps: the codec, and the two ways a compact encoding lies.

A seven-character token is unreadable by eye, so every property it is supposed
to have has to be checked mechanically or not at all. The two that matter are
that it round-trips, and that sorting the text sorts the moments -- the second
being the reason the year sits in the high bits, and the kind of claim that is
easy to reason yourself into and hard to notice being wrong about.
"""

from __future__ import annotations

import dataclasses
import random
from datetime import UTC, datetime, timedelta, timezone

import pytest

from kinemata.stamps import (
    ALPHABET,
    BITS_PER_CHARACTER,
    EPOCH_YEAR,
    LAST_YEAR,
    SECOND_BITS,
    STAMP_LENGTH,
    YEAR_BITS,
    Stamp,
    StampError,
    canonical_key,
    decode,
    encode,
    find,
    parse,
    reference_key,
)


def moment(year, month=1, day=1, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def year_seconds(year):
    return int((moment(year + 1) - moment(year)).total_seconds())


def encode_raw(year, seconds):
    """A stamp built from field values, bypassing the calendar.

    Needed because `encode` cannot produce an out-of-range seconds field -- it
    derives that field from a real datetime -- and the refusal under test is
    exactly about the values it cannot produce.
    """
    value = ((year - EPOCH_YEAR) << SECOND_BITS) | seconds
    return "".join(
        ALPHABET[(value >> shift) & (len(ALPHABET) - 1)]
        for shift in range(
            (STAMP_LENGTH - 1) * BITS_PER_CHARACTER, -1, -BITS_PER_CHARACTER
        )
    )


# -- the field layout ---------------------------------------------------------


def test_the_fields_exactly_fill_the_characters():
    """Seven times five is thirty-five, with no padding and no waste.

    Stated in the specification as an exact fit, which makes it a fact nothing
    was checking: a later widening of either field would still encode, and would
    silently drop the high bits of the year.
    """
    assert YEAR_BITS + SECOND_BITS == STAMP_LENGTH * BITS_PER_CHARACTER
    assert len(ALPHABET) == 1 << BITS_PER_CHARACTER


def test_the_alphabet_is_crockford_and_in_ascii_order():
    """Order is not cosmetic here; the sort property below rests on it."""
    assert set("ILOU").isdisjoint(ALPHABET)
    assert list(ALPHABET) == sorted(ALPHABET)


def test_the_year_field_reaches_the_documented_range():
    assert (EPOCH_YEAR, LAST_YEAR) == (2000, 3023)


def test_the_seconds_field_has_the_documented_headroom():
    """22.4 days of encodings that name no time -- the reason decoding refuses.

    The number is quoted in `docs/citations.md` as the argument that leap
    seconds need no thought. Pinned so that changing a field width shows up as
    a failed claim rather than as prose that stopped being true.
    """
    longest = max(year_seconds(year) for year in (2023, 2024))
    assert longest == 31622400
    unreachable = (1 << SECOND_BITS) - longest
    assert unreachable == 1932032
    assert round(unreachable / 86400, 1) == 22.4


# -- round trip ---------------------------------------------------------------


@pytest.mark.parametrize(
    "when",
    [
        moment(EPOCH_YEAR),
        moment(LAST_YEAR, 12, 31, 23, 59, 59),
        moment(2026, 9, 9, 14, 38, 35),
        moment(2024, 2, 29, 12, 0, 0),      # a day only a leap year has
        moment(2024, 12, 31, 23, 59, 59),   # the last second of a leap year
        moment(2023, 12, 31, 23, 59, 59),   # and of a common one
    ],
)
def test_a_moment_survives_the_round_trip(when):
    assert decode(encode(when)) == when


def test_a_stamp_is_seven_characters_from_the_alphabet():
    body = encode(moment(2026, 9, 9, 14, 38, 35))
    assert len(body) == STAMP_LENGTH
    assert set(body) <= set(ALPHABET)


def test_encoding_never_emits_a_confusable_character():
    """The half of the confusable question that has no trade-off in it."""
    rng = random.Random(20260909)
    for _ in range(500):
        year = rng.randint(EPOCH_YEAR, LAST_YEAR)
        when = moment(year) + timedelta(seconds=rng.randrange(year_seconds(year)))
        assert set("ILOUilou").isdisjoint(encode(when))


def test_a_moment_is_truncated_to_the_second():
    """The format has second precision; sub-second input is not an error."""
    when = moment(2026, 9, 9, 14, 38, 35)
    assert encode(when.replace(microsecond=999999)) == encode(when)


def test_a_moment_outside_utc_is_converted_rather_than_read_as_local():
    east = timezone(timedelta(hours=5, minutes=30))
    assert encode(datetime(2026, 9, 9, 20, 8, 35, tzinfo=east)) == encode(
        moment(2026, 9, 9, 14, 38, 35)
    )


# -- the sort property --------------------------------------------------------
#
# The one claim in the specification that is a claim about the encoding rather
# than about markdown, and the one the high-bit year field exists to buy.


def test_text_order_is_time_order_across_every_year_boundary():
    """The boundary is where a big-endian layout would fail if it were wrong.

    Every boundary rather than one: a field-width mistake would show at a
    specific power of two, and a single sampled boundary is unlikely to be it.
    """
    for year in range(EPOCH_YEAR, LAST_YEAR):
        last = encode(moment(year + 1) - timedelta(seconds=1))
        first = encode(moment(year + 1))
        assert last < first, year


def test_text_order_is_time_order_over_the_representable_range():
    """Sorting the strings and sorting the moments must give the same list.

    Seeded rather than random so a failure can be reproduced, and anchored at
    both ends of the range so the sample cannot miss them.
    """
    rng = random.Random(20260909)
    moments = {moment(EPOCH_YEAR), moment(LAST_YEAR, 12, 31, 23, 59, 59)}
    while len(moments) < 2000:
        year = rng.randint(EPOCH_YEAR, LAST_YEAR)
        moments.add(moment(year) + timedelta(seconds=rng.randrange(year_seconds(year))))
    by_text = sorted(encode(when) for when in moments)
    by_time = [encode(when) for when in sorted(moments)]
    assert by_text == by_time


# -- refusals -----------------------------------------------------------------


def test_a_seconds_field_longer_than_the_year_is_refused():
    """The 22.4 days that name no time.

    `0ZZZZZZ` is year 2031 with every seconds bit set. Rolling it into 2032
    would report a corrupt stamp as a real date in the wrong year, which is the
    plausible-looking answer this project would rather not give.
    """
    with pytest.raises(StampError, match="malformed"):
        decode("0ZZZZZZ")


def test_the_length_refused_depends_on_whether_the_year_is_a_leap_year():
    """One second past the end of 2023 is a real second of 2024.

    A single hard-coded year length would accept the first and reject the
    second, or the other way round, and would look correct in whichever test
    was written first.
    """
    common, leap = 2023, 2024
    assert year_seconds(common) < year_seconds(leap)
    at_end_of_common = timedelta(seconds=year_seconds(common))
    assert decode(encode(moment(leap) + at_end_of_common)) == moment(leap) + at_end_of_common
    with pytest.raises(StampError, match="malformed"):
        decode(encode_raw(common, year_seconds(common)))


@pytest.mark.parametrize("character", ["I", "L", "O", "U", "i", "l", "o", "u"])
def test_a_confusable_character_is_refused_rather_than_folded(character):
    """The decision recorded in `decode`, pinned as behavior.

    Crockford suggests folding I and L to 1 and O to 0 for a value a person
    retypes. Nothing retypes these, so folding would only ever turn a typo into
    a different plausible moment -- and would give one moment several spellings,
    at which point comparing stamps as text stops agreeing with the sort
    property above.
    """
    with pytest.raises(StampError, match="Crockford"):
        decode("0TMQDK" + character)


@pytest.mark.parametrize("body", ["", "0TMQDK", "0TMQDKBB", "0TMQDKB "])
def test_a_body_of_the_wrong_length_is_refused(body):
    with pytest.raises(StampError, match="characters"):
        decode(body)


@pytest.mark.parametrize("text", ["0TMQDKB-T", "0TMQDKB-Tyz", "0TMQDKB-T1", "0TMQDKB-"])
def test_a_malformed_type_is_refused(text):
    with pytest.raises(StampError, match="not a type"):
        parse(text)


def test_a_naive_datetime_is_refused():
    """Assuming UTC is wrong by hours and looks entirely ordinary when it is."""
    with pytest.raises(StampError, match="naive"):
        encode(datetime(2026, 9, 9, 14, 38, 35))


@pytest.mark.parametrize("year", [1999, 3024])
def test_a_year_outside_the_range_is_refused(year):
    with pytest.raises(StampError, match="representable range"):
        encode(moment(year, 6, 1))


# -- parsing a stamp given on its own -----------------------------------------


def test_the_three_spellings_a_person_has_in_hand_all_parse():
    when = decode("0TMQDKB")
    for text in ("[0TMQDKB-Ty]", "0TMQDKB-Ty", "0TMQDKB"):
        assert parse(text).moment == when


def test_a_bare_body_carries_no_type():
    assert parse("0TMQDKB").type_code is None
    assert parse("[0TMQDKB-Ty]").type_code == "Ty"


def test_a_stamp_is_matched_case_insensitively():
    assert parse("[0tmqdkb-ty]").moment == parse("[0TMQDKB-Ty]").moment
    assert parse("[0tmqdkb-ty]").canonical == "[0TMQDKB-Ty]"


def test_a_parsed_stamp_keeps_the_text_it_was_given():
    """The raw text, not the canonical form: a report quotes what is written."""
    stamp = parse("[0tmqdkb-ty]")
    assert stamp.text == "[0tmqdkb-ty]"
    assert stamp.canonical == "[0TMQDKB-Ty]"


def test_a_stamp_does_not_change():
    with pytest.raises(dataclasses.FrozenInstanceError):
        parse("[0TMQDKB-Ty]").moment = moment(2026)


# -- finding stamps in a line -------------------------------------------------


def test_a_stamp_is_found_with_its_position():
    """Position is recorded now because associating a stamp with the citation it
    annotates is not built yet, and recovering the span afterward means matching
    the text a second time against the line."""
    line = "The registry contract is `docs/design.md` [0TMQDKB-Ty]."
    (stamp,) = find(line)
    assert stamp.type_code == "Ty"
    assert line[slice(*stamp.span)] == "[0TMQDKB-Ty]"


def test_several_stamps_come_back_in_order():
    line = "[0TMQDKB-Ty] then [0TMQDKC-Zz]"
    assert [s.canonical for s in find(line)] == ["[0TMQDKB-Ty]", "[0TMQDKC-Zz]"]
    assert [s.span for s in find(line)] == [(0, 12), (18, 30)]


def test_ordinary_bracketed_prose_of_the_same_shape_is_passed_over():
    """`[outline-Ab]` is seven letters, a hyphen and two more.

    The character class is the alphabet rather than "any alphanumeric" so that
    prose like this never enters the decoder. A loud wrong refusal on a document
    that has nothing to do with stamps is worse than missing a stamp mistyped
    into a letter Crockford omits.
    """
    assert find("see [outline-Ab] and [the design](docs/design.md)") == []


def test_a_token_of_the_declared_shape_that_does_not_decode_is_refused():
    """Inside brackets the shape is unambiguous, which is what the delimiters
    were chosen to buy -- so this is an error in the document, not something to
    walk past."""
    with pytest.raises(StampError, match="malformed"):
        find("written at [0ZZZZZZ-Ty], allegedly")


def test_find_returns_stamps():
    (stamp,) = find("[0TMQDKB-Ty]")
    assert isinstance(stamp, Stamp)
    assert stamp.moment.tzinfo is not None


# -- the reference key --------------------------------------------------------


def test_a_type_alone_still_parses_and_names_no_entry():
    """The number binds a citation to a bibliography entry, and a citation may
    be dated and typed without being bound. Every stamp written before keys
    existed is of this shape, so this is the case that must not break."""
    stamp = parse("[0TMQDKB-Pa]")
    assert stamp.type_code == "Pa"
    assert stamp.key is None


def test_a_keyed_stamp_carries_type_and_number_together():
    """Type *and* number, because digits are unique only within a type."""
    stamp = parse("[0TMQDKB-Ru0169]")
    assert stamp.type_code == "Ru"
    assert stamp.key == "Ru0169"
    assert stamp.canonical == "[0TMQDKB-Ru0169]"


def test_two_types_may_carry_the_same_number():
    assert reference_key("Ru0169") != reference_key("De0169")


def test_a_key_is_matched_case_insensitively_and_written_one_way():
    assert parse("[0tmqdkb-ru0169]").key == "ru0169"
    assert parse("[0tmqdkb-ru0169]").canonical == "[0TMQDKB-Ru0169]"
    assert canonical_key("rU0169") == "Ru0169"


def test_a_key_is_found_in_a_line_with_its_position():
    line = "The registry contract is [0TMQDKB-Pa0003]."
    (stamp,) = find(line)
    assert stamp.key == "Pa0003"
    assert line[slice(*stamp.span)] == "[0TMQDKB-Pa0003]"


@pytest.mark.parametrize("digits", ["169", "01690", "1"])
def test_a_number_of_the_wrong_width_is_refused_not_padded(digits):
    """``Ru169`` and ``Ru0169`` would be two spellings of one fact, which is the
    re-derivation this project exists to catch."""
    with pytest.raises(StampError, match="zero-padded"):
        parse(f"[0TMQDKB-Ru{digits}]")


def test_a_wrong_width_key_in_prose_is_refused_rather_than_passed_over():
    """Matched loosely and refused loudly.

    Pinning the digit count in the pattern would make this token match nothing
    at all, and a token nothing matches is a stamp the extractor walks past --
    a check that quietly stopped checking, which is worse than no check.
    """
    with pytest.raises(StampError, match="zero-padded"):
        find("the ruling is [0TMQDKB-Ru169], allegedly")


def test_a_bare_type_is_not_a_reference_key():
    """A bibliography entry *is* the binding, so a key with no number declares
    nothing that could be cited."""
    with pytest.raises(StampError, match="names a type but no entry"):
        reference_key("Ru")


def test_a_key_that_is_not_a_key_at_all_is_refused():
    with pytest.raises(StampError, match="not a reference key"):
        reference_key("ruling-169")
