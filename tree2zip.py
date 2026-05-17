import os
import re
import sys
import zipfile
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QTextEdit,
)


# ---------------------------
# Parsing / ZIP logic
# ---------------------------

def clean_line(line: str) -> str:
    return line.split("#")[0].rstrip()


def get_depth_and_name(line: str):
    line = clean_line(line)
    if not line.strip():
        return None, None

    if not any(sym in line for sym in ["├──", "└──"]):
        return 0, line.strip()

    match = re.match(r"^((?:│   |    )*)(├── |└── )(.*)$", line)
    if not match:
        return None, None

    indent_part = match.group(1)
    name = match.group(3).strip()
    depth = len(indent_part) // 4 + 1
    return depth, name


def is_directory(name: str) -> bool:
    return name.endswith("/")


def parse_tree_text(text: str):
    items = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        depth, name = get_depth_and_name(line)
        if name is not None:
            items.append((depth, name))
    return items


def parse_tree_file(txt_path: str):
    with open(txt_path, "r", encoding="utf-8") as f:
        return parse_tree_text(f.read())


def build_structure(items, base_dir):
    path_stack = {}

    for depth, name in items:
        name = clean_line(name)

        if depth == 0:
            root_name = name.rstrip("/")
            current_path = os.path.join(base_dir, root_name)
            os.makedirs(current_path, exist_ok=True)
            path_stack[0] = current_path
            continue

        parent_path = path_stack.get(depth - 1)
        if not parent_path:
            raise ValueError(f"Invalid tree structure near: {name}")

        current_name = name.rstrip("/")
        current_path = os.path.join(parent_path, current_name)

        if is_directory(name):
            os.makedirs(current_path, exist_ok=True)
        else:
            os.makedirs(parent_path, exist_ok=True)
            with open(current_path, "w", encoding="utf-8") as f:
                f.write("")

        path_stack[depth] = current_path


def zip_directory(folder_path, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for d in dirs:
                dir_path = os.path.join(root, d)
                arcname = os.path.relpath(dir_path, os.path.dirname(folder_path))
                zipf.write(dir_path, arcname)
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                zipf.write(file_path, arcname)


def generate_zip_from_text(tree_text: str, output_zip: str):
    items = parse_tree_text(tree_text)
    if not items:
        raise ValueError("No valid tree structure found.")

    with tempfile.TemporaryDirectory() as temp_dir:
        build_structure(items, temp_dir)
        root_name = items[0][1].rstrip("/")
        root_folder = os.path.join(temp_dir, root_name)
        zip_directory(root_folder, output_zip)


# ---------------------------
# Drag and Drop Box
# ---------------------------

class DropZone(QFrame):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        layout = QVBoxLayout(self)

        self.label = QLabel("Drag & drop your tree .txt file here")
        self.label.setAlignment(Qt.AlignCenter)

        self.sub = QLabel("or click Browse to select a file")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setObjectName("SubtleLabel")

        layout.addStretch()
        layout.addWidget(self.label)
        layout.addWidget(self.sub)
        layout.addStretch()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".txt"):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(".txt"):
                self.fileDropped.emit(file_path)
                event.acceptProposedAction()


