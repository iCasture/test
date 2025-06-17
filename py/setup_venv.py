# -*- coding: utf-8 -*-

"""
Automatically sets up the virtual environment upon import.

This module is intended to be imported at the very beginning of the main script,
before importing any packages that rely on the virtual environment.


Notes
-----
- This module does not use a `if __name__ == "__main__"` guard -- its setup logic
  runs automatically upon import.

- This module must be imported BEFORE any third-party packages that depend on the virtual
  environment are imported.

- Because this module is only imported for its side effects, linters such as Ruff may report
  an unused import, and type checkers like Pyright may issue warnings.
  To suppress these, append this comment after the import statement:
  `# noqa: F401  # pyright: ignore[reportUnusedImport]`.

Examples
--------
>>> import venv_manager.setup_venv  # noqa: F401  # pyright: ignore[reportUnusedImport]

See Also
--------
https://stackoverflow.com/questions/36827962/pep8-import-not-at-top-of-file-with-sys-path
"""

from __future__ import annotations

import os
import platform
import re
import runpy
import site
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

# 1. Avoid using relative imports like "from ..common.dt import xxx",
#    as mypy will fail to locate the module when run from the project root
#    (it only works when mypy is run from within the module's directory).
#
# 2. Instead, use absolute imports such as "from common.dt import xxx".
#    This allows mypy to be run from the project root.
#
# However, make sure the following tools are properly configured:
#
# - mypy:    'mypy_path = "$MYPY_CONFIG_FILE_DIR/src"'
#            'python_executable = "$MYPY_CONFIG_FILE_DIR/.venv/bin/python3"'
# - pyright: 'executionEnvironments = [ { root = "src" } ]'
# - pytest:  'addopts = [ "--import-mode=importlib" ]'
#            'pythonpath = "src"'
# - VSCode:  '"python.analysis.extraPaths": ["${workspaceFolder}/src"],'
#            '"python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python3",'
#            '"python.testing.unittestEnabled": false,'
#            '"python.testing.pytestEnabled": true,'
#
# With absolute imports:
#
# 1. Modules under ./src, such as ./src/script.py, can directly import with "import venv_manager.setup_venv".
#    This works regardless of whether the script is executed from within ./src or from another directory.
#
# 2. Modules deeper in the hierarchy, such as ./src/example/script.py, can also use "import venv_manager.setup_venv".
#    These nested modules CANNOT be run directly as scripts,
#    because doing so will result in a "ModuleNotFoundError" due to unresolved absolute imports.
#    However, they can still be imported and used by scripts under the ./src directory, such as ./src/script.py,
#    and everything will work correctly regardless of the current working directory.
from utils.logkit import (
    PATH_XDG_STATE_HOME,
    FileConfig,
    StderrConfig,
    StdoutConfig,
    get_logger,
)
from utils.logkit.filters import CallerInfoFilter

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable


# - - - - - - - - - - - - - - - - - -


# Default logging level.
# Since successful activation and other events also log at the INFO level,
# DEBUG and INFO messages are hidden from the console (stdout / stderr),
# but INFO messages are still recorded in the log file.
STDOUT_CONFIG: StdoutConfig | None = None
STDERR_CONFIG: StderrConfig | None = StderrConfig()
FILE_CONFIG: FileConfig = FileConfig(
    # Add caller info to the log format.
    log_format=(
        "[ %(asctime)s ] - [ %(levelname)s ] - [ caller: %(caller)s ] - "
        "[ process: %(process)d ] - [ logger: %(name)s ] - [ file: %(filename)s ] - "
        "[ line: %(lineno)d ] - [ module: %(module)s ] - %(message)s"
    ),
    log_path=PATH_XDG_STATE_HOME.joinpath(
        "log",
        "python-scripts",
        "venv_manager.log",
    ),
    rotate_mode="size",
    rotate_size_max_bytes=2 * 1024 * 1024,
    rotate_backup_count=7,
)

