"""
V.E.R.S.O. - Application Entrypoint
Run this file to start V.E.R.S.O. Companion:
    python main.py
"""

import flet as ft
from verso.ui.app import create_app


def main():
    ft.run(main=create_app)


if __name__ == "__main__":
    main()
