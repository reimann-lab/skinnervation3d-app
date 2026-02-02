from __future__ import annotations

def main() -> int:
    from .app import run_app
    return run_app()

if __name__ == "__main__":
    raise SystemExit(main())