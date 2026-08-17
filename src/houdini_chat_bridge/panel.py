"""PySide6 presentation layer for the Houdini Chat Bridge Python Panel.

This module intentionally contains no network inspection, validation, action,
or undo logic. It delegates those responsibilities to the bridge modules.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Mapping

import hou
from PySide6 import QtCore, QtGui, QtWidgets

from .context import (
    inspect_current_context,
    inspect_current_network,
    inspect_selected_nodes,
    inspect_upstream_network,
)
from .executor import execute_operations
from .formatting import format_context_for_chatgpt, format_execution_summary


PANEL_BATCH_LABEL = "Houdini Chat Bridge panel batch"


def create_panel() -> QtWidgets.QWidget:
    """Create the Python Panel root widget on Houdini's main Qt thread."""
    return HoudiniChatBridgePanel()


class HoudiniChatBridgePanel(QtWidgets.QWidget):
    """Thin, main-thread UI for inspecting context and running explicit batches."""

    _COPY_CONTEXT_MODE_LABELS = {
        "selected": "Selected Nodes",
        "upstream": "Selected + Upstream",
        "network": "Whole Current Network",
    }

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("houdini_chat_bridge_panel")
        self.setProperty("houdiniStyle", True)
        self._copy_context_mode = "upstream"
        self._build_ui()
        self.refresh_context()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        context_group = QtWidgets.QGroupBox("CONTEXT")
        context_layout = QtWidgets.QFormLayout(context_group)
        self.network_path_label = _selectable_label("No network context")
        self.selected_nodes_label = _selectable_label("No selected nodes")
        self.display_node_label = _selectable_label("No display node")
        context_layout.addRow("Current network", self.network_path_label)
        context_layout.addRow("Selected nodes", self.selected_nodes_label)
        context_layout.addRow("Display node", self.display_node_label)

        context_buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh Context")
        self.refresh_button.setMinimumWidth(130)
        self.refresh_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.refresh_button.setToolTip(
            "Refresh the current network, selection, and display-node information."
        )
        self.copy_context_button = QtWidgets.QToolButton()
        self.copy_context_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.copy_context_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.copy_context_button.setMinimumWidth(300)
        self.copy_context_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.copy_context_button.setToolTip(
            "Copy Houdini context using the currently selected scope."
        )
        copy_context_menu = QtWidgets.QMenu(self.copy_context_button)
        self.copy_selected_action = copy_context_menu.addAction("Selected Nodes")
        self.copy_upstream_action = copy_context_menu.addAction("Selected + Upstream")
        self.copy_network_action = copy_context_menu.addAction("Whole Current Network")
        self.copy_selected_action.setToolTip("Copy only the currently selected nodes.")
        self.copy_upstream_action.setToolTip(
            "Copy the selected nodes and their wired upstream dependencies."
        )
        self.copy_network_action.setToolTip(
            "Copy the immediate contents of the current Network Editor."
        )
        self.copy_context_action_group = QtGui.QActionGroup(self)
        self.copy_context_action_group.setExclusive(True)
        for action in (
            self.copy_selected_action,
            self.copy_upstream_action,
            self.copy_network_action,
        ):
            action.setCheckable(True)
            self.copy_context_action_group.addAction(action)
        self.copy_upstream_action.setChecked(True)
        self.copy_context_button.setMenu(copy_context_menu)
        self._update_copy_context_button_label()
        context_buttons.addWidget(self.refresh_button, 0)
        context_buttons.addWidget(self.copy_context_button, 1)
        context_layout.addRow(context_buttons)
        layout.addWidget(context_group)

        patch_group = QtWidgets.QGroupBox("PATCH")
        patch_layout = QtWidgets.QVBoxLayout(patch_group)
        self.operation_editor = QtWidgets.QPlainTextEdit()
        self.operation_editor.setPlaceholderText(_operation_placeholder())
        self.operation_editor.setMinimumHeight(260)
        self.operation_editor.setTabChangesFocus(False)
        self.operation_editor.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.operation_editor.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        patch_layout.addWidget(self.operation_editor)

        execution_buttons = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("Check")
        self.execute_button = QtWidgets.QPushButton("Execute")
        self.execute_button.setDefault(True)
        execution_buttons.addWidget(self.check_button)
        execution_buttons.addStretch(1)
        execution_buttons.addWidget(self.execute_button)
        patch_layout.addLayout(execution_buttons)
        result_group = QtWidgets.QGroupBox("RESULT")
        result_layout = QtWidgets.QVBoxLayout(result_group)
        self.result_output = QtWidgets.QPlainTextEdit()
        self.result_output.setReadOnly(True)
        self.result_output.setMinimumHeight(120)
        self.result_output.setPlaceholderText("Check and execution results appear here.")
        self.result_output.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        result_layout.addWidget(self.result_output)

        self.details_group = QtWidgets.QGroupBox("Technical Details")
        self.details_group.setCheckable(True)
        self.details_group.setChecked(False)
        details_layout = QtWidgets.QVBoxLayout(self.details_group)
        self.details_output = QtWidgets.QPlainTextEdit()
        self.details_output.setReadOnly(True)
        self.details_output.setMinimumHeight(120)
        self.details_output.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        details_layout.addWidget(self.details_output)
        self.details_group.toggled.connect(self.details_output.setVisible)
        self.details_output.setVisible(False)
        result_layout.addWidget(self.details_group)

        self.lower_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.lower_splitter.setChildrenCollapsible(False)
        self.lower_splitter.addWidget(patch_group)
        self.lower_splitter.addWidget(result_group)
        self.lower_splitter.setStretchFactor(0, 7)
        self.lower_splitter.setStretchFactor(1, 3)
        self.lower_splitter.setSizes([680, 320])
        layout.addWidget(self.lower_splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_context)
        self.copy_context_button.clicked.connect(self.copy_context)
        self.copy_selected_action.triggered.connect(
            lambda _checked=False: self._set_copy_context_mode("selected")
        )
        self.copy_upstream_action.triggered.connect(
            lambda _checked=False: self._set_copy_context_mode("upstream")
        )
        self.copy_network_action.triggered.connect(
            lambda _checked=False: self._set_copy_context_mode("network")
        )
        self.check_button.clicked.connect(lambda: self._schedule_batch(dry_run=True))
        self.execute_button.clicked.connect(lambda: self._schedule_batch(dry_run=False))

    def refresh_context(self, show_status: bool = True) -> None:
        """Refresh only the lightweight context display."""
        try:
            self._require_main_thread()
            context = inspect_current_context()
            self._display_context(context)
            if show_status and context.get("error"):
                self._set_result("Context inspection note: %s" % context["error"])
            elif show_status:
                self._set_result("Context refreshed.")
        except Exception:
            if show_status:
                self._show_exception("Could not refresh Houdini context")

    def copy_selected_context(self) -> None:
        try:
            self._require_main_thread()
            context = inspect_selected_nodes()
            self._copy_text(format_context_for_chatgpt(context))
            self._set_result("Selected nodes context copied.")
        except Exception:
            self._show_exception("Could not copy selected-node context")

    def copy_context(self) -> None:
        """Copy with the scope selected in the Copy Context split button."""
        copy_methods = {
            "selected": self.copy_selected_context,
            "upstream": self.copy_upstream_context,
            "network": self.copy_current_network_context,
        }
        copy_methods[self._copy_context_mode]()

    def _set_copy_context_mode(self, mode: str) -> None:
        if mode not in self._COPY_CONTEXT_MODE_LABELS:
            raise ValueError("Unsupported copy-context mode: %s." % mode)
        self._copy_context_mode = mode
        self._update_copy_context_button_label()

    def _update_copy_context_button_label(self) -> None:
        label = self._COPY_CONTEXT_MODE_LABELS[self._copy_context_mode]
        self.copy_context_button.setText("Copy: %s" % label)

    def copy_upstream_context(self) -> None:
        try:
            self._require_main_thread()
            selected = inspect_selected_nodes().get("selected_nodes", [])
            if not selected:
                raise RuntimeError("Select a node before copying upstream context.")
            path = selected[0].get("path")
            node = hou.node(path) if isinstance(path, str) else None
            if node is None:
                raise RuntimeError("Selected node is no longer available: %s." % path)
            self._copy_text(format_context_for_chatgpt(inspect_upstream_network(node)))
            self._set_result("Selected + upstream context copied.")
        except Exception:
            self._show_exception("Could not copy upstream context")

    def copy_current_network_context(self) -> None:
        try:
            self._require_main_thread()
            self._copy_text(format_context_for_chatgpt(inspect_current_network()))
            self._set_result("Whole current network context copied.")
        except Exception:
            self._show_exception("Could not copy current network context")

    def _schedule_batch(self, dry_run: bool) -> None:
        """Yield to Qt once so button state paints before main-thread HOM work."""
        self.details_output.clear()
        self._set_busy(True, "Checking patch..." if dry_run else "Executing patch...")
        QtCore.QTimer.singleShot(0, lambda: self._run_batch(dry_run))

    def _run_batch(self, dry_run: bool) -> None:
        try:
            self._require_main_thread()
            try:
                operations = _parse_operations(self.operation_editor.toPlainText())
            except ValueError as error:
                self._show_parse_error(str(error), dry_run=dry_run)
                return
            parent = self._current_network_node()
            result = execute_operations(
                parent,
                operations,
                label=PANEL_BATCH_LABEL,
                dry_run=dry_run,
            )
            self._show_result(result, dry_run=dry_run)
            self.refresh_context(show_status=False)
        except Exception:
            self._show_exception("Could not %s patch" % ("check" if dry_run else "execute"))
        finally:
            self._set_busy(False)

    def _current_network_node(self) -> Any:
        context = inspect_current_context()
        network = context.get("current_network")
        path = network.get("path") if isinstance(network, Mapping) else None
        if not isinstance(path, str) or not path:
            raise RuntimeError("No current Network Editor context is available for this batch.")
        node = hou.node(path)
        if node is None:
            raise RuntimeError("Current network no longer exists: %s." % path)
        return node

    def _show_result(self, result: Mapping[str, Any], dry_run: bool) -> None:
        success = result.get("success") is True
        if success and dry_run:
            self._set_result(
                "CHECK PASSED\n\n"
                "Patch is structurally valid.\n"
                "Preflight checks passed.\n"
                "No scene changes were made."
            )
        elif success:
            self._set_result(format_execution_summary(result))
        else:
            heading = "PREFLIGHT FAILED" if dry_run else "FAILED"
            self._set_result("%s\n\n%s\n\nSee Technical Details." % (heading, _first_error_message(result)))
            self.details_group.setChecked(True)
        self.details_output.setPlainText(json.dumps(result, indent=2, sort_keys=True, default=str))

    def _display_context(self, context: Mapping[str, Any]) -> None:
        network = context.get("current_network")
        display = context.get("display_node")
        selected = context.get("selected_nodes")
        self.network_path_label.setText(_path_or_placeholder(network, "No current network"))
        self.display_node_label.setText(_path_or_placeholder(display, "No display node"))
        if isinstance(selected, list) and selected:
            paths = [item.get("path") for item in selected if isinstance(item, Mapping) and item.get("path")]
            self.selected_nodes_label.setText("\n".join(paths) if paths else "No selected nodes")
        else:
            self.selected_nodes_label.setText("No selected nodes")

    def _copy_text(self, text: str) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Qt clipboard is unavailable.")
        clipboard.setText(text)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        for button in (self.check_button, self.execute_button):
            button.setEnabled(not busy)
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_result(message or "Working...")
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _set_result(self, message: str) -> None:
        self.result_output.setPlainText(message)

    def _show_parse_error(self, message: str, *, dry_run: bool) -> None:
        heading = "VALIDATION FAILED" if dry_run else "FAILED"
        self._set_result("%s\n\n%s\n\nSee Technical Details." % (heading, message))
        self.details_group.setChecked(True)
        self.details_output.setPlainText(json.dumps({
            "success": False,
            "stage": "parse",
            "errors": [{"message": message}],
        }, indent=2, sort_keys=True))

    def _show_exception(self, summary: str) -> None:
        details = traceback.format_exc()
        self._set_result("FAILED\n\n%s. See Technical Details." % summary)
        self.details_group.setChecked(True)
        self.details_output.setPlainText(json.dumps({
            "success": False,
            "errors": [{"message": summary}],
            "traceback": details,
        }, indent=2, sort_keys=True))

    @staticmethod
    def _require_main_thread() -> None:
        application = QtWidgets.QApplication.instance()
        if application is None or QtCore.QThread.currentThread() != application.thread():
            raise RuntimeError("Houdini operations must run on the main Qt application thread.")


