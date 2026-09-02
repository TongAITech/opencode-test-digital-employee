"""OpenCode AI Test canonical R1-R4 runtime package.

Importing the package itself must be side-effect free and must not initialize
legacy V1.11.1 runtime paths such as ``AITEST_DB_PATH``/``aitest.db``.
"""

VERSION = "R1-R4-CANONICAL-G1G2-REPAIR"

__all__ = ["VERSION"]