# ---------------------------
# Main Window
# ---------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tree to ZIP")
        self.resize(1000, 680)

        self.current_text = ""
        self.current_file = None

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        # Title
        title = QLabel("Tree Structure → ZIP")
        title.setObjectName("Title")

        subtitle = QLabel("Generate a classic folder/file structure from a text tree.")
        subtitle.setObjectName("SubtleLabel")

        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        # Top controls
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText("Input .txt file...")
        self.input_path.setReadOnly(True)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_input)

        top_row.addWidget(self.input_path, 1)
        top_row.addWidget(browse_btn)

        root_layout.addLayout(top_row)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self.load_file)
        root_layout.addWidget(self.drop_zone)

        # Middle split
        middle = QHBoxLayout()
        middle.setSpacing(14)

        # Raw text editor
        left_panel = QVBoxLayout()
        left_label = QLabel("Tree text")
        left_label.setObjectName("SectionTitle")

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Paste your tree structure here...")
        self.editor.textChanged.connect(self.update_preview)

        left_panel.addWidget(left_label)
        left_panel.addWidget(self.editor)

        # Preview tree
        right_panel = QVBoxLayout()
        right_label = QLabel("Preview")
        right_label.setObjectName("SectionTitle")

        self.preview = QTreeWidget()
        self.preview.setHeaderLabels(["Name", "Type"])
        self.preview.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.preview.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preview.setAlternatingRowColors(False)

        right_panel.addWidget(right_label)
        right_panel.addWidget(self.preview)

        middle.addLayout(left_panel, 1)
        middle.addLayout(right_panel, 1)

        root_layout.addLayout(middle, 1)

        # Output row
        output_row = QHBoxLayout()
        output_row.setSpacing(10)

        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Output ZIP file path...")

        output_btn = QPushButton("Choose Output")
        output_btn.clicked.connect(self.choose_output)

        output_row.addWidget(self.output_path, 1)
        output_row.addWidget(output_btn)

        root_layout.addLayout(output_row)

        # Bottom buttons
        bottom = QHBoxLayout()
        bottom.addStretch()

        self.generate_btn = QPushButton("Generate ZIP")
        self.generate_btn.setObjectName("PrimaryButton")
        self.generate_btn.clicked.connect(self.generate_zip)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_all)

        bottom.addWidget(clear_btn)
        bottom.addWidget(self.generate_btn)

        root_layout.addLayout(bottom)

        self.apply_styles()

        # Menu
        self.build_menu()

    def build_menu(self):
        menu = self.menuBar().addMenu("File")

        open_action = QAction("Open TXT", self)
        open_action.triggered.connect(self.browse_input)

        save_action = QAction("Choose Output ZIP", self)
        save_action.triggered.connect(self.choose_output)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)

        menu.addAction(open_action)
        menu.addAction(save_action)
        menu.addSeparator()
        menu.addAction(exit_action)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #f6f7fb;
                color: #1f2937;
                font-family: Segoe UI, Inter, Arial;
                font-size: 13px;
            }

            QLabel#Title {
                font-size: 24px;
                font-weight: 700;
                color: #111827;
            }

            QLabel#SectionTitle {
                font-size: 14px;
                font-weight: 600;
                color: #111827;
                padding-bottom: 4px;
            }

            QLabel#SubtleLabel {
                color: #6b7280;
                font-size: 12px;
            }

            QLineEdit, QTextEdit, QTreeWidget {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 10px;
            }

            QTextEdit {
                selection-background-color: #c7d2fe;
            }

            QTreeWidget {
                padding: 6px;
            }

            QTreeWidget::item {
                padding: 6px;
            }

            QPushButton {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 12px;
                padding: 10px 16px;
                color: #111827;
            }

            QPushButton:hover {
                background: #f3f4f6;
            }

            QPushButton#PrimaryButton {
                background: #111827;
                color: white;
                border: none;
                font-weight: 600;
            }

            QPushButton#PrimaryButton:hover {
                background: #1f2937;
            }

            QFrame#DropZone {
                border: 2px dashed #cbd5e1;
                border-radius: 16px;
                background: #ffffff;
                min-height: 120px;
            }

            QHeaderView::section {
                background: #f9fafb;
                color: #374151;
                border: none;
                border-bottom: 1px solid #e5e7eb;
                padding: 8px;
                font-weight: 600;
            }

            QMenuBar {
                background: #f6f7fb;
            }

            QMenuBar::item:selected {
                background: #e5e7eb;
                border-radius: 6px;
            }

            QMenu {
                background: white;
                border: 1px solid #e5e7eb;
            }

            QMenu::item:selected {
                background: #f3f4f6;
            }
        """)

    def browse_input(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Tree TXT File",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            self.load_file(file_path)

    def load_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.current_file = file_path
            self.current_text = text
            self.input_path.setText(file_path)
            self.editor.setPlainText(text)

            if not self.output_path.text().strip():
                default_zip = str(Path(file_path).with_suffix(".zip"))
                self.output_path.setText(default_zip)

            self.update_preview()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load file:\n{e}")

    def choose_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ZIP File",
            "output.zip",
            "ZIP Files (*.zip)"
        )
        if file_path:
            if not file_path.lower().endswith(".zip"):
                file_path += ".zip"
            self.output_path.setText(file_path)

    def update_preview(self):
        text = self.editor.toPlainText()
        self.current_text = text
        self.preview.clear()

        try:
            items = parse_tree_text(text)
            if not items:
                return

            tree_nodes = {}
            root_item = None

            for depth, name in items:
                display_name = name.rstrip("/")
                node_type = "Folder" if is_directory(name) else "File"

                item = QTreeWidgetItem([display_name, node_type])

                if depth == 0:
                    root_item = item
                    self.preview.addTopLevelItem(item)
                    tree_nodes[0] = item
                else:
                    parent = tree_nodes.get(depth - 1)
                    if parent:
                        parent.addChild(item)
                    else:
                        self.preview.addTopLevelItem(item)
                    tree_nodes[depth] = item

            self.preview.expandAll()

        except Exception:
            # Keep preview silent if text is incomplete while editing
            pass

    def generate_zip(self):
        text = self.editor.toPlainText().strip()
        output = self.output_path.text().strip()

        if not text:
            QMessageBox.warning(self, "Missing Input", "Please provide a tree structure.")
            return

        if not output:
            QMessageBox.warning(self, "Missing Output", "Please choose an output ZIP path.")
            return

        try:
            generate_zip_from_text(text, output)
            QMessageBox.information(self, "Success", f"ZIP created successfully:\n{output}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate ZIP:\n{e}")

    def clear_all(self):
        self.input_path.clear()
        self.output_path.clear()
        self.editor.clear()
        self.preview.clear()
        self.current_text = ""
        self.current_file = None


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
