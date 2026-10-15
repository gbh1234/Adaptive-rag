"""Support ``python -m app.cli``."""

from app.cli.commands import main

if __name__ == "__main__":
    raise SystemExit(main())