def _parse_operations(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        raise ValueError("Enter a JSON list of supported operations before validating or executing.")
    try:
        operations = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Operation JSON is invalid: %s" % error) from error
    if not isinstance(operations, list):
        raise ValueError("Operation JSON must contain a list.")
    if not all(isinstance(operation, dict) for operation in operations):
        raise ValueError("Each operation in the JSON list must be an object.")
    return operations


def _first_error_message(result: Mapping[str, Any]) -> str:
    errors = result.get("errors")
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], Mapping):
        return "The patch could not be completed."
    error = errors[0]
    message = str(error.get("message") or "The patch could not be completed.")
    index = error.get("operation_index")
    if isinstance(index, int):
        return "Operation %d: %s" % (index + 1, message)
    return message


def _path_or_placeholder(value: Any, placeholder: str) -> str:
    if isinstance(value, Mapping) and isinstance(value.get("path"), str):
        return value["path"]
    return placeholder


def _selectable_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _operation_placeholder() -> str:
    return """[
  {
    \"action\": \"create_node\",
    \"id\": \"pole\",
    \"node_type_name\": \"tube\",
    \"name\": \"POLE\"
  },
  {
    \"action\": \"set_parameter\",
    \"node\": {\"ref\": \"pole\"},
    \"parameter\": \"height\",
    \"value\": 5.0
  }
]"""
