"""`python3 -m muchanipo serve …` entrypoint (delegates to src.muchanipo)."""

from src.muchanipo.server import main

if __name__ == "__main__":
    raise SystemExit(main())
