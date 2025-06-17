"""
Custom logging filters for advanced log message filtering.

This module provides custom filters designed to enhance and customize Python's
built-in logging system. It includes specialized filters for controlling which
log messages are processed based on various criteria.

Features
--------
- `LevelRangeFilter`: A filter that allows log messages within a configurable level range
  with customizable inclusivity for both upper and lower bounds.

- `CallerInfoFilter`: A filter that injects the name of the calling script into log records.

Examples
--------
>>> from utils.logs.filters import LevelRangeFilter
>>> filter = LevelRangeFilter(min_level="INFO", max_level="WARNING")
>>> handler.addFilter(filter)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from utils.caller_resolver import resolve_caller_filename

from .logging_utils import convert_level_to_int

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Final


# - - - - - - - - - - - - - - - - - -


# Define the list of publicly exportable members of the module
__all__: Final[list[str]] = [
    "CallerInfoFilter",
    "LevelRangeFilter",
]


# - - - - - - - - - - - - - - - - - -

# Custom Filters


class LevelRangeFilter(logging.Filter):
    """
    A logging filter that allows messages within a specific level range.

    This filter accepts log records with levels between `min_level` and `max_level`.
    The inclusiveness of these bounds can be controlled.
    Levels can be specified as integers (e.g., `logging.INFO`, `20`) or as string names (e.g., `"INFO"`).

    Parameters
    ----------
    min_level : int or str or None, optional
        The lower bound of the log level range, default is `"INFO"`.
        Can be an integer log level or a string (e.g., `"DEBUG"`, `"INFO"`, `10`).
        If set to `None`, all log records are considered to have
        a level above this bound (no lower filtering is applied).
    max_level : int or str or None, optional
        The upper bound of the log level range, default is `"INFO"`.
        Can be an integer log level or a string (e.g., `"WARNING"`, `"ERROR"`, `30`).
        If set to `None`, all log records are considered to have
        a level below this bound (no upper filtering is applied).
    min_inclusive : bool, optional
        Whether the lower bound is inclusive. Default is `True`.
        If `True`, log records with a level equal to `min_level` are allowed.
        If `False`, only records with a level strictly greater than `min_level` are allowed.
    max_inclusive : bool, optional
        Whether the upper bound is inclusive. Default is `True`.
        If `True`, log records with a level equal to `max_level` are allowed.
        If `False`, only records with a level strictly less than `max_level` are allowed.
    name : str
        The name of the filter.
        Defaults to an empty string, meaning all events are allowed through.
        If specified, only log records from loggers whose name matches this filter's name
        (or starts with it, followed by a dot) will be allowed through this filter and its subclasses.

    Attributes
    ----------
    min_level : float
        The resolved numeric value for the minimum log level.
        Is `float('-inf')` if `min_level` was `None`.
    max_level : float
        The resolved numeric value for the maximum log level.
        Is `float('inf')` if `max_level` was `None`.

    Notes
    -----
    - If `min_level` is greater than `max_level`, no log records will be accepted (all records are filtered out).

    - If `min_level` is equal to `max_level`:

        If both `min_inclusive` and `max_inclusive` are `True`,
        then only log records with a level equal to that specific level will be accepted.

        If either `min_inclusive` or `max_inclusive` (or both) is `False`,
        then no records will be accepted in this specific equal-level case.

    - If both `min_level` and `max_level` are `None`, all log records will be accepted (no filtering).
    """

    def __init__(
        self,
        min_level: int | str | None = "INFO",
        max_level: int | str | None = "INFO",
        *,
        min_inclusive: bool = True,
        max_inclusive: bool = True,
        name: str = "",
    ) -> None:
        """
        Initialize the filter with a level range and inclusivity options.

        Parameters
        ----------
        min_level : int or str or None, optional
            The lower bound of the log level range. Default is `"INFO"`.
            See class Pparameters for details.
        max_level : int or str or None, optional
            The upper bound of the log level range. Default is `"INFO"`.
            See class Parameters for details.
        min_inclusive : bool, optional
            Whether the lower bound `min_level` is inclusive. Default is `True`.
        max_inclusive : bool, optional
            Whether the upper bound `max_level` is inclusive. Default is `True`.
        name : str, optional
            The name of the filter.
            If specified, only log records from loggers whose name matches this filter's name
            (or starts with it, followed by a dot) will be allowed through this filter and its subclasses.
            If set to an empty string, all events are allowed through.
        """
        super().__init__(name)

        # Resolve min_level and max_level to numeric values.
        # None is treated as an open bound.
        self.min_level: float = (
            convert_level_to_int(min_level) if min_level is not None else float("-inf")
        )
        self.max_level: float = (
            convert_level_to_int(max_level) if max_level is not None else float("inf")
        )

        # Set comparators based on inclusivity.
        # These functions will be called like: comparator(record_value)
        # e.g., self.min_level.__le__(record.levelno) means self.min_level <= record.levelno

        self._min_comparator: Callable[[int], bool]
        self._max_comparator: Callable[[int], bool]

        if min_inclusive:
            self._min_comparator = self.min_level.__le__
        else:
            self._min_comparator = self.min_level.__lt__

        if max_inclusive:
            self._max_comparator = self.max_level.__ge__
        else:
            self._max_comparator = self.max_level.__gt__

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log records based on their level within the configured range.

        Parameters
        ----------
        record : logging.LogRecord
            The log record to filter.

        Returns
        -------
        bool
            `True` if the record should be logged (i.e., its level is within the specified range), `False` otherwise.
        """
        if self.min_level > self.max_level:
            return False

        # Check against lower bound:
        # self._min_comparator(record.levelno) is equivalent to:
        #   self.min_level <= record.levelno (if min_inclusive)
        #   self.min_level < record.levelno  (if not min_inclusive)
        pass_min_check = self._min_comparator(record.levelno)

        # Check against upper bound:
        # self._max_comparator(record.levelno) is equivalent to:
        #   self.max_level >= record.levelno (if max_inclusive)
        #   self.max_level > record.levelno  (if not max_inclusive)
        pass_max_check = self._max_comparator(record.levelno)

        return pass_min_check and pass_max_check


