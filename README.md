# PDF Editor

A feature-rich PDF editor built with Python, PyQt5, and PyMuPDF.

## Features

- 📂 Open, save, and export PDFs
- ✏️ Edit text in-place (double-click to edit)
- 🖼️ Add images to pages
- 🖍️ Annotations: pen drawing, highlighter, sticky notes
- 📌 Stamps (preset + custom) and signatures
- 🔗 Add/remove hyperlinks and internal page links
- 💧 Watermarks (text + image)
- 🔢 Page numbers, headers, and footers
- 🔍 Text search with highlight
- 📑 Page management (reorder, rotate, delete, merge, split)
- 🎨 Dark / light / system theme
- ⚡ Undo/redo for all operations
- 💾 Persistent settings across sessions

## Requirements

- Python 3.10+
- PyQt5
- PyMuPDF (fitz)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python app.py
```

Or open a specific file:

```bash
python app.py "path/to/file.pdf"
```

## Build executable

```bash
.\build.bat
```

Output: `dist\PDF Editor.exe`

## Project Structure

```
pdf-edit/
├── app.py                  # Entry point
├── src/
│   ├── main_window.py      # Main window (PDFEditorWindow)
│   ├── graphics_view.py    # PDF canvas (PDFGraphicsView)
│   ├── models/
│   │   └── annotation.py   # Annotation data model
│   ├── items/
│   │   ├── sticky_note.py  # Sticky note widget
│   │   └── text_block.py   # Editable text block widget
│   └── dialogs/
│       ├── helpers.py       # Shared helpers
│       ├── watermark.py     # Watermark dialog
│       ├── stamp.py         # Stamp dialog
│       ├── signature.py     # Signature dialog
│       ├── page_number.py   # Page number dialog
│       ├── header_footer.py # Header/footer dialog
│       └── link.py          # Link dialog
├── pdf-editor.spec          # PyInstaller build spec
├── build.bat                # Build script
└── requirements.txt         # Dependencies
```

## License

MIT