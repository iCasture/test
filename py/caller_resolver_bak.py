"""
Utilities for resolving the true caller module in the call stack.

This module provides functionality to walk up the call stack and identify
the first external module that is not part of a specified internal prefix list.
This is useful in logging frameworks or utility libraries that want to
attribute actions to user code rather than internal helpers.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .missing_mark import MISSING, MissingMark

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Final


# - - - - - - - - - - - - - - - - - -


# Define the list of publicly exportable members of the module
__all__: Final[list[str]] = [
    "aaa",
    "bbb",
]


# - - - - - - - - - - - - - - - - - -


def aaa(
    stack_start: int = 1,
    max_stack_depth: int | None = None,
    excluded_prefixes: str | Sequence[str] | None = None,
    *,
    fallback_to_current: bool = True,
) -> str | MissingMark:
    """
    Resolve the name of the most external caller's module, skipping excluded modules.

    This function inspects the call stack and returns the name of the first module
    that does not start with any of the provided prefix(es). It is useful for identifying
    the originating module in user code, especially within utility wrappers or logging.

    Parameters
    ----------
    stack_start : int, optional
        Number of initial frames to skip from the beginning of the stack. This can be used
        to ignore the utility wrappers themselves. Defaults to `1` (skip this resolver function).
        Common values include:
          - `0`: No frames skipped, includes the current function.
          - `1`: Skips this resolver function (use if called directly).
          - `2`: Skips both this function and its immediate caller (use if called via a wrapper).

    max_stack_depth : int, optional
        The maximum number of frames to inspect starting from `stack_start`.
        Limits traversal depth to avoid performance degradation in deep call stacks.
        If `None` (default), no limit is applied.

    excluded_prefixes : str or sequence of str, optional
        A string prefix or a list/tuple of prefixes. Modules whose `__name__` starts with
        any of these prefixes will be skipped.
        If `None` (the default), no modules will be excluded.

    fallback_to_current : bool, optional
        Whether to fall back to the current module's `__name__` if no suitable external
        caller is found. Defaults to `True`.

    Returns
    -------
    str or MissingMark
        The module name of the most external caller that is not excluded.
        If no suitable caller is found:
        - Returns the current module's `__name__` if `fallback_to_current` is `True`
        - Returns `MISSING` sentinel if `fallback_to_current` is `False`

    Notes
    -----
    - The `stack_start` parameter allows precise control over which frames to skip,
      especially when utility functions or decorators wrap the actual user call site.
      Adjusting this helps identify the true caller module in user code.

    - This implementation uses `inspect.currentframe()` and traverses frames via `.f_back`
      rather than building full `inspect.FrameInfo` objects. This avoids object creation
      overhead and reduces memory pressure.

      Traversal cost is proportional to the depth (`O(depth)`) rather than to the total
      number of frames with additional allocations.
    """
    # Normalize excluded prefixes to a tuple to allow consistent startswith() checks
    # This ensures we can uniformly call startswith() on all exclusions
    if excluded_prefixes is None:
        prefix_tuple: tuple[str, ...] = ()
    elif isinstance(excluded_prefixes, str):
        prefix_tuple = (excluded_prefixes,)
    else:
        prefix_tuple = tuple(excluded_prefixes)

    frame = inspect.currentframe()

    try:
        # Skip the first `stack_start` frames to bypass internal utility layers.
        # This is useful when the caller is wrapped in decorators or helper functions.
        for _ in range(stack_start):
            if frame is None:
                return __name__ if fallback_to_current else MISSING
            frame = frame.f_back

        # Counter to track how many frames we've inspected, used to enforce `max_stack_depth`.
        inspected = 0

        # Traverse up the call stack until we find a frame outside the excluded prefixes,
        # or until we hit the `max_stack_depth` limit.
        while frame and (max_stack_depth is None or inspected < max_stack_depth):
            module_name: str = frame.f_globals.get("__name__", "")

            # Skip frames whose module names match excluded prefixes.
            # 1. `module_name` may be empty for some frames (e.g., eval/exec), so we check for that too.
            # 2. If `prefix_tuple` is empty (`excluded_prefixes` is set to `None`),
            #    then all modules are eligible (return the first module found).
            if module_name and (
                not prefix_tuple or not module_name.startswith(prefix_tuple)
            ):
                return module_name

            frame = frame.f_back
            inspected += 1
    finally:
        # Break reference cycles ASAP to prevent memory leaks
        del frame

    # If no valid caller module is found, use fallback strategy
    return __name__ if fallback_to_current else MISSING


def bbb(
    stack_start: int = 0,
    exclude_patterns: set[str] | None = None,
    *,
    fallback_to_argv: bool = True,
    fallback_to_current: bool = True,
) -> str | MissingMark:
    """
    Resolve the filename of the calling script, skipping internal/excluded files.

    This function walks up the call stack to find the first external script file
    that doesn't match the exclusion patterns. It's particularly useful for logging
    frameworks that want to identify which user script triggered an action.

    Parameters
    ----------
    stack_start : int, optional
        Number of initial frames to skip from the beginning of the stack.
        Defaults to `0` (includes the current function).
        Common values:
          - `0`: No frames skipped, includes this function.
          - `1`: Skip this function (use if called directly).
          - `2`: Skip this function and its immediate caller.

    exclude_patterns : set of str, optional
        A set of patterns to exclude when looking for the caller.
        Files containing any of these patterns in their path will be skipped.
        Common patterns include:
          - Specific filenames (e.g., `"setup_venv.py"`)
          - Directory patterns (e.g., `"site-packages"`, `".venv"`)
          - Special markers (e.g., `"<frozen"`)
        If `None`, a default set of common internal patterns will be used.

    fallback_to_argv : bool, optional
        Whether to fall back to `sys.argv[0]` if no suitable caller is found
        in the stack. Defaults to `True`. Note that `sys.argv` may be unavailable
        in embedded Python interpreters or other special execution environments.

    fallback_to_current : bool, optional
        Whether to fall back to the current module's filename if no suitable caller
        is found in the stack and either `fallback_to_argv` is `False` or `sys.argv`
        is unavailable. Defaults to `True`.

    Returns
    -------
    # TODO: 确认行为
    str or MissingMark
        The base filename (e.g., `"main.py"`) of the calling script.
        If no suitable caller is found, tries fallbacks in order:
        1. The filename from `sys.argv[0]` if `fallback_to_argv` is `True` and `sys.argv` is available
        2. The current module's filename if `fallback_to_current` is `True`
        3. Returns `MISSING` sentinel if no fallback is available or enabled

    Notes
    -----
    - Unlike `resolve_caller_module`, this function returns filenames rather than
      module names, making it suitable for display in logs or error messages.

    - The function uses `inspect.stack()` which provides more detailed frame
      information compared to manual frame traversal, at the cost of slightly
      higher overhead.

    Examples
    --------
    >>> # Get the filename of the direct caller
    >>> filename = resolve_caller_filename1(stack_start=1)

    >>> # Custom exclusion patterns
    >>> filename = resolve_caller_filename1(
    ...     exclude_patterns={"my_framework/", "test_", "<stdin>"}
    ... )

    >>> # Disable all fallbacks to get MISSING when no caller is found
    >>> result = resolve_caller_filename1(
    ...     fallback_to_argv=False, fallback_to_current=False
    ... )
    >>> if result is MISSING:
    ...     print("Could not determine caller filename")
    """
    # Default exclusion patterns if none provided
    if exclude_patterns is None:
        exclude_patterns = {
            __file__,  # This file itself
            "logging/__init__.py",
            "<frozen importlib._bootstrap>",
            "<frozen importlib._bootstrap_external>",
            "importlib/__init__.py",
            "site-packages",
            "<stdin>",
            "<string>",
        }

    # Get the current stack frames, skipping the specified number
    try:
        stack = inspect.stack()[stack_start:]
    except Exception:  # noqa: BLE001
        # If stack inspection fails, try fallbacks
        if fallback_to_argv and sys.argv:
            return Path(sys.argv[0]).name
        if fallback_to_current:
            return Path(__file__).name
        return MISSING

    # Track files we've seen to avoid duplicates
    seen_files: set[str] = set()

    for frame_info in stack:
        caller_path = frame_info.filename

        # Skip if we've seen this file before
        if caller_path in seen_files:
            continue

        seen_files.add(caller_path)

        # Skip files matching exclusion patterns
        if any(pattern in caller_path for pattern in exclude_patterns):
            continue

        # Skip common internal Python locations
        if (
            "<" in caller_path  # Handles <frozen module> and similar
            or "venv" in caller_path.lower()
            or ".venv" in caller_path.lower()
            or "virtualenv" in caller_path.lower()
        ):
            continue

        # We found a suitable caller
        return Path(caller_path).name

    # Try fallbacks in order
    if fallback_to_argv and sys.argv:
        return Path(sys.argv[0]).name
    if fallback_to_current:
        return Path(__file__).name
    return MISSING
