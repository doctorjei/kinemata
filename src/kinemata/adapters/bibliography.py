"""Where a cited source actually lives, declared once.

A citation stamp answers *when*. It does not answer *what*, and a citation that
spells its target inline carries a fact that belongs in one declared place. The
reference key supplies the second answer and this registry supplies the third::

    The registry contract is `docs/design.md` [0TMQDKB-Pa0003].

    the stamp   when this was verified   inline
    the key     which source             inline
    the entry   where the source is      here, once

The inline text carries only the two invariants. The volatile half -- which
repository, which address, which path -- is declared once and edited once when
it moves. **This closes the gap a commit hash leaves**: a hash is immutable
*content* identity and says nothing about *place*, so a hash cited from another
project is a valid coordinate in a tree the checker was never pointed at.

**A key is local to the project that declares it**, the way reference 12 in one
paper is that paper's number for another's work rather than a number both must
agree on forever. So a key is only ever resolved against its own bibliography,
and collision between projects stops being a category of problem. Global
uniqueness across trees would need either a shared type vocabulary or a project
prefix inside the token, and neither earns its cost.

**Numbers are chosen, not minted.** Any unused number is a valid number, and the
tool's job here is refusal rather than assignment: a duplicate key is a finding,
and a citation naming a key that does not exist is a finding. Both are
mechanically catchable, which is the property that matters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from .. import stamps
from ..contract import BaseRegistry, Entry
from ..prose import outside_fenced_blocks

#: Codes the tool interprets, where behavior depends on the code meaning what it
#: says. **A project redefining one of these is refused at load**, because
#: reinterpreting it would make a check silently answer a different question
#: while still reporting.
#:
#: Read-only rather than a plain dict: this is a shared convention, and a
#: caller mutating it in place would change what every registry in the process
#: considers reserved. Extend it per project through ``interpreted=``, which
#: adds and never replaces.
INTERPRETED: Mapping[str, str] = MappingProxyType({
    "Wb": "web address",
    "Pa": "path in this tree",
    "Cm": "commit",
})

#: Common source types, reserved even though the tool never reads them. The
#: value of a shorthand is that it reads without explanation -- the same
#: argument that chose square brackets over every other delimiter -- so a
#: project inventing its own private code for a book or a specification throws
#: away the only thing a shared notation offers.
#:
#: **A conflicting project use is a warning, not a refusal.** Refusing would
#: enforce a convention the tool cannot act on, and the only cost of divergence
#: is legibility across projects. That is the reminder-and-catch distinction
#: applied to the vocabulary itself.
STANDARDIZED: Mapping[str, str] = MappingProxyType({
    "Dc": "document",
    "Sp": "specification or standard",
    "Ru": "ruling",
    "Is": "issue",
    "Pr": "change request",
    "Rp": "repository",
    "Bk": "book",
    "Ar": "article or paper",
})

#: What an entry may say. Anything else is refused rather than ignored, for the
#: reason a promise's keys are: ``not`` written for ``note`` would drop the
#: human-readable half in silence and leave an entry that resolves to a bare
#: path, which is the readable form the forward direction exists to give back.
ENTRY_KEYS = frozenset({"key", "target", "note", "foreign"})


def _code(text: Any, where: str) -> str:
    """One type code, canonically spelled, or a refusal naming ``where``."""
    code = str(text)
    if len(code) != stamps.TYPE_LENGTH or not code.isalpha() or not code.isascii():
        raise ValueError(
            f"{where}: {code!r} is not a type code -- exactly "
            f"{stamps.TYPE_LENGTH} letters, matched case-insensitively"
        )
    return stamps.canonical_key(code)


class Bibliography(BaseRegistry):
    """Entries drawn from declared ``key`` / ``target`` / ``note`` records.

    :param records: one mapping per entry.
    :param name: registry name, used in reports.
    :param home: where these entries are declared, repo-relative. Carried onto
        every entry so that :func:`~kinemata.bypass.unused` can tell a citation
        from the declaration itself.
    :param types: type codes this project defines, beyond the reserved core.
    :param interpreted: codes reserved as *interpreted* beyond the built-in
        core, added and never replacing.
    :param standardized: the same for the standardized core.
    :param closed: is a citation naming an undeclared key an error? See
        :meth:`candidates` -- a bibliography can answer that where most
        registries cannot.

    **Refuses rather than loading partially.** A malformed key, a duplicate, an
    entry whose type nothing declares, or a source that yielded no entries at
    all all raise here. A bibliography that loads empty resolves every key to
    nothing while `ids` prints a clean heading, which is the inert signal this
    package exists to refuse.
    """

    name = "bibliography"

    #: Everything a document *says*, prose included, minus what it *shows*. A
    #: citation is written in prose and a stamp inside an inline code span or a
    #: docstring is still a citation, so the filters that make a value registry
    #: precise would make this one blind -- which is why this was ``raw`` for
    #: the life of the project.
    #:
    #: It stopped being right at the fence. ``docs/citations.md`` has to spell a
    #: whole reference key to show the reader what one looks like, and that
    #: example was the only finding the closed-world citation catch had: true as
    #: stated, wrong in substance, and unfixable except by inventing a
    #: bibliography entry for a source that does not exist. See
    #: :func:`~kinemata.prose.outside_fenced_blocks` for what a fence is taken
    #: to mean and what that costs.
    #:
    #: Live rather than decorative: :func:`~kinemata.bypass.strays` reads it
    #: before asking :meth:`candidates` what is cited.
    match_mode = "unfenced"

    #: Documents, not code, and declared here rather than left to the project's
    #: list. The project default is ``.py``; a bibliography pointed at it would
    #: find no citations anywhere and report every entry unused -- blind, and
    #: reading exactly like a clean tree. A project that cites from source
    #: overrides this in its ``[[registry]]``.
    suffixes: tuple[str, ...] | None = (".md",)

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        name: str = "sources",
        home: str = "",
        types: Mapping[str, Any] | None = None,
        interpreted: Mapping[str, Any] | None = None,
        standardized: Mapping[str, Any] | None = None,
        closed: bool = False,
    ) -> None:
        self.name = name
        self.closed = closed
        self._home = home

        #: Standardized-code conflicts, and anything else worth saying without
        #: refusing. Collected rather than printed, so the one place that loads
        #: configuration decides where a warning goes.
        self.notices: tuple[str, ...] = ()

        self.interpreted = self._extend(INTERPRETED, interpreted, "interpreted")
        self.standardized = self._extend(STANDARDIZED, standardized,
                                         "standardized")
        self.types = self._project_types(types)
        self._entries = self._read(records)

    # -- the vocabulary ----------------------------------------------------

    def _extend(
        self, core: Mapping[str, str], extra: Mapping[str, Any] | None, tier: str
    ) -> dict[str, str]:
        """The built-in tier plus whatever this project reserves on top of it.

        **The extension point is the point.** A closed built-in set with no way
        to add to it is a defect this project has already shipped: the document
        suffix set was closed, and it left an adopting project blind to the only
        two content files one of its repositories had while the scan came back
        looking nearly green. The same shape of fix applies here.

        Adding is all it does. A code already in either core is refused, because
        redeclaring a reserved code through the extension point is the same
        redefinition the tiers exist to govern, arrived at by another road.
        """
        if extra is not None and not isinstance(extra, Mapping):
            raise ValueError(
                f"registry {self.name!r}: reserved {tier} codes are a table of "
                f"code = meaning, not {type(extra).__name__}"
            )
        merged = dict(core)
        for raw, meaning in (extra or {}).items():
            code = _code(raw, f"registry {self.name!r}: reserved {tier}")
            if code in INTERPRETED or code in STANDARDIZED:
                raise ValueError(
                    f"registry {self.name!r}: {code} is already reserved "
                    f"({INTERPRETED.get(code) or STANDARDIZED[code]}). The "
                    f"reserved core grows by explicit decision, and reserving "
                    f"it again here would redefine it rather than add to it."
                )
            merged[code] = str(meaning)
        return merged

    def _project_types(self, types: Mapping[str, Any] | None) -> dict[str, str]:
        """Codes this project defines, checked against the reserved core.

        A reserved code is declared already, so naming one here is a
        redefinition whichever meaning is written beside it: two prose
        descriptions cannot be compared for agreement, and treating a matching
        string as agreement would make the check turn on punctuation.

        The two tiers part company here, which is the whole reason for tiering
        them. An interpreted code is refused, because a check whose behavior
        depends on ``Pa`` meaning a path would silently answer a different
        question. A standardized code is a notice, because the tool never reads
        it and the only cost of divergence is legibility across projects.
        """
        if types is not None and not isinstance(types, Mapping):
            raise ValueError(
                f"registry {self.name!r}: [types] is a table of code = meaning, "
                f"not {type(types).__name__}"
            )
        declared: dict[str, str] = {}
        notices = list(self.notices)
        for raw, meaning in (types or {}).items():
            code = _code(raw, f"registry {self.name!r}: type")
            if code in self.interpreted:
                raise ValueError(
                    f"registry {self.name!r}: {code} is reserved for "
                    f"{self.interpreted[code]!r}, and this tool acts on that "
                    f"meaning. Redefining it as {str(meaning)!r} would leave a "
                    "check answering a different question than it reports. "
                    "Choose another code."
                )
            if code in self.standardized:
                notices.append(
                    f"registry {self.name!r}: {code} is standardized for "
                    f"{self.standardized[code]!r} and this project defines it "
                    f"as {str(meaning)!r}. Nothing here reads the code, so this "
                    "is legibility across projects rather than a broken check."
                )
            declared[code] = str(meaning)
        self.notices = tuple(notices)
        return declared

    def declares(self, code: str) -> bool:
        """Is this type code declared -- reserved implicitly, or by the project?"""
        return code in self.interpreted or code in self.standardized \
            or code in self.types

    # -- the entries -------------------------------------------------------

    def _read(self, records: Sequence[Mapping[str, Any]]) -> list[Entry]:
        seen: dict[str, str] = {}
        built: list[Entry] = []
        for index, record in enumerate(records):
            built.append(self._entry(record, index, seen))
        if not built:
            raise ValueError(
                f"registry {self.name!r}: the bibliography declares no entries, "
                "so every key in this project would resolve to nothing while "
                "the registry still reports as configured."
            )
        return built

    def _entry(
        self, record: Any, index: int, seen: dict[str, str]
    ) -> Entry:
        where = f"registry {self.name!r}: entry {index}"
        if not isinstance(record, Mapping):
            raise ValueError(
                f"{where} is not a table. An entry declares `key`, `target` "
                "and `note`."
            )
        unknown = set(record) - ENTRY_KEYS
        if unknown:
            raise ValueError(
                f"{where} ({record.get('key', '?')}) declares "
                f"{', '.join(sorted(unknown))}, which means nothing here "
                f"(known: {', '.join(sorted(ENTRY_KEYS))})."
            )
        missing = [field for field in ("key", "target", "note")
                   if not record.get(field)]
        if missing:
            raise ValueError(
                f"{where} ({record.get('key', '?')}) is missing "
                f"{', '.join(missing)}. An entry needs the key, what it points "
                "at, and a note a reader can understand without resolving it."
            )
        try:
            key = stamps.reference_key(str(record["key"]))
        except stamps.StampError as exc:
            raise ValueError(f"{where}: {exc}") from exc

        code = key[:stamps.TYPE_LENGTH]
        if not self.declares(code):
            raise ValueError(
                f"{where} ({key}) names type {code}, which nothing declares. "
                "Reserved codes are declared implicitly and a project's own go "
                "in the bibliography's [types] table -- so an undeclared code "
                "is a typo rather than a silent pass."
            )
        if key in seen:
            raise ValueError(
                f"{where}: {key} is already declared as {seen[key]!r}. Digits "
                "are unique within a type, so this is one key with two sources "
                "rather than two keys."
            )
        seen[key] = str(record["target"])

        extra = {
            "type": code,
            "target": str(record["target"]),
            "note": str(record["note"]),
        }
        if record.get("foreign"):
            extra["foreign"] = str(record["foreign"])
        return Entry(
            id=key,
            extra=extra,
            # No antipatterns, deliberately. An entry's target spelled out in
            # prose is not a bypass: section 5.6 says a citation *accompanies*
            # its target by default, so the second spelling is the readable half
            # of a declared citation rather than a re-derivation of it.
            home=(self._home,) if self._home else (),
        )

    def entries(self) -> Iterable[Entry]:
        return list(self._entries)

    def line(self, entry: Entry) -> str:
        return f"{entry.id}  {entry.extra['target']}"

    # -- matching ----------------------------------------------------------

    def _cited(self, text: str) -> Iterable[str]:
        """Every key cited in ``text``, canonically spelled.

        Read as *stamps* rather than as bare names, which the default matcher
        cannot do. A sentence mentioning ``Pa0003`` in passing has not cited
        anything; the token ``[0TMQDKB-Pa0003]`` has. Routing through
        :func:`kinemata.stamps.find` also means a malformed token is refused
        here exactly as it is everywhere else, instead of being passed over by a
        matcher that never saw it.

        **What a document shows never arrives here, but not by one route.** A
        fence is a property of a whole document and this reads one line at a
        time, so the blanking has to happen before the split -- and the two
        callers reach it differently. :meth:`candidates` is asked line by line
        by :func:`~kinemata.bypass.strays`, which applies the ``unfenced`` mode
        to the file first. :meth:`detect` is handed a whole file by
        :func:`~kinemata.bypass.unused`, which consults no mode at all, so it
        blanks the text itself.

        This paragraph previously claimed the mode covered both. It did not, and
        nothing caught the difference until the two directions disagreed out
        loud on 2026-09-10.
        """
        for line in text.splitlines():
            for stamp in stamps.find(line):
                if stamp.key is not None:
                    yield stamps.canonical_key(stamp.key)

    def detect(self, text: str) -> list[str]:
        """Declared keys cited here. Overridden because the default is wrong twice.

        It looks for a bare identifier, so a key named in prose would count as a
        citation; and its boundary class treats the hyphen as part of a name, so
        the separator immediately before a key would stop the match dead and
        every entry would report as uncited.

        **Fences are blanked here, not left to the caller.** This method has one
        caller -- :func:`~kinemata.bypass.unused` -- and it reads whole files
        without consulting ``match_mode``, so a registry that relied on the mode
        alone would answer one question for the catch and a different one for the
        review list. It did, on 2026-09-10: ``undeclared`` and ``cite`` both
        reported this project as citing nothing while ``unused`` still counted an
        illustration inside a fenced block as a mention.

        The mode is not the place to fix that generally. ``match_mode`` governs
        where an *antipattern* counts -- a re-derived value, which lives in a
        string literal -- while this asks where the *identifier* is mentioned,
        which for a value registry lives in code. Teaching ``unused`` to apply
        the mode would blank the code and report every declared constant as
        unmentioned; measured on a constants registry, ``detect`` goes from
        finding its entry to finding nothing. The two coincide only for a
        registry whose identifiers are themselves what appears in prose, which is
        this one.
        """
        seen: dict[str, None] = {}
        for key in self._cited(outside_fenced_blocks(text)):
            if key in self._index:
                seen.setdefault(key, None)
        return list(seen)

    def candidates(self, text: str) -> list[str]:
        """Every key *cited* here, declared or not.

        A bibliography can answer this where most registries cannot, because a
        cited key is unmistakable: it lives inside a stamp token, and making
        that token unambiguous is exactly what the delimiters were chosen for.
        That is what lets a bibliography be declared ``closed``, which turns
        section 5.3's second catchable failure -- a citation naming a key no
        entry declares -- into the closed-world catch that already exists.
        """
        seen: dict[str, None] = {}
        for key in self._cited(text):
            seen.setdefault(key, None)
        return list(seen)


def undeclared_key(key: str) -> str:
    """What to say about a citation naming a key no entry declares.

    Section 5.3 makes this one of the two failures the scheme exists to catch,
    so more than one command has to say it -- resolving a key by hand, and
    deciding whether a citation is one to date. Written once here, in the module
    that owns what a key is, because two commands wording the same refusal
    differently is how a reader comes to think they are two different problems.
    """
    return (
        f"no entry declares {key}. Numbers are chosen rather than minted, so "
        "any unused one is valid -- but a key nothing declares is a typo or a "
        "citation into a bibliography this project does not have."
    )


def duplicate_keys(registries: Iterable[BaseRegistry]) -> list[str]:
    """Keys declared by more than one bibliography, with where they collide.

    **The key space is project-wide, not per file.** A project may keep more
    than one bibliography -- one for its own tree and one for the standards it
    cites -- and a key resolving to two different sources depending on which
    file was read last is exactly the ambiguity the scheme exists to remove. Each
    registry refuses its own duplicates as it loads; only something holding all
    of them can see this one.
    """
    homes: dict[str, list[str]] = {}
    for registry in registries:
        if not isinstance(registry, Bibliography):
            continue
        for entry in registry.entries():
            homes.setdefault(entry.id, []).append(registry.name)
    return [
        f"{key} is declared by {' and '.join(names)}"
        for key, names in sorted(homes.items())
        if len(names) > 1
    ]
