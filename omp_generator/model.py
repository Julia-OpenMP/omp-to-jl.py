"""Normalized, language-neutral model of the OpenMP directive/clause/modifier syntax.

The loader (:mod:`omp_generator.spec`) turns the raw JSON of the OpenMP specification
sources into these dataclasses; emitters (e.g. :mod:`omp_generator.julia`) only ever see
this model. Only *structural* facts are kept (names, types, properties, cross references):
no prose from the specification is carried over.

Naming conventions
------------------
``name``      unique identifier of an entity in the specification, e.g. ``ordered-blockassoc``
              or ``update-depend_objects`` (the JSON ``$name``).
``spelling``  what a user writes in a directive, e.g. ``ordered`` or ``update`` (the JSON
              ``$clean_name`` when present, with spaces replaced by underscores).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Kinds of syntactic elements (argument, modifier value, list item). This is a closed set:
# any OpenMP type that is not recognized becomes STYLIZED, with the precise OpenMP type kept
# in ``Argument.type`` so that front-ends can specialize on it.
KEYWORD = "keyword"  # one keyword out of ``values``
COMPLEX = "complex"  # keyword(arguments...)
LIST = "list"  # comma-separated list of ``items``
LIST_ITEM = "list_item"  # a list item of some kind (variable, locator, ...): see ``type``
EXPRESSION = "expression"  # a base-language expression of OpenMP type ``type``
VARIABLE = "variable"  # a base-language variable
IDENTIFIER = "identifier"  # a base-language / OpenMP identifier
DIRECTIVE_NAME = "directive_name"  # the name of a directive
DIRECTIVE_SPECIFICATION = "directive_specification"  # a nested directive (metadirectives)
TYPE_NAME = "type_name"  # a base-language type
STYLIZED = "stylized"  # an OpenMP stylized expression / specifier: see ``type``

KINDS = (
    KEYWORD,
    COMPLEX,
    LIST,
    LIST_ITEM,
    EXPRESSION,
    VARIABLE,
    IDENTIFIER,
    DIRECTIVE_NAME,
    DIRECTIVE_SPECIFICATION,
    TYPE_NAME,
    STYLIZED,
)


@dataclass(frozen=True)
class Argument:
    """Syntax of an argument (of a directive, clause or complex modifier), of a modifier
    value, or of a list item."""

    name: str
    kind: str
    type: str = ""  # OpenMP type, e.g. "OpenMP logical", "locator list item", "integer"
    keyword: Optional[str] = None  # keyword of a COMPLEX, or keyword category of a KEYWORD
    values: Tuple[str, ...] = ()  # KEYWORD: accepted keywords; COMPLEX: alternative keywords
    items: Optional["Argument"] = None  # LIST: syntax of each item
    arguments: Tuple["Argument", ...] = ()  # COMPLEX: arguments
    properties: Tuple[str, ...] = ()

    def __post_init__(self):
        assert self.kind in KINDS, self.kind


@dataclass(frozen=True)
class Modifier:
    name: str
    value: Argument  # syntax of the modifier itself
    modifying: Tuple[str, ...] = ()  # names of the modified arguments; () means all
    properties: Tuple[str, ...] = ()
    reference: Optional[str] = None  # name of the global modifier this one refers to


@dataclass(frozen=True)
class MemberSet:
    """A clause-set (members are clause names) or a modifier-set (modifier names)."""

    name: str
    members: Tuple[str, ...]
    properties: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Clause:
    name: str
    spelling: str
    arguments: Tuple[Argument, ...]
    modifiers: Tuple[Modifier, ...]
    modifier_sets: Tuple[MemberSet, ...]
    directives: Tuple[str, ...]
    properties: Tuple[str, ...]


@dataclass(frozen=True)
class ClauseGroup:
    name: str
    clauses: Tuple[str, ...]
    directives: Tuple[str, ...]
    properties: Tuple[str, ...]
    arguments: Tuple[Argument, ...] = ()
    modifiers: Tuple[Modifier, ...] = ()
    # When set, the members of the group are not clauses but the names of the directives
    # that have this property (e.g. the cancel-directive-name group of `cancel`).
    member_property: Optional[str] = None


@dataclass(frozen=True)
class ModifierGroup:
    name: str
    modifiers: Tuple[str, ...]
    clauses: Tuple[str, ...]
    properties: Tuple[str, ...]


@dataclass(frozen=True)
class Directive:
    name: str
    spelling: str
    category: str
    association: str
    association_properties: Tuple[str, ...]
    arguments: Tuple[Argument, ...]
    clauses: Tuple[str, ...]
    clause_groups: Tuple[str, ...]
    clause_sets: Tuple[MemberSet, ...]
    properties: Tuple[str, ...]
    language: str  # "any", or the spec's language restriction ("ccpp", "fortran", ...)
    separating: Tuple[str, ...] = ()
    separated: Tuple[str, ...] = ()
    subsidiary: Tuple[str, ...] = ()
    enclosing: Tuple[str, ...] = ()


@dataclass
class Spec:
    version: str
    revision: Optional[str]
    directives: Dict[str, Directive] = field(default_factory=dict)
    clauses: Dict[str, Clause] = field(default_factory=dict)
    clause_groups: Dict[str, ClauseGroup] = field(default_factory=dict)
    modifiers: Dict[str, Modifier] = field(default_factory=dict)
    modifier_groups: Dict[str, ModifierGroup] = field(default_factory=dict)
    # compound directives, as sequences of leaf directive names (outermost first)
    compound_directives: List[Tuple[str, ...]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
