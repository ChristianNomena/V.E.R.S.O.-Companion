"""
V.E.R.S.O. - Application Entrypoint
Run this file to start V.E.R.S.O. Companion:
    python main.py
"""

import flet as ft
from verso.database import init_db
from verso.ui.app import create_app


def main():
    init_db()
    ft.run(main=create_app)


if __name__ == "__main__":
    main()
