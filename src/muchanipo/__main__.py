"""`python3 -m src.muchanipo serve …` entrypoint."""

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
