from gi.repository import Adw, GLib, Gdk, Gio, Gtk, Pango


from note_content_view import NoteContentView
import os
import shutil
from datetime import datetime

NOTES_DIR = os.path.expanduser("~/Documents/Notes")
EXT = ".md"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Markdown Notes")
        self.set_default_size(800, 600)

        # Setup AdwHeaderBar
        self.header = Adw.HeaderBar()

        # Move search entry to header bar
        self.entry = Gtk.SearchEntry()
        self.entry.set_hexpand(True)

        self.entry.set_placeholder_text("Search or create note...")
        self.entry.connect("activate", self.on_entry_activate)
        self.entry.connect("search-changed", self.on_entry_changed)

        # Add entry-specific shortcut controller with high priority
        entry_shortcut_controller = Gtk.ShortcutController.new()
        entry_shortcut_controller.set_scope(
            Gtk.ShortcutScope.MANAGED
        )  # Higher priority than LOCAL
        context_menu_shortcut = Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>o"),
            Gtk.CallbackAction.new(self.show_note_context_menu, None),
        )
        entry_shortcut_controller.add_shortcut(context_menu_shortcut)
        self.entry.add_controller(entry_shortcut_controller)

        # Regular key controller for other entry shortcuts
        self.entry_key_controller = Gtk.EventControllerKey.new()
        self.entry_key_controller.connect("key-pressed", self.on_search_entry_key_press)
        self.entry.add_controller(self.entry_key_controller)

        self.header.set_title_widget(self.entry)

        self.notes = []
        self.filtered_notes = []
        self.current_note_path = None
        self.load_notes()

        self.create_ui()
        self.setup_shortcuts()

        # Add focus controller for text entry shortcut (Ctrl+/)
        window_key_controller = Gtk.EventControllerKey.new()
        window_key_controller.connect("key-pressed", self.on_window_key_press)
        self.add_controller(window_key_controller)

        self.entry.grab_focus()

    def create_ui(self):
        # Main layout with headerbar
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        main_box.append(self.header)

        # Use Adw.OverlaySplitView for sidebar and content
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_vexpand(True)
        self.split_view.set_hexpand(True)
        self.vbox_sidebar_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10
        )
        main_box.append(self.split_view)

        # Notes List
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        self.vbox_sidebar_content.append(scrolled_window)

        self.note_list = Gtk.ListBox()
        self.note_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.note_list.connect("row-selected", self.on_note_selected)
        scrolled_window.set_child(self.note_list)

        # Set the sidebar child of the SplitView
        self.split_view.set_sidebar(self.vbox_sidebar_content)

        self.note_content_view = NoteContentView()
        self.note_content_view.set_parent_window(self)  # Set parent reference
        self.note_content_view.set_hexpand(True)
        self.note_content_view.set_vexpand(True)

        # Connect signals from the NoteContentView
        self.note_content_view.connect("content-saved", self.on_content_view_saved)
        self.note_content_view.connect(
            "edit-mode-exited", self.on_content_view_edit_exited
        )

        # Set the content child of the SplitView
        # The NoteContentView contains the stack internally
        self.split_view.set_content(self.note_content_view)

        # Add sidebar toggle button to the header bar
        self.sidebar_button = Gtk.Button()
        self.sidebar_button.set_child(
            Gtk.Image.new_from_icon_name("sidebar-show-symbolic")
        )
        self.sidebar_button.set_tooltip_text("Toggle Sidebar (Ctrl+B)")
        self.sidebar_button.connect("clicked", self.on_sidebar_button_clicked)
        self.header.pack_start(self.sidebar_button)

        self.refresh_note_list()

    def setup_shortcuts(self):
        # Shortcut for toggling sidebar (Ctrl+B)
        shortcut_controller = Gtk.ShortcutController.new()
        toggle_sidebar_shortcut = Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<control>b"),
            Gtk.CallbackAction.new(self.toggle_sidebar, None),
        )
        shortcut_controller.add_shortcut(toggle_sidebar_shortcut)

        self.add_controller(shortcut_controller)

    def show_note_context_menu(self, *args):
        """Shows the context menu for the currently selected note."""
        selected_row = self.note_list.get_selected_row()
        if not selected_row or not hasattr(selected_row, "filename"):
            return

        # Create menu model
        menu_model = Gio.Menu.new()
        menu_model.append("Open with Editor", "app.open_with_editor")
        menu_model.append("Rename", "app.rename_note")
        menu_model.append("Delete", "app.delete_note")

        # Create PopoverMenu
        popover_menu = Gtk.PopoverMenu.new_from_model(menu_model)
        popover_menu.set_parent(selected_row)

        # Setup actions
        action_group = Gio.SimpleActionGroup()
        action_group.add_action(Gio.SimpleAction.new("open_with_editor", None))
        action_group.add_action(Gio.SimpleAction.new("rename_note", None))
        action_group.add_action(Gio.SimpleAction.new("delete_note", None))

        action_group.lookup_action("open_with_editor").connect(
            "activate", self.on_open_with_editor_action
        )
        action_group.lookup_action("rename_note").connect(
            "activate", self.on_rename_note_action
        )
        action_group.lookup_action("delete_note").connect(
            "activate", self.on_delete_note_action
        )

        self.insert_action_group("app", action_group)
        popover_menu.popup()

    def find_notes_recursively(self, directory):
        notes = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(EXT):
                    rel_path = os.path.relpath(os.path.join(root, file), NOTES_DIR)
                    notes.append(rel_path)
        return notes

    def load_notes(self):
        os.makedirs(NOTES_DIR, exist_ok=True)
        self.notes = self.find_notes_recursively(NOTES_DIR)

    def refresh_note_list(self):
        # Keep track of the currently selected note's filename (relative path)
        selected_filename = None
        selected_row = self.note_list.get_selected_row()
        if selected_row and hasattr(selected_row, "filename"):
            selected_filename = selected_row.filename

        # Remove all children from the list box
        while True:
            row = self.note_list.get_first_child()
            if row is None:
                break
            self.note_list.remove(row)

        # Filter and sort notes
        search_text = self.entry.get_text().lower()
        self.filtered_notes = [
            note for note in self.notes if search_text in note.lower()
        ]
        self.filtered_notes.sort(key=lambda x: x.split(os.sep))

        # Add filtered notes to the list box
        select_row_after_refresh = None
        for note in self.filtered_notes:
            row = Gtk.ListBoxRow()

            # Strip the file extension for display
            display_name = os.path.splitext(note)[0]

            label = Gtk.Label(label=display_name)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(80)
            label.set_xalign(0)
            label.set_margin_start(5)
            label.set_margin_end(5)
            label.set_margin_top(5)
            label.set_margin_bottom(5)

            # Store the actual filename with extension as a Python attribute
            row.filename = note

            row.set_child(label)
            self.note_list.append(row)

            # Add gesture for context menu
            context_menu_gesture = Gtk.GestureClick.new()
            context_menu_gesture.set_button(Gdk.BUTTON_SECONDARY)  # Right mouse button
            context_menu_gesture.connect("pressed", self.on_row_right_click)
            row.add_controller(context_menu_gesture)

            # If this row was previously selected, mark it for re-selection
            if note == selected_filename:
                select_row_after_refresh = row

        # Re-select the previously selected row if it still exists, otherwise select the first
        if select_row_after_refresh:
            self.note_list.select_row(select_row_after_refresh)
        elif self.note_list.get_row_at_index(0):
            self.note_list.select_row(self.note_list.get_row_at_index(0))
        else:
            # No rows left, clear content area
            self.current_note_path = None
            self.note_content_view.set_content("")  # Clear content in the view

        self.entry.grab_focus()  # Ensure the search entry is focused

    def on_search_entry_key_press(self, controller, keyval, keycode, state):
        # Handle Escape key to clear search
        if keyval == Gdk.KEY_Escape:
            self.entry.set_text("")  # Clear search
            return Gdk.EVENT_STOP  # Stop propagation

        num_rows = len(self.filtered_notes)
        if num_rows > 0:
            selected_row = self.note_list.get_selected_row()
            current_index = -1
            if selected_row:
                current_index = selected_row.get_index()

            if keyval == Gdk.KEY_Up:
                if current_index > 0:
                    next_row = self.note_list.get_row_at_index(current_index - 1)
                    self.note_list.select_row(next_row)
                    self.note_list.get_selected_row().grab_focus()
                return Gdk.EVENT_STOP

            elif keyval == Gdk.KEY_Down:
                if current_index < num_rows - 1:
                    next_row = self.note_list.get_row_at_index(current_index + 1)
                    self.note_list.select_row(next_row)
                    self.note_list.get_selected_row().grab_focus()
                return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_entry_changed(self, entry):
        text = entry.get_text().strip()
        # Handle @today expansion immediately
        if text == "@today":
            today = datetime.now()
            new_text = f"Journal/{today.year}/{today.month:02d}/{today.day:02d}"
            # Temporarily block the changed signal to prevent recursion
            entry.handler_block_by_func(self.on_entry_changed)
            entry.set_text(new_text)
            entry.handler_unblock_by_func(self.on_entry_changed)
            # Move cursor to end
            entry.set_position(-1)
            return
        self.refresh_note_list()

    def on_entry_activate(self, entry):
        query = entry.get_text().strip()
        if not query:
            # If query is empty and a note is selected, open the selected note for editing
            selected_row = self.note_list.get_selected_row()
            if selected_row:
                self.on_note_selected(self.note_list, selected_row)
                self.note_content_view.enter_edit_mode()  # Delegate to new widget
            return

        # Add extension if not already present
        if not query.lower().endswith(EXT):
            filename = query + EXT
        else:
            filename = query
            query = os.path.splitext(query)[0]  # Use base name for title

        filename_relative = os.path.relpath(
            os.path.join(NOTES_DIR, filename), NOTES_DIR
        )
        filename_full_path = os.path.join(NOTES_DIR, filename_relative)

        if not len(self.filtered_notes):
            try:
                os.makedirs(os.path.dirname(filename_full_path), exist_ok=True)
                initial_content = f"# {query}\n\n"
                with open(filename_full_path, "w") as f:
                    f.write(initial_content)
                self.notes.append(filename_relative)
                self.notes.sort()
                self.refresh_note_list()

                # Select the newly created note
                for i, note in enumerate(self.filtered_notes):
                    if note == filename_relative:
                        row = self.note_list.get_row_at_index(i)
                        if row:
                            self.note_list.select_row(row)
                            # Manually trigger selection logic to ensure content is loaded
                            self.on_note_selected(self.note_list, row)
                            self.note_content_view.enter_edit_mode()  # Enter edit mode for new note
                        break
            except OSError as e:
                print(
                    f"Error creating note {filename_full_path}: {e}"
                )  # Basic error handling
                # Optionally show an error dialog
        else:
            # If a matching note exists, select it
            for i, note in enumerate(self.filtered_notes):
                idx = self.note_list.get_selected_row().get_index()
                if note == self.filtered_notes[idx]:  # Select the first match
                    row = self.note_list.get_row_at_index(i)
                    row.grab_focus()
                    self.on_note_selected(self.note_list, row)
                    # self.note_content_view.set_content
                    # Use a short delay before selecting to ensure the listbox is ready
                    # This can sometimes prevent issues with immediate selection after refresh
                    # GLib.timeout_add(
                    #     50, self.select_row_after_creation, row, matching_notes[0]
                    # )

    def select_row_after_creation(self, row, note_filename_relative):
        """Helper to select a row after a short delay."""
        if row:
            self.note_list.select_row(row)
            # Manually trigger selection logic to ensure content is loaded
            self.on_note_selected(self.note_list, row)
        return GLib.SOURCE_REMOVE  # Remove the timeout source

    def on_note_selected(self, listbox, row):
        if row and hasattr(row, "filename"):
            note_name = row.filename
            self.current_note_path = os.path.join(NOTES_DIR, note_name)
            self.load_note_into_view()  # Load content into the NoteContentView
            # Hide the sidebar on narrow widths after selecting a note if hide mode is active
            if (
                hasattr(self.split_view, "get_hide_sidebar")
                and self.split_view.get_hide_sidebar()
            ):
                self.entry.set_text("")
                self.split_view.set_show_sidebar(False)
        else:
            # Handle case where selection is cleared or an invalid row is selected
            self.current_note_path = None
            self.note_content_view.set_content("")  # Clear content in the view

    def on_row_right_click(self, gesture, n_press, x, y):
        # Ensure it's a right-click (BUTTON_SECONDARY = 3) and only one press
        if n_press == 1 and gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            row = gesture.get_widget()  # Get the row that was clicked
            if not row or not hasattr(row, "filename"):
                return  # Should not happen if attached correctly

            # Select the row first so that subsequent actions apply to it
            self.note_list.select_row(row)
            # Update current_note_path
            self.current_note_path = os.path.join(NOTES_DIR, row.filename)

            # Create a menu model
            menu_model = Gio.Menu.new()
            menu_model.append("Rename", "app.rename_note")
            menu_model.append("Delete", "app.delete_note")

            # Create a PopoverMenu
            popover_menu = Gtk.PopoverMenu.new_from_model(menu_model)
            popover_menu.set_parent(row)  # Attach to the clicked row

            # Map actions to handlers
            # Use self for the actions, as they are methods of NotesApp
            action_group = Gio.SimpleActionGroup()
            action_group.add_action(Gio.SimpleAction.new("rename_note", None))
            action_group.add_action(Gio.SimpleAction.new("delete_note", None))

            action_group.lookup_action("rename_note").connect(
                "activate", self.on_rename_note_action
            )
            action_group.lookup_action("delete_note").connect(
                "activate", self.on_delete_note_action
            )

            self.insert_action_group("app", action_group)  # Register the action group

            # Position and show the popover
            # Use the clicked row as the target for positioning
            popover_menu.popup()

    # Modified handlers to be Gio.Action activated
    def on_rename_note_action(self, action, parameter):
        self.on_rename_note(None)  # Call the existing rename logic

    def on_delete_note_action(self, action, parameter):
        self.on_delete_note(None)  # Call the existing delete logic

    def on_open_with_editor_action(self, action, parameter):
        """Handler for opening the current note with the system's default editor"""
        if not self.current_note_path:
            return

        try:
            Gtk.show_uri(None, f"file://{self.current_note_path}", Gdk.CURRENT_TIME)
        except Exception as e:
            print(f"Error opening note with default editor: {e}")

    def on_rename_note(
        self, menu_item
    ):  # Keep this function, called by the action handler
        if not self.current_note_path:
            return  # No note selected

        current_filename_relative = os.path.relpath(self.current_note_path, NOTES_DIR)
        current_name_without_ext = os.path.splitext(current_filename_relative)[0]
        current_directory_relative = os.path.dirname(current_filename_relative)

        # Create a dialog to get the new name
        dialog = Gtk.Dialog(title="Rename Note", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Rename", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content_area = dialog.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        content_area.append(box)

        label = Gtk.Label(label="Enter new name (without extension):")
        label.set_xalign(0)
        box.append(label)

        entry = Gtk.Entry()
        entry.set_text(current_name_without_ext)
        entry.set_activates_default(True)  # Activate default button on Enter key
        box.append(entry)

        dialog.present()
        dialog.connect(
            "response",
            self.on_rename_dialog_response,
            entry,
            current_filename_relative,
            current_directory_relative,
        )

    def on_rename_dialog_response(
        self,
        dialog,
        response_id,
        entry,
        current_filename_relative,
        current_directory_relative,
    ):
        if response_id == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            dialog.destroy()

            if not new_name:
                print("New name cannot be empty.")
                return

            new_name_with_ext = new_name + EXT

            if current_directory_relative == ".":
                new_filename_relative = new_name_with_ext
            else:
                new_filename_relative = os.path.join(
                    current_directory_relative, new_name_with_ext
                )

            new_full_path = os.path.join(NOTES_DIR, new_filename_relative)

            existing_notes_lower = [n.lower() for n in self.notes]
            if new_filename_relative.lower() in existing_notes_lower:
                print(f"Note with name '{new_name}' already exists.")
                return

            try:
                os.makedirs(os.path.dirname(new_full_path), exist_ok=True)
                shutil.move(self.current_note_path, new_full_path)

                try:
                    self.notes.remove(current_filename_relative)
                except ValueError:
                    pass

                self.notes.append(new_filename_relative)
                self.notes.sort()

                self.current_note_path = new_full_path
                self.refresh_note_list()

            except OSError as e:
                print(f"Error renaming note: {e}")
        else:
            dialog.destroy()

    def on_delete_note(self, menu_item):
        if not self.current_note_path:
            return

        filename = os.path.basename(self.current_note_path)

        # Create a confirmation dialog
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.NONE,
            message_type=Gtk.MessageType.WARNING,
            text="Confirm Delete",
            secondary_text=f"Are you sure you want to delete the note '{filename}'?",
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Delete", Gtk.ResponseType.OK)
        dialog.connect("response", self.on_delete_confirmation_response)
        dialog.show()

    def on_delete_confirmation_response(self, dialog, response):
        dialog.close()

        if response != Gtk.ResponseType.OK:
            return

        if not self.current_note_path:
            return

        filename_relative = os.path.relpath(self.current_note_path, NOTES_DIR)
        deleted_note_was_current = self.current_note_path == os.path.join(
            NOTES_DIR, filename_relative
        )

        try:
            os.remove(self.current_note_path)

            try:
                self.notes.remove(filename_relative)
            except ValueError:
                pass

            if deleted_note_was_current:
                self.current_note_path = None
                self.note_content_view.set_content("")

            self.refresh_note_list()

        except OSError as e:
            print(f"Error deleting note {self.current_note_path}: {e}")

    def load_note_into_view(self):
        """
        Loads the content of the current note into the NoteContentView widget.
        """
        content = ""
        if self.current_note_path and os.path.exists(self.current_note_path):
            try:
                with open(self.current_note_path, "r") as f:
                    content = f.read()
            except OSError as e:
                print(f"Error loading note {self.current_note_path}: {e}")
                # Content remains empty on error

        # Set the content in the NoteContentView widget (defaults to preview mode)
        self.note_content_view.set_content(content, is_editing=False)

    def on_content_view_saved(self, note_content_view, content):
        """
        Handler for the 'content-saved' signal from NoteContentView.
        Saves the content to the current note file.
        """
        if self.current_note_path:
            # Ensure directory exists before saving
            os.makedirs(os.path.dirname(self.current_note_path), exist_ok=True)
            try:
                with open(self.current_note_path, "w") as f:
                    f.write(content)
                # print(f"Saved: {self.current_note_path}") # For debugging
            except OSError as e:
                print(f"Error saving note {self.current_note_path}: {e}")
                # Optionally show an error dialog

    def on_content_view_edit_exited(self, note_content_view):
        """
        Handler for the 'edit-mode-exited' signal from NoteContentView.
        Returns focus to the search entry.
        """
        self.note_list.get_selected_row().grab_focus()
        # self.entry.grab_focus()

    def on_window_key_press(self, controller, keyval, keycode, state, user_data=None):
        # Let the search entry handle its own events when focused
        focused = self.get_focus()
        if focused == self.entry:
            return Gdk.EVENT_PROPAGATE

        # Handle other global shortcuts
        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            selected_row = self.note_list.get_selected_row()
            if selected_row:
                self.note_content_view.enter_edit_mode()
                return Gdk.EVENT_STOP
        elif keyval == Gdk.KEY_Escape:
            self.entry.grab_focus()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE  # Continue propagation for other keys

    def on_sidebar_button_clicked(self, button):
        self.toggle_sidebar()

    def toggle_sidebar(self, *args):
        """Toggles the visibility of the sidebar using Adw.OverlaySplitView."""
        is_visible = self.split_view.get_show_sidebar()
        self.split_view.set_show_sidebar(not is_visible)

    def navigate_to_note(self, note_path):
        """Navigate to a note by its relative path"""
        self.entry.set_text(note_path)  # Clear search
