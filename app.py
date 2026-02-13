"""PDF Editor Application - Entry Point"""

import sys
import os
from src.main_window import PDFEditorWindow

# Re-export for backward compatibility
__all__ = ["PDFEditorWindow"]


def main():
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Editor")
    app.setStyle("Fusion")

    window = PDFEditorWindow()
    window.show()

    # If a file was passed as argument, open it
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        window._load_pdf(sys.argv[1])

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
