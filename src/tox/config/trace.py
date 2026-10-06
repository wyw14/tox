"""Read-only tracing of configuration reference resolution.

Used by ``tox config --explain`` to record, without affecting resolution, which references a value uses, where each
one resolves, and which chain was active when a circular or missing reference failed. Secret-looking variable names
never carry their resolved content: only the name and whether it was provided are recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tox.util.redact import is_secret_name

if TYPE_CHECKING:
    from collections.abc import Sequence

# reference kinds that are substitutions (``{env:...}`` etc.); everything else is a cross-section config reference
SUBSTITUTION_KINDS: frozenset[str] = frozenset({"env", "tty", "posargs", "glob", "factor", "path", "pathsep"})


@dataclass
class TraceEvent:
    """One reference encountered while materializing a configuration value.

    :param expression: the reference as written (``{env:X}``, ``{[section]key}``) or the TOML replacement shape
    :param kind: ``env``, ``ref``, ``if``, ``factor``, ``posargs``, ``glob``, ``tty``, ``path``, ``pathsep``
    :param depth: nesting depth (a reference resolved through another reference is deeper)
    :param name: the referenced variable/factor name, when applicable
    :param target: the referenced configuration key (``section.key`` or ``env.key``), when applicable
    :param chain: snapshot of the configuration resolution chain active for this event
    :param resolved: the value the reference resolved to (never populated for secret names)
    :param error: ``repr()`` of the original error raised while resolving the reference, when any
    :param default: the default text the reference falls back to, when given
    :param missing: whether the referenced variable/key was not provided
    :param provided: for environment variables, whether a value was provided (via set_env or the OS environment)
    :param secret: whether the name is secret-looking, in which case ``resolved`` stays empty
    :param matched: for conditional (``if``/factor) references, whether the condition matched
    :param condition: the raw condition expression of a conditional reference

    """

    expression: str
    kind: str
    depth: int
    name: str | None = None
    target: str | None = None
    chain: list[str] = field(default_factory=list)
    resolved: str | None = None
    error: str | None = None
    default: str | None = None
    missing: bool = False
    provided: bool | None = None
    secret: bool = False
    matched: bool | None = None
    condition: str | None = None


class ConfigTrace:
    """Collect reference resolution events for one configuration value materialization."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._stack: list[TraceEvent] = []

    def event(
        self,
        expression: str,
        *,
        kind: str,
        name: str | None = None,
        chain: Sequence[str] = (),
    ) -> TraceEvent:
        """Open a new reference event and append it to the trace.

        The event depth is the number of references currently being resolved (its parent chain), so data-structure
        nesting (a replacement inside a list) does not indent a reference deeper.

        """
        result = TraceEvent(
            expression=expression,
            kind=kind,
            depth=len(self._stack),
            name=name,
            chain=list(chain),
            secret=is_secret_name(name) if name is not None else False,
        )
        self.events.append(result)
        return result

    def push(self, event: TraceEvent) -> None:
        """Mark ``event`` as the reference currently being resolved (annotations target it)."""
        self._stack.append(event)

    def pop(self, event: TraceEvent) -> None:
        """Close a reference opened with :meth:`push` (nested references may be above it on the stack)."""
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] is event:
                del self._stack[index]
                return

    def annotate(self, **values: object) -> None:
        """Attach details (target, provided flag, ...) to the reference currently being resolved."""
        if self._stack:
            for key, value in values.items():
                setattr(self._stack[-1], key, value)

    def failure_chain(self) -> list[str]:
        """:returns: the chain snapshot of the deepest event that errored, or an empty list"""
        failures = [event for event in self.events if event.error is not None]
        return failures[-1].chain.copy() if failures else []


__all__ = (
    "ConfigTrace",
    "TraceEvent",
)
