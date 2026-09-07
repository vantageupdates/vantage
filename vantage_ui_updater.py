"""Portable entry point for VantageUI; no integration side effects on Vantage."""
from vantage.ui_skin_app import main

if __name__ == "__main__":
    raise SystemExit(main())