# Initialize logger with caller info included in the formatter.
# The '%(caller)s' field will be dynamically replaced with
# the caller's script name using a CallerInfoFilter.
logger = get_logger(
    "setup_venv",
    config_stdout=STDOUT_CONFIG,
    config_stderr=STDERR_CONFIG,
    config_file=FILE_CONFIG,
)

# Virtual environment prompt.
# It is displayed in the command-line prompt when the environment is activated.
VENV_PROMPT = "python-scripts"

# Get the absolute path of the current script's directory.
BASE_DIR = Path(__file__).resolve().parent

# Path to the virtual environment (without trailing `/`).
# Normalize the path to ensure proper backslashes are used on Windows.
VENV_PATH = (BASE_DIR / ".." / ".." / ".venv").resolve()

# System platform identifier
SYS_PLATFORM = platform.system().lower()

# Do not import any symbols when this module is imported
__all__: list[str] = []


# - - - - - - - - - - - - - - - - - -


class _PathInfo(TypedDict):
    """
    Typed dictionary for representing a filesystem path and its expected type.

    This type is used to indicate whether a given path should point to a directory
    or a file, along with the corresponding `Path` object.

    Attributes
    ----------
    path : Path
        The filesystem path.
    type : {"dir", "file"}
        The expected type of the path, indicating whether it should be a directory or a file.
    """

    path: Path
    type: Literal["dir", "file"]


# Add the CallerInfoFilter to the logger to inject caller information
# into log records. This needs to be added to all handlers.
caller_filter = CallerInfoFilter(
    exclude_patterns={
        __file__,
        "setup_venv.py",
        "venv_manager",
    },
)

# Add the filter to all handlers of the logger
for handler in logger.handlers:
    handler.addFilter(caller_filter)


def is_in_virtualenv() -> bool:
    """
    Check if currently running inside a virtual environment.

    Returns
    -------
    bool
        `True` if currently running inside a virtual environment, `False` otherwise.
    """
    has_base_prefix: bool = hasattr(sys, "base_prefix")
    base_prefix_differs: bool = (
        sys.prefix != sys.base_prefix if has_base_prefix else False
    )
    has_real_prefix: bool = hasattr(sys, "real_prefix")

    return base_prefix_differs or has_real_prefix


