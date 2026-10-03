"""Read-only local dependency check; never opens a cloud job or prints secrets."""

from importlib.metadata import version
import sys


EXPECTED = {
    "allsolve": "0.5.2",
    "fastapi": "0.115.6",
    "numpy": "1.26.4",
    "scipy": "1.14.1",
    "scikit-learn": "1.5.2",
    "pytest": "8.3.4",
}


def main() -> int:
    print(f"Python {sys.version.split()[0]}")
    if sys.version_info[:2] != (3, 11):
        print("MetaSense requires Python 3.11 for its checked environment.")
        return 1

    mismatch = False
    for package, expected in EXPECTED.items():
        actual = version(package)
        print(f"{package} {actual}")
        mismatch |= actual != expected

    import allsolve  # noqa: F401 - import check
    import fastapi  # noqa: F401 - import check
    import numpy  # noqa: F401 - import check
    import scipy  # noqa: F401 - import check
    import sklearn  # noqa: F401 - import check

    if mismatch:
        print("At least one installed package differs from the tested pins.")
        return 1
    print("Core dependencies import successfully. No local mesher is required by the SDK scaffold.")
    print("Allsolve optical physics remains unimplemented pending a verified workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
