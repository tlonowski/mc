#!/usr/bin/env python3
import py_cui
import os
import shutil
import stat
import datetime
import pwd
import grp
from functools import lru_cache
import asyncio
import time
import curses

class MidnightCommanderApp:
    """
    A Midnight Commander-style terminal file manager using py-cui
    """
    
    def __init__(self, stdscr):
        self.screen = stdscr
        curses.start_color()
        curses.use_default_colors()
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.curs_set(0)  # Ukryj kursor
        
        # Inicjalizacja par kolorów
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Aktywny panel
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Zaznaczony element
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Katalog
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Normalny tekst
        
        # Zachowaj pozostałe elementy z konstruktora
        self.left_dir = os.path.expanduser('~')
        self.right_dir = os.path.expanduser('~')
        self.active_pane = 'left'
        
        # Set title
        self.master.set_title('Midnight Commander')
        
        # Create variables to track current directories
        self.left_dir = os.path.expanduser('~')
        self.right_dir = os.path.expanduser('~')
        self.active_pane = 'left'
        
        # Create the layout
        self._create_widgets()
        self._set_key_bindings()
        
        # Initial refresh of file lists
        self.refresh_file_lists()

        self._file_info_cache = {}
        self._cache_timeout = 30  # seconds
        self._last_click_time = 0
        self._click_threshold = 0.5  # czas w sekundach między kliknięciami

    def _create_windows(self):
        """Utwórz okna dla interfejsu"""
        h, w = self.screen.getmaxyx()
        
        # Okna paneli plików (70% szerokości)
        panel_width = w // 2 - 1
        panel_height = h - 3  # Zostaw miejsce na pasek statusu i menu
        
        self.left_panel = curses.newwin(panel_height, panel_width, 1, 0)
        self.right_panel = curses.newwin(panel_height, panel_width, 1, panel_width + 1)
        
        # Pasek statusu
        self.status_bar = curses.newwin(1, w, h-2, 0)
        self.status_bar.bkgd(' ', curses.color_pair(1))
        
        # Pasek menu
        self.menu_bar = curses.newwin(1, w, h-1, 0)
        self.menu_bar.bkgd(' ', curses.color_pair(1))
        
    def _create_widgets(self):
        """Create all widgets for the interface"""
        # Create directory path displays
        self.left_path_label = self.master.add_block_label('', 0, 0, row_span=1, column_span=6)
        self.right_path_label = self.master.add_block_label('', 0, 6, row_span=1, column_span=6)
        
        # Create file list widgets with custom colors
        self.left_files_list = self.master.add_scroll_menu('Left Pane', 1, 0, row_span=6, column_span=6)
        self.right_files_list = self.master.add_scroll_menu('Right Pane', 1, 6, row_span=6, column_span=6)
        
        # Ustaw kolory dla list plików
        self.left_files_list.set_color(py_cui.WHITE_ON_BLACK)
        self.right_files_list.set_color(py_cui.WHITE_ON_BLACK)
        
        # Ustaw kolory dla zaznaczenia (wyraźna inwersja)
        self.left_files_list.set_selected_color(py_cui.BLACK_ON_WHITE)
        self.right_files_list.set_selected_color(py_cui.BLACK_ON_WHITE)
        
        # Ustaw kolory dla aktywnego panelu
        self.left_files_list.set_focus_text(py_cui.CYAN_ON_BLACK)
        self.right_files_list.set_focus_text(py_cui.CYAN_ON_BLACK)
        
        # Create status bar for file info
        self.status_bar = self.master.add_block_label('', 7, 0, row_span=1, column_span=12)
        self.status_bar.set_color(py_cui.WHITE_ON_BLUE)
        
        # Create bottom menu bar (przeniesione na dół)
        self.menu_bar = self.master.add_block_label('F1:Help F2:Menu F3:View F4:Edit F5:Copy F6:Move F7:Mkdir F8:Delete F10:Quit', 8, 0, row_span=1, column_span=12)
        self.menu_bar.set_color(py_cui.WHITE_ON_BLUE)
        
        # Set callbacks
        self.left_files_list.add_key_command(py_cui.keys.KEY_ENTER, self.handle_left_selection)
        self.right_files_list.add_key_command(py_cui.keys.KEY_ENTER, self.handle_right_selection)
        
        self.left_files_list.set_on_selection_change_event(self.on_left_selection_change)
        self.right_files_list.set_on_selection_change_event(self.on_right_selection_change)
        
        # Dodaj obsługę myszy do list plików (tylko pojedyncze kliknięcia)
        self.left_files_list.add_mouse_command(py_cui.keys.LEFT_MOUSE_CLICK, self.handle_left_click)
        self.right_files_list.add_mouse_command(py_cui.keys.LEFT_MOUSE_CLICK, self.handle_right_click)
        
        # Set left pane as the initial focus
        self.master.move_focus(self.left_files_list)
        
    def _set_key_bindings(self):
        """Set up key bindings for the application"""
        self.master.add_key_command(py_cui.keys.KEY_F1, self.show_help)
        self.master.add_key_command(py_cui.keys.KEY_F2, self.show_menu)
        self.master.add_key_command(py_cui.keys.KEY_F3, self.view_file)
        self.master.add_key_command(py_cui.keys.KEY_F4, self.edit_file)
        self.master.add_key_command(py_cui.keys.KEY_F5, self.copy_file)
        self.master.add_key_command(py_cui.keys.KEY_F6, self.move_file)
        self.master.add_key_command(py_cui.keys.KEY_F7, self.make_directory)
        self.master.add_key_command(py_cui.keys.KEY_F8, self.delete_file)
        self.master.add_key_command(py_cui.keys.KEY_F10, self.quit_app)
        
        # Tab for switching between panes
        self.master.add_key_command(py_cui.keys.KEY_TAB, self.switch_pane)
    
    def refresh_file_lists(self):
        """
        Zoptymalizowane odświeżanie list plików
        """
        def get_dir_state(directory):
            try:
                files = os.listdir(directory)
                return {
                    'dirs': set(f for f in files if os.path.isdir(os.path.join(directory, f))),
                    'files': set(f for f in files if not os.path.isdir(os.path.join(directory, f)))
                }
            except Exception:
                return {'dirs': set(), 'files': set()}

        # Zachowaj poprzedni stan
        left_previous = self._previous_left_state if hasattr(self, '_previous_left_state') else None
        right_previous = self._previous_right_state if hasattr(self, '_previous_right_state') else None
        
        # Pobierz aktualny stan
        left_current = get_dir_state(self.left_dir)
        right_current = get_dir_state(self.right_dir)
        
        # Aktualizuj tylko jeśli nastąpiły zmiany
        if left_current != left_previous:
            self._update_pane(self.left_files_list, self.left_dir)
            self._previous_left_state = left_current
            
        if right_current != right_previous:
            self._update_pane(self.right_files_list, self.right_dir)
            self._previous_right_state = right_current
    
    def _update_pane(self, pane_list, current_dir):
        """
        Wspólna metoda do aktualizacji panelu z dodatkowymi informacjami
        """
        pane_list.clear()
        try:
            files = os.listdir(current_dir)
            pane_list.add_item('..'.ljust(30) + ' <DIR>')
            
            # Sortowanie i grupowanie
            dirs = sorted([f for f in files if os.path.isdir(os.path.join(current_dir, f))])
            regular_files = sorted([f for f in files if not os.path.isdir(os.path.join(current_dir, f))])
            
            # Dodaj katalogi
            for directory in dirs:
                path = os.path.join(current_dir, directory)
                try:
                    stats = self._get_file_stats(path)
                    mod_time = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
                    perms = self._format_mode(stats.st_mode)
                    truncated_name = self._truncate_filename(directory)
                    display = f"{truncated_name} <DIR> {perms} {mod_time}"  # Poprawiona linia
                    pane_list.add_item(display)
                except:
                    truncated_name = self._truncate_filename(directory)
                    pane_list.add_item(f"{truncated_name} <DIR>")
            
            # Dodaj pliki
            for file in regular_files:
                path = os.path.join(current_dir, file)
                try:
                    stats = self._get_file_stats(path)
                    size = self._format_size(stats.st_size)
                    mod_time = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
                    perms = self._format_mode(stats.st_mode)
                    truncated_name = self._truncate_filename(file)
                    display = f"{truncated_name} {size:>8} {perms} {mod_time}"  # Poprawiona linia
                    pane_list.add_item(display)
                except:
                    truncated_name = self._truncate_filename(file)
                    pane_list.add_item(f"{truncated_name}")
                    
        except Exception as e:
            self.show_error(f"Error accessing directory: {str(e)}")
    
    def _update_pane_with_pagination(self, pane_list, current_dir, page_size=100):
        """
        Aktualizacja panelu ze stronnicowaniem
        """
        pane_list.clear()
        try:
            with os.scandir(current_dir) as it:
                entries = list(it)
                total_pages = (len(entries) + page_size - 1) // page_size
                
                dirs = sorted((e for e in entries if e.is_dir()), key=lambda x: x.name)
                files = sorted((e for e in entries if e.is_file()), key=lambda x: x.name)
                
                pane_list.add_item('..')
                
                for entry in dirs[:page_size]:
                    pane_list.add_item(f"[DIR] {entry.name}")
                for entry in files[:page_size]:
                    pane_list.add_item(entry.name)
                    
                if total_pages > 1:
                    pane_list.add_item(f"--- Page 1/{total_pages} ---")
                    
        except Exception as e:
            self.show_error(f"Error accessing directory: {str(e)}")
    
    def handle_left_selection(self):
        """Handle file/directory selection in the left pane"""
        selected = self.left_files_list.get()
        if not selected:
            return
            
        # Wyciągnij nazwę pliku/katalogu (pierwsze 30 znaków zawierają nazwę)
        name = selected[:30].strip()
        
        if name == '..':
            # Zapamiętaj nazwę bieżącego katalogu
            current_dir_name = os.path.basename(self.left_dir)
            # Go up one directory
            self.left_dir = os.path.dirname(self.left_dir)
            self.refresh_file_lists()
            # Ustaw kursor na poprzednim katalogu
            self._set_cursor_on_item(self.left_files_list, current_dir_name)
        elif '<DIR>' in selected:
            # Enter the selected directory
            new_path = os.path.join(self.left_dir, name)
            if os.path.exists(new_path) and os.path.isdir(new_path):
                self.left_dir = new_path
                self.refresh_file_lists()
        else:
            # It's a file, show file info
            file_path = os.path.join(self.left_dir, name)
            self.show_file_info(file_path)

    def handle_right_selection(self):
        """Handle file/directory selection in the right pane"""
        selected = self.right_files_list.get()
        if not selected:
            return
            
        # Wyciągnij nazwę pliku/katalogu (pierwsze 30 znaków zawierają nazwę)
        name = selected[:30].strip()
        
        if name == '..':
            # Zapamiętaj nazwę bieżącego katalogu
            current_dir_name = os.path.basename(self.right_dir)
            # Go up one directory
            self.right_dir = os.path.dirname(self.right_dir)
            self.refresh_file_lists()
            # Ustaw kursor na poprzednim katalogu
            self._set_cursor_on_item(self.right_files_list, current_dir_name)
        elif '<DIR>' in selected:
            # Enter the selected directory
            new_path = os.path.join(self.right_dir, name)
            if os.path.exists(new_path) and os.path.isdir(new_path):
                self.right_dir = new_path
                self.refresh_file_lists()
        else:
            # It's a file, show file info
            file_path = os.path.join(self.right_dir, name)
            self.show_file_info(file_path)

    def _set_cursor_on_item(self, pane_list, item_name):
        """
        Ustawia kursor na elemencie o podanej nazwie
        
        Args:
            pane_list: Lista plików (lewy lub prawy panel)
            item_name (str): Nazwa elementu do znalezienia
        """
        items = pane_list.get_item_list()
        for i, item in enumerate(items):
            if item_name in item:  # Sprawdza czy nazwa jest częścią wiersza
                pane_list.set_selected_item_index(i)
                break

    def on_left_selection_change(self, new_selection):
        """Handle selection change in the left pane"""
        self.active_pane = 'left'
        if new_selection:
            if new_selection == '..':
                self.status_bar.set_text("Parent Directory")  # Zmiana z set_title na set_text
            elif '<DIR>' in new_selection:
                name = new_selection[:30].strip()  # Wyciągnij nazwę z pierwszych 30 znaków
                dir_path = os.path.join(self.left_dir, name)
                self.show_file_info(dir_path)
            else:
                name = new_selection[:30].strip()  # Wyciągnij nazwę z pierwszych 30 znaków
                file_path = os.path.join(self.left_dir, name)
                self.show_file_info(file_path)

    def on_right_selection_change(self, new_selection):
        """Handle selection change in the right pane"""
        self.active_pane = 'right'
        if new_selection:
            if new_selection == '..':
                self.status_bar.set_text("Parent Directory")  # Zmiana z set_title na set_text
            elif '<DIR>' in new_selection:
                name = new_selection[:30].strip()  # Wyciągnij nazwę z pierwszych 30 znaków
                dir_path = os.path.join(self.right_dir, name)
                self.show_file_info(dir_path)
            else:
                name = new_selection[:30].strip()  # Wyciągnij nazwę z pierwszych 30 znaków
                file_path = os.path.join(self.right_dir, name)
                self.show_file_info(file_path)

    def show_file_info(self, file_path):
        """Show information about a file or directory"""
        try:
            stats = self._get_file_stats(file_path)
            file_size = self._format_size(stats.st_size)
            mod_time = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                owner = pwd.getpwuid(stats.st_uid).pw_name
            except KeyError:
                owner = str(stats.st_uid)
                
            try:
                group = grp.getgrgid(stats.st_gid).gr_name
            except KeyError:
                group = str(stats.st_gid)
                
            mode = self._format_mode(stats.st_mode)
            
            if os.path.isdir(file_path):
                type_str = "Directory"
            else:
                type_str = "File"
                
            info = f"{type_str}: {os.path.basename(file_path)} | Size: {file_size} | Mode: {mode} | Owner: {owner}:{group} | Modified: {mod_time}"
            # Zmiana z set_title na set_text
            self.status_bar.set_text(info)
        except Exception as e:
            self.status_bar.set_text(f"Error: {str(e)}")
    
    @lru_cache(maxsize=1000)
    def _get_file_stats(self, file_path):
        """
        Cached file stats
        """
        return os.stat(file_path)

    def _format_size(self, size_in_bytes):
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.2f} PB"
    
    def _format_mode(self, mode):
        """Format file mode in a readable format (like ls -l)"""
        perms = '-'
        if stat.S_ISDIR(mode):
            perms = 'd'
        elif stat.S_ISLNK(mode):
            perms = 'l'
            
        for entity in ['USR', 'GRP', 'OTH']:
            for perm in ['R', 'W', 'X']:
                if mode & getattr(stat, f'S_I{perm}{entity}'):
                    perms += {'R': 'r', 'W': 'w', 'X': 'x'}[perm]
                else:
                    perms += '-'
                    
        return perms
    
    def switch_pane(self):
        """Switch focus between left and right panes"""
        if self.active_pane == 'left':
            self.master.move_focus(self.right_files_list)
            self.active_pane = 'right'
        else:
            self.master.move_focus(self.left_files_list)
            self.active_pane = 'left'
    
    def get_active_pane_info(self):
        """Get current directory and selected item for the active pane"""
        if self.active_pane == 'left':
            current_dir = self.left_dir
            selected = self.left_files_list.get()
            other_dir = self.right_dir
        else:
            current_dir = self.right_dir
            selected = self.right_files_list.get()
            other_dir = self.left_dir
            
        if selected and selected.startswith('[DIR]'):
            selected = selected[6:]  # Remove the [DIR] prefix
            
        return current_dir, selected, other_dir
    
    def show_help(self):
        """Display help information"""
        help_text = """
Midnight Commander-style File Manager
----------------------------------------------------------
Key Bindings:
F1 - Help (this screen)
F2 - Menu
F3 - View file
F4 - Edit file
F5 - Copy file/directory
F6 - Move file/directory
F7 - Create directory
F8 - Delete file/directory
F10 - Quit
Tab - Switch between panes
Enter - Open directory/file

Mouse Controls:
- Single click to select and focus
- Double click to open/enter
- Click on panel to switch focus

Navigation:
- Use arrow keys to navigate
- Enter to open directories or files
- Select '..' to go up one directory
"""
        self.master.show_message_box('Help', help_text)
    
    def show_menu(self):
        """Show a dropdown menu with options"""
        menu_items = ['Copy', 'Move', 'Delete', 'View', 'Edit', 'New Directory', 'Refresh', 'Quit']
        self.master.show_menu_popup('Menu', menu_items, self._handle_menu_selection)
    
    def _handle_menu_selection(self, option):
        """Handle menu option selection"""
        if option == 'Copy':
            self.copy_file()
        elif option == 'Move':
            self.move_file()
        elif option == 'Delete':
            self.delete_file()
        elif option == 'View':
            self.view_file()
        elif option == 'Edit':
            self.edit_file()
        elif option == 'New Directory':
            self.make_directory()
        elif option == 'Refresh':
            self.refresh_file_lists()
        elif option == 'Quit':
            self.quit_app()
    
    def view_file(self):
        """View the contents of a file"""
        current_dir, selected, _ = self.get_active_pane_info()
        if selected and selected != '..' and not selected.startswith('[DIR]'):
            file_path = os.path.join(current_dir, selected)
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                self.master.show_text_box('View: ' + os.path.basename(file_path), content)
            except Exception as e:
                self.show_error(f"Error viewing file: {str(e)}")
        else:
            self.show_error("Please select a file to view")
    
    def edit_file(self):
        """Edit the contents of a file"""
        current_dir, selected, _ = self.get_active_pane_info()
        if selected and selected != '..' and not selected.startswith('[DIR]'):
            file_path = os.path.join(current_dir, selected)
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                # Create a text box for editing with a callback to save changes
                def save_callback(new_content):
                    try:
                        with open(file_path, 'w') as f:
                            f.write(new_content)
                        self.master.show_message_box('Success', f'File saved: {os.path.basename(file_path)}')
                        self.refresh_file_lists()
                    except Exception as e:
                        self.show_error(f"Error saving file: {str(e)}")
                
                editor = self.master.show_text_box_popup('Edit: ' + os.path.basename(file_path), content)
                editor.add_key_command(py_cui.keys.KEY_CTRL_S, save_callback)
                # Add a status message for the editor
                self.master.show_status_bar_message('Ctrl+S to save, Esc to cancel')
            except Exception as e:
                self.show_error(f"Error editing file: {str(e)}")
        else:
            self.show_error("Please select a file to edit")
    
    def copy_file(self):
        """Copy a file or directory to the other pane"""
        current_dir, selected, other_dir = self.get_active_pane_info()
        
        if not selected or selected == '..':
            self.show_error("Please select a file or directory to copy")
            return
        
        source_path = os.path.join(current_dir, selected)
        dest_path = os.path.join(other_dir, selected)
            
        # Ask for confirmation
        confirm_message = f"Copy '{selected}' to {other_dir}?"
        self.master.show_yes_no_popup('Confirm Copy', confirm_message, self._do_copy, [source_path, dest_path])
    
    def _do_copy(self, paths):
        """Perform the actual copy operation"""
        source_path, dest_path = paths
        asyncio.run(self._do_copy_async(source_path, dest_path))
    
    async def _do_copy_async(self, source_path, dest_path):
        """
        Asynchroniczne kopiowanie plików
        """
        try:
            if os.path.isdir(source_path):
                await asyncio.to_thread(shutil.copytree, source_path, dest_path)
            else:
                await asyncio.to_thread(shutil.copy2, source_path, dest_path)
            
            self.master.show_message_box('Success', f'Copied to {os.path.basename(dest_path)}')
            self.refresh_file_lists()
        except Exception as e:
            self.show_error(f"Error copying: {str(e)}")
    
    def move_file(self):
        """Move a file or directory to the other pane"""
        current_dir, selected, other_dir = self.get_active_pane_info()
        
        if not selected or selected == '..':
            self.show_error("Please select a file or directory to move")
            return
        
        source_path = os.path.join(current_dir, selected)
        dest_path = os.path.join(other_dir, selected)
            
        # Ask for confirmation
        confirm_message = f"Move '{selected}' to {other_dir}?"
        self.master.show_yes_no_popup('Confirm Move', confirm_message, self._do_move, [source_path, dest_path])
    
    def _do_move(self, paths):
        """Perform the actual move operation"""
        source_path, dest_path = paths
        try:
            if os.path.exists(dest_path):
                # If destination exists, create a unique name
                base_name, ext = os.path.splitext(os.path.basename(source_path))
                i = 1
                new_name = f"{base_name}_moved{i}{ext}"
                while os.path.exists(os.path.join(os.path.dirname(dest_path), new_name)):
                    i += 1
                    new_name = f"{base_name}_moved{i}{ext}"
                dest_path = os.path.join(os.path.dirname(dest_path), new_name)
            
            # Move the file or directory
            shutil.move(source_path, dest_path)
            
            self.master.show_message_box('Success', f'Moved to {os.path.basename(dest_path)}')
            self.refresh_file_lists()
        except Exception as e:
            self.show_error(f"Error moving: {str(e)}")
    
    def delete_file(self):
        """Delete a file or directory"""
        current_dir, selected, _ = self.get_active_pane_info()
        
        if not selected or selected == '..':
            self.show_error("Please select a file or directory to delete")
            return
        
        file_path = os.path.join(current_dir, selected)
            
        # Ask for confirmation
        confirm_message = f"Delete '{selected}'? This cannot be undone!"
        self.master.show_yes_no_popup('Confirm Delete', confirm_message, self._do_delete, file_path)
    
    def _do_delete(self, file_path):
        """Perform the actual delete operation"""
        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
            
            self.master.show_message_box('Success', 'Deleted successfully')
            self.refresh_file_lists()
        except Exception as e:
            self.show_error(f"Error deleting: {str(e)}")
    
    def make_directory(self):
        """Create a new directory in the active pane"""
        current_dir, _, _ = self.get_active_pane_info()
        
        # Ask for the directory name
        self.master.show_text_box_popup('New Directory', 'Enter directory name:', self._do_make_directory)
    
    def _do_make_directory(self, dir_name):
        """Perform the actual directory creation"""
        current_dir, _, _ = self.get_active_pane_info()
        
        try:
            if not dir_name or dir_name.isspace():
                self.show_error("Directory name cannot be empty")
                return
            
            # Create the directory
            new_dir_path = os.path.join(current_dir, dir_name)
            os.makedirs(new_dir_path)
            
            self.master.show_message_box('Success', f'Created directory: {dir_name}')
            self.refresh_file_lists()
        except Exception as e:
            self.show_error(f"Error creating directory: {str(e)}")
    
    def quit_app(self):
        """Exit the application"""
        # Ask for confirmation
        self.master.show_yes_no_popup('Confirm Exit', 'Are you sure you want to quit?', self._do_quit)
    
    def _do_quit(self, _=None):
        """Perform the actual quit"""
        exit(0)
        
    def show_error(self, message):
        """Display an error message"""
        self.master.show_error_popup('Error', message)

    def _get_file_info(self, file_path):
        """
        Get file info with caching
        """
        current_time = time.time()
        if file_path in self._file_info_cache:
            cached_info, timestamp = self._file_info_cache[file_path]
            if current_time - timestamp < self._cache_timeout:
                return cached_info
                                
        file_info = self._compute_file_info(file_path)
        self._file_info_cache[file_path] = (file_info, current_time)
        return file_info

    def _truncate_filename(self, filename, max_length=30):
        """
        Skraca nazwę pliku/katalogu zachowując początek i koniec
        
        Args:
            filename (str): Nazwa pliku do skrócenia
            max_length (int): Maksymalna długość (domyślnie 30)
        
        Returns:
            str: Skrócona nazwa pliku
        """
        if len(filename) <= max_length:
            return filename.ljust(max_length)
        
        # Zachowaj rozszerzenie pliku
        name, ext = os.path.splitext(filename)
        if ext:
            # Zostaw 3 znaki na '...' i co najmniej 5 znaków z nazwy
            avail_length = max_length - len(ext) - 3
            if avail_length >= 5:
                return f"{name[:avail_length-2]}...{ext}".ljust(max_length)
            else:
                return f"{name[:max_length-3]}...".ljust(max_length)
        else:
            # Dla katalogów (bez rozszerzenia)
            return f"{filename[:max_length-3]}...".ljust(max_length)

    def handle_left_click(self):
        """Obsługa kliknięcia w lewym panelu z detekcją podwójnego kliknięcia"""
        current_time = time.time()
        if current_time - self._last_click_time < self._click_threshold:
            # Podwójne kliknięcie
            self.handle_left_selection()
        else:
            # Pojedyncze kliknięcie
            self.active_pane = 'left'
            self.master.move_focus(self.left_files_list)
            selected = self.left_files_list.get()
            if selected:
                self.on_left_selection_change(selected)
        self._last_click_time = current_time

    def handle_right_click(self):
        """Obsługa kliknięcia w prawym panelu z detekcją podwójnego kliknięcia"""
        current_time = time.time()
        if current_time - self._last_click_time < self._click_threshold:
            # Podwójne kliknięcie
            self.handle_right_selection()
        else:
            # Pojedyncze kliknięcie
            self.active_pane = 'right'
            self.master.move_focus(self.right_files_list)
            selected = self.right_files_list.get()
            if selected:
                self.on_right_selection_change(selected)
        self._last_click_time = current_time

    def _draw_panel(self, window, items, selected_idx, is_active):
        """Rysuj panel z listą plików"""
        window.clear()
        h, w = window.getmaxyx()
        
        for idx, item in enumerate(items):
            if idx >= h:
                break
                
            # Wybierz kolor
            if idx == selected_idx:
                attr = curses.color_pair(2)
            elif '<DIR>' in item:
                attr = curses.color_pair(3)
            else:
                attr = curses.color_pair(4)
            
            # Dodaj ramkę dla aktywnego panelu
            if is_active:
                window.box()
            
            # Wyświetl element
            window.addstr(idx + 1, 1, item[:w-2], attr)
        
        window.refresh()

    def run(self):
        """Główna pętla programu"""
        while True:
            self._draw_screen()
            ch = self.screen.getch()
            
            if ch == ord('q'):
                break
            elif ch == ord('\t'):
                self.switch_pane()
            elif ch == curses.KEY_F1:
                self.show_help()
            # ...obsługa pozostałych klawiszy...

def main():
    """Initialize and run the application"""
    def run_app(stdscr):
        app = MidnightCommanderApp(stdscr)
        app.run()
    
    curses.wrapper(run_app)

if __name__ == "__main__":
    main()