def get_python_version_str(py_path: Path, logger: logging.Logger) -> str | None:
    """
    Get the python version string (e.g. `python3.8`) from a python executable.

    Parameters
    ----------
    py_path : Path
        Path to the python executable.
    logger : logging.Logger
        Logger for error reporting.

    Returns
    -------
    str or None
        Python version string (only `major` & `minor`), prefixed with `python`, e.g., `python3.8`.
        Returns `None` if the version cannot be determined.

    Notes
    -----
    The version string is obtained by executing the python executable with the `-c` option.
    The command is `import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')`.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [
                os.fsdecode(py_path),
                "-c",
                "import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        py_version = result.stdout.strip()

    except FileNotFoundError:
        logger.exception("Error: '%s' not found.", py_path)
        return None

    except Exception:
        logger.exception("Error: failed to get Python version string.")
        return None

    if py_version.startswith("python"):
        return py_version

    logger.error("Error: Unexpected version output: '%s'.", py_version)
    return None


def parse_python_version(py_exec: Path) -> tuple[int, int]:
    """
    Parse major and minor version from the executable name.

    Parameters
    ----------
    py_exec : Path
        Path to the Python executable.

    Returns
    -------
    tuple of (int, int)
        A tuple of the form `(major, minor)`. Returns `(-1, -1)` if parsing fails.

    Notes
    -----
    This function parses the version from the filename only.
    It does not execute the binary to determine the actual version.
    It also does not verify whether the file actually exists.

    Examples
    --------
    - `python` -> `(-1, -1)`
    - `python3` -> `(3, -1)`
    - `python3.10` -> `(3, 10)`
    - `python3.10.1` -> `(3, 10)`
    - `python3.x` -> `(-1 , -1)`
    - `python.3.11` -> `(-1 , -1)`
    - Unrecognized patterns -> `(-1, -1)`
    """
    version_str = py_exec.name

    # Define the regular expression pattern
    pattern = (
        r"^python(?:\s*|\s+)?(?:"
        r"(?P<major>\d+)(?:\.(?P<minor>\d+))?)?(?:\.\d+)?$"
    )
    match = re.match(pattern, version_str, re.IGNORECASE)

    major = minor = None

    if match:
        major = match.group("major")
        minor = match.group("minor")

    # If the regular expression matches a major version, convert major and minor to integers
    if major:
        major = int(major)

        # If minor is not matched, default it to -1
        minor = int(minor) if minor is not None else -1

        # Return the parsed (major, minor) version tuple
        return (major, minor)

    # Return (-1, -1) as the default if parsing fails
    return (-1, -1)


def activate_via_activate_this(
    activate_this_path: Path,
    logger: logging.Logger,
) -> bool:
    """
    Activate virtual environment by running `activate_this.py`.

    Parameters
    ----------
    activate_script : Path
        Path to the `activate_this.py` file in the virtual environment to be activated.
    logger : logging.Logger
        Logger for reporting.

    Returns
    -------
    bool
        `True` if successful, `False` otherwise.
    """
    if not activate_this_path.is_file():
        logger.error("activate_this.py not found: '%s'.", activate_this_path)
        return False

    try:
        runpy.run_path(os.fsdecode(activate_this_path))
    except Exception:
        logger.exception(
            "Failed to activate the virtual environment via activate_this.py.",
        )
        return False
    else:
        logger.info(
            "Successfully activated the virtual environment via activate_this.py: '%s'.",
            activate_this_path,
        )
        return True


def validate_path_exists_and_type(
    *,
    name: str,
    path: Path,
    path_type: Literal["dir", "file"] = "file",
    logger: logging.Logger,
) -> bool:
    """
    Validate that the given path exists and matches the expected type based on its name.

    Parameters
    ----------
    name : str
        A descriptive name for the path, used for both internal logic and log messages.
    path : Path
         The filesystem path to validate.
    path_type : {'dir', 'file'}, optional, default='file'
        The expected type of the path.
    logger : logging.Logger
        Logger used to output warning messages.

    Returns
    -------
    bool
        `True` if the path exists and matches the expected type; `False` otherwise.

    Notes
    -----
    If validation fails, a warning is logged via `logger`, and the function returns False.

    The `name` parameter is also included in warning log messages
    to provide clearer context about which path failed validation.
    """
    if not path.exists():
        logger.error("Path '%s' not found: '%s'.", name, path)
        return False

    # Directory
    if path_type == "dir" and not path.is_dir():
        logger.error("Expected directory for '%s': '%s'.", name, path)
        return False

    # File
    if path_type == "file" and not path.is_file():
        logger.error("Expected file for '%s': '%s'.", name, path)
        return False

    return True


def get_site_packages_path(lib_path: Path, py_version_str: str) -> Path | None:
    """
    Compute the site-packages path inside a virtualenv.

    Parameters
    ----------
    lib_path : Path
        Path to the lib directory of the virtualenv.
    version : str
        Version string like 'python3.8'.

    Returns
    -------
    Path or None
        Path to the site-packages directory.
        Returns `None` if the platform type is not supported (unable to determine the site-packages path).
    """
    if "windows" in SYS_PLATFORM:
        return (lib_path / "site-packages").resolve()

    if "darwin" in SYS_PLATFORM or "linux" in SYS_PLATFORM:
        return (lib_path / py_version_str / "site-packages").resolve()

    logger.error("Unsupported platform type: '%s'.", SYS_PLATFORM)

    return None


def activate_manually(
    *,
    venv_path: Path,
    venv_bin_path: Path,
    venv_lib_path: Path,
    venv_py_path: Path,
    logger: logging.Logger,
) -> bool:
    """
    Activate virtualenv by setting environment variables manually.

    Parameters
    ----------
    venv_path : Path
        Root path to the virtual environment (without trailing `/`, e.g., `/path/to/.venv`).
    venv_bin_path : Path
        Path to the bin directory of the virtual environment (macOS /Linux: `bin`, Windows: `Scripts`).
    venv_lib_path : Path
        Path to the lib directory of the virtual environment (macOS / Linux: `lib`, Windows: `Lib`).
    venv_py_path : Path
        Path to the python executable.
    logger : logging.Logger
        Logger for reporting.

    Returns
    -------
    bool
        `True` if activation succeeded, `False` otherwise.
    """
    paths = {
        "Virtual Environment Path": _PathInfo(path=venv_path, type="dir"),
        "Virtual Environment Bin Path": _PathInfo(path=venv_bin_path, type="dir"),
        "Virtual Environment Lib Path": _PathInfo(path=venv_lib_path, type="dir"),
        "Virtual Environment Python Path": _PathInfo(path=venv_py_path, type="file"),
    }

    for name, info in paths.items():
        if not validate_path_exists_and_type(
            name=name,
            path=info["path"],
            path_type=info["type"],
            logger=logger,
        ):
            logger.error(
                "Failed to activate the virtual environment by manually setting environment variables, "
                "the following path does not exist. '%s' (type: '%s'): '%s'.",
                name,
                info["type"],
                info["path"],
            )
            return False

    # Prepend the bin dir to PATH (activate_this.py file is inside the bin directory)
    # This ensures that scripts and executables from the virtual environment are prioritized.
    os.environ["PATH"] = os.pathsep.join(
        [os.fsdecode(venv_bin_path), *os.environ.get("PATH", "").split(os.pathsep)],
    )

    # Set the VIRTUAL_ENV environment variable to indicate the active virtual environment.
    os.environ["VIRTUAL_ENV"] = os.fsdecode(venv_path)

    # Set the prompt for the virtual environment, using a custom prompt if available,
    # otherwise falling back to the environment's base name.
    os.environ["VIRTUAL_ENV_PROMPT"] = VENV_PROMPT or venv_path.name

    # Parse the Python version number (only major and minor) in a virtual environment, such as 'python3.11'.
    python_version_str = get_python_version_str(venv_py_path, logger)

    if not python_version_str:
        logger.error(
            "Failed to activate the virtual environment by manually setting environment variables: "
            "failed to retrieve the Python version string.",
        )
        return False

    venv_site_path = get_site_packages_path(venv_lib_path, python_version_str)

    if not venv_site_path:
        logger.error(
            "Failed to activate the virtual environment by manually setting environment variables: "
            "failed to determine the Site Packages directory of the virtual environment.",
        )
        return False

    if not validate_path_exists_and_type(
        name="Virtual Environment Site Packages Path",
        path=venv_site_path,
        path_type="dir",
        logger=logger,
    ):
        logger.error(
            "Failed to activate the virtual environment by manually setting environment variables, "
            "the following path does not exist. '%s' (type: '%s'): '%s'.",
            "Virtual Environment Site Packages Path",
            "dir",
            venv_site_path,
        )
        return False

    # Add the virtual environment's libraries to the host Python import mechanism.
    # This ensures Python can import packages from the virtual environment.
    prev_length = len(sys.path)
    site.addsitedir(os.fsdecode(venv_site_path))
    # Reorder sys.path to prioritize the newly added virtual environment paths.
    sys.path[:] = sys.path[prev_length:] + sys.path[0:prev_length]

    # Store the original system prefix to allow restoration later,
    # and update it to the virtual environment path.
    sys.real_prefix = sys.prefix  # type: ignore[attr-defined]
    sys.prefix = os.fsdecode(venv_path)

    logger.debug("Using Python interpreter: '%s'.", venv_py_path)
    logger.debug(
        "The extracted Python version string in the virtual environment: '%s'.",
        python_version_str,
    )
    logger.debug("sys.base_prefix: '%s'.", sys.base_prefix)
    logger.debug("sys.prefix: '%s'.", sys.prefix)
    logger.debug("sys.path: '%s'.", sys.path)
    logger.debug("VIRTUAL_ENV_PROMPT: '%s'.", os.environ["VIRTUAL_ENV_PROMPT"])
    logger.debug("VIRTUAL_ENV: '%s'.", os.environ["VIRTUAL_ENV"])
    logger.debug("PATH: '%s'.", os.environ["PATH"])

    logger.info(
        "Successfully activated the virtual environment by manually setting environment variables: '%s'.",
        venv_path,
    )

    return True


def activate_virtualenv(venv_path: Path, logger: logging.Logger | None = None) -> bool:
    """
    Attempt activation of a virtualenv using multiple methods.

    Parameters
    ----------
    venv_path : Path
        Root path to the virtual environment (without trailing `/`, e.g., `/path/to/.venv`).
    logger : logging.Logger, optional
        Logger for output. If not provided, a default logger will be created.

    Returns
    -------
    bool
        `True` if any activation method succeeded, `False` otherwise.
    """
    if logger is None:
        logger = get_logger()

    if "windows" in SYS_PLATFORM:
        py_activate_this = venv_path / "Scripts" / "activate_this.py"
        venv_bin_path = venv_path / "Scripts"
        venv_lib_path = venv_path / "Lib"
        py_exec_pattern = re.compile(r"^python(\d+(\.\d+){0,3})?\.exe$")
    elif "darwin" in SYS_PLATFORM or "linux" in SYS_PLATFORM:
        py_activate_this = venv_path / "bin" / "activate_this.py"
        venv_bin_path = venv_path / "bin"
        venv_lib_path = venv_path / "lib"
        py_exec_pattern = re.compile(r"^python(\d+(\.\d+){0,3})?$")
    else:
        logger.error("Unsupported platform: '%s'.", SYS_PLATFORM)
        return False

    # Retrieve all Python executables within the virtual environment
    # and select the highest version (e.g., "python3.8", "python3.13").
    # Fallback options like "python3" / "python2" / "python" are considered last.
    if not validate_path_exists_and_type(
        name="Virtual Environment Bin Path",
        path=venv_bin_path,
        path_type="dir",
        logger=logger,
    ):
        logger.error(
            "Virtual environment bin directory not found: '%s'.",
            venv_bin_path,
        )
        return False

    python_executables = [
        p for p in venv_bin_path.iterdir() if py_exec_pattern.fullmatch(p.name)
    ]

    if not python_executables:
        logger.error("No Python executables found in the virtual environment.")
        return False

    sortedp_py_executables = sorted(
        python_executables,
        key=parse_python_version,
        reverse=True,  # Sort in descending order to prioritize the latest version
    )

    # Select the highest version of Python as the preferred executable
    venv_py_path = sortedp_py_executables[0]

    methods: list[tuple[str, Callable[[], bool]]] = [
        (
            "activate_this.py Script",
            lambda: activate_via_activate_this(
                activate_this_path=py_activate_this,
                logger=logger,
            ),
        ),
        (
            "Manually set environment variables",
            lambda: activate_manually(
                venv_path=venv_path,
                venv_bin_path=venv_bin_path,
                venv_lib_path=venv_lib_path,
                venv_py_path=venv_py_path,
                logger=logger,
            ),
        ),
    ]

    for name, func in methods:
        logger.info("Trying to activate the virtual environment via '%s' ...", name)

        if func():
            return True

        logger.error(
            "Failed to activate the virtual environment via '%s'. Trying next method ...",
            name,
        )

    logger.error(
        "All activation methods failed. Failed to activate the virtual environment.",
    )
    return False


# Activate on import.
# Do not use if __name__ == "__main__" here;
# this function needs to run immediately upon import.
#
# Skip activation if already inside a virtual environment
if is_in_virtualenv():
    logger.warning(
        "Already inside a virtual environment. Virtual environment activation skipped.",
    )
elif activate_virtualenv(venv_path=VENV_PATH, logger=logger):
    logger.info("Virtual environment activated successfully.")
else:
    logger.critical("Failed to activate virtual environment.")
    sys.exit(1)