class CallerInfoFilter(logging.Filter):
    """
    Logging filter that injects the name of the calling script into log records.

    This filter adds a `caller` attribute to log records, which can then be used
    in formatter strings via `%(caller)s`. It's particularly useful for identifying
    which script triggered logging output in multi-script applications.

    Parameters
    ----------
    attribute_name : str, optional
        The name of the attribute to add to the log record. Defaults to `"caller"`.
        This can be customized if there's a naming conflict with existing attributes.

    exclude_patterns : set of str, optional
        Additional patterns to exclude when looking for the caller.
        These are added to the default exclusion patterns.
        If you want to completely replace the default patterns, use
        `override_exclude_patterns` instead.

    override_exclude_patterns : set of str, optional
        If provided, completely replaces the default exclusion patterns.
        Use this when you want full control over what files are excluded.

    stack_offset : int, optional
        Additional frames to skip when searching for the caller.
        Defaults to `0`. Increase this if the filter is wrapped in
        additional layers of abstraction.

    fallback_to_argv : bool, optional
        Whether to fall back to `sys.argv[0]` if no suitable caller
        is found in the stack. Defaults to `True`.

    Attributes
    ----------
    record.<attribute_name> : str
        The base filename (e.g., `"main.py"`) of the script that generated
        the log message. Set to `"unknown"` if the caller cannot be determined.

    Examples
    --------
    Basic usage with default settings:

    >>> from utils.logkit.filters import CallerInfoFilter
    >>> logger = logging.getLogger(__name__)
    >>> handler = logging.StreamHandler()
    >>> handler.addFilter(CallerInfoFilter())
    >>> formatter = logging.Formatter("[ %(caller)s ] - %(message)s")
    >>> handler.setFormatter(formatter)
    >>> logger.addHandler(handler)

    Custom attribute name and exclusion patterns:

    >>> filter = CallerInfoFilter(
    ...     attribute_name="script_name", exclude_patterns={"test_", "conftest.py"}
    ... )
    >>> formatter = logging.Formatter("%(script_name)s: %(message)s")

    Notes
    -----
    - The filter automatically handles the additional stack frames introduced
      by the logging framework itself.

    - For performance reasons, the caller resolution is done on-demand for
      each log record. In high-throughput scenarios, consider whether the
      overhead is acceptable.
    """

    def __init__(
        self,
        attribute_name: str = "caller",
        exclude_patterns: set[str] | None = None,
        override_exclude_patterns: set[str] | None = None,
        stack_offset: int = 0,
        *,
        fallback_to_argv: bool = True,
    ) -> None:
        """Initialize the CallerInfoFilter."""
        super().__init__()
        self.attribute_name = attribute_name
        self.stack_offset = stack_offset
        self.fallback_to_argv = fallback_to_argv

        # Build the exclusion patterns
        if override_exclude_patterns is not None:
            self.exclude_patterns = override_exclude_patterns
        else:
            # Start with default patterns from resolve_caller_filename
            self.exclude_patterns = {
                "logging/__init__.py",
                "<frozen importlib._bootstrap>",
                "<frozen importlib._bootstrap_external>",
                "importlib/__init__.py",
                "site-packages",
                "<stdin>",
                "<string>",
            }
            # Add any additional patterns
            if exclude_patterns:
                self.exclude_patterns.update(exclude_patterns)

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add caller information to the log record.

        Parameters
        ----------
        record : logging.LogRecord
            The log record to enhance with caller information.

        Returns
        -------
        bool
            Always returns `True` to allow the record to be processed.
        """
        # The logging framework adds several frames to the stack,
        # so we need to skip past them to find the actual caller.
        # Typically we need to skip at least 8-10 frames to get past
        # the logging internals, but this can vary.
        caller = resolve_caller_filename(
            stack_start=8 + self.stack_offset,
            excluded_patterns=self.exclude_patterns,
            fallback_to_argv=self.fallback_to_argv,
        )

        setattr(record, self.attribute_name, caller)
        return True
