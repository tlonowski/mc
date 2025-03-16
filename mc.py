#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Midnight Commander Clone
Copyright (C) 2024 Tomasz Lonowski

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import curses
import os
import shutil
import stat
import datetime
import pwd
import grp
from functools import lru_cache
import subprocess
import time
from contextlib import contextmanager

class MidnightCommander:
    __slots__ = ['screen', 'top_bar', 'left_panel', 'right_panel', 'status_bar', 'menu_bar',
                 'command_line', 'left_dir', 'right_dir', 'active_pane', 'left_selected',
                 'right_selected', 'left_offset', 'right_offset', 'left_files', 'right_files',
                 'escape_pressed', 'escape_time', 'command_line_content', 'error_handler']

    def __init__(self, screen):
        self.screen = screen
        self.setup_screen()
        
        # Najpierw utwórz okna
        self.create_windows()
        
        # Następnie zainicjalizuj pozostałe atrybuty
        self.left_dir = os.path.expanduser('~')
        self.right_dir = os.path.expanduser('~')
        self.active_pane = 'left'
        self.left_selected = 0
        self.right_selected = 0
        self.left_offset = 0
        self.right_offset = 0
        self.left_files = []
        self.right_files = []
        self.escape_pressed = False
        self.escape_time = 0
        self.command_line_content = ""
        
        # Na końcu utwórz error handler
        self.error_handler = MCError(self.screen, self.status_bar)

    @property
    def current_dir(self):
        """Aktualny katalog"""
        return self.left_dir if self.active_pane == 'left' else self.right_dir

    @property
    def current_files(self):
        """Lista plików w aktualnym katalogu"""
        return self.left_files if self.active_pane == 'left' else self.right_files

    @property
    def current_selected(self):
        """Aktualnie wybrany element"""
        return self.left_selected if self.active_pane == 'left' else self.right_selected

    def setup_screen(self):
        """Konfiguracja ekranu"""
        # Podstawowa konfiguracja
        curses.start_color()
        curses.use_default_colors()
        curses.curs_set(0)  # Ukryj kursor
        
        # Włącz obsługę klawiszy specjalnych
        self.screen.keypad(1)
        
        # Wyłącz buforowanie wejścia
        curses.raw()
        curses.noecho()
        
        # Definicja kolorów
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)    # Aktywny panel
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)   # Zaznaczony element
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Katalog
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # Zwykły tekst
        curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLUE)   # Menu

    def create_windows(self):
        """Tworzenie okien interfejsu"""
        height, width = self.screen.getmaxyx()
        
        # Górny pasek
        self.top_bar = curses.newwin(1, width, 0, 0)
        self.top_bar.bkgd(' ', curses.color_pair(1))
        
        # Panele plików (zmniejsz wysokość o 1 dla linii komend)
        panel_height = height - 4  # -4 zamiast -3 (status, menu, command line)
        panel_width = width // 2
        self.left_panel = curses.newwin(panel_height, panel_width, 1, 0)
        self.right_panel = curses.newwin(panel_height, panel_width, 1, panel_width)
        
        # Linia komend
        self.command_line = curses.newwin(1, width, height-3, 0)
        self.command_line.bkgd(' ', curses.color_pair(4))
        
        # Pasek statusu
        self.status_bar = curses.newwin(1, width, height-2, 0)
        self.status_bar.bkgd(' ', curses.color_pair(1))
        
        # Menu
        self.menu_bar = curses.newwin(1, width, height-1, 0)
        self.menu_bar.bkgd(' ', curses.color_pair(5))

    def refresh_directory_content(self, directory):
        """Zoptymalizowany odczyt zawartości katalogu"""
        try:
            files = ['..']
            with os.scandir(directory) as entries:
                items = [(entry.name, entry.is_dir()) for entry in entries]
                dirs = sorted(name for name, is_dir in items if is_dir)
                regular_files = sorted(name for name, is_dir in items if not is_dir)
                files.extend(dirs)
                files.extend(regular_files)
            return files
        except (PermissionError, FileNotFoundError, Exception) as e:
            self.error_handler.show_error(str(e))
            return ['..']

    def draw_panel(self, panel, files, selected, offset, is_active):
        """Rysowanie panelu z plikami z obsługą przewijania i szczegółów"""
        panel.clear()
        height, width = panel.getmaxyx()
        visible_height = height - 2
        current_dir = self.left_dir if self.active_pane == 'left' else self.right_dir
        
        # Rysuj ramkę z odpowiednim kolorem dla aktywnego panelu
        if is_active:
            panel.attron(curses.color_pair(1))  # Aktywny panel - biały na niebieskim
            panel.box()
            panel.attroff(curses.color_pair(1))
            # Dodaj znacznik aktywnego panelu
            panel.addstr(0, 2, "[ AKTYWNY ]", curses.color_pair(1))
        else:
            panel.attron(curses.color_pair(4))  # Nieaktywny panel - biały na czarnym
            panel.box()
            panel.attroff(curses.color_pair(4))
        
        # Dodaj wskaźniki przewijania
        if offset > 0:
            panel.addstr(0, width//2, "▲", curses.color_pair(1) if is_active else curses.color_pair(4))
        if offset + visible_height < len(files):
            panel.addstr(height-1, width//2, "▼", curses.color_pair(1) if is_active else curses.color_pair(4))
        
        # Wyświetl pliki
        for idx, file in enumerate(files[offset:offset + visible_height]):
            try:
                full_path = os.path.join(current_dir, file)
                stats = os.stat(full_path) if file != '..' else os.stat(current_dir)
                
                # Format: [Nazwa 30] [Rozmiar 10] [Atrybuty 10] [Data 16]
                name = file
                if file != '..':
                    if os.path.isdir(full_path):
                        name += '/'
                        size = '<DIR>'
                    else:
                        size = self.format_size(stats.st_size)
                else:
                    size = '<DIR>'
                
                mode = self.format_mode(stats.st_mode)
                mtime = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
                
                # Skróć nazwę jeśli jest za długa
                name_width = 30
                if len(name) > name_width:
                    name = name[:name_width-3] + '...'
                else:
                    name = name.ljust(name_width)
                
                # Wybierz kolor - poprawiona logika zaznaczenia
                if idx + offset == selected:
                    attr = curses.color_pair(2)  # Zawsze używaj tego samego koloru dla zaznaczenia
                elif os.path.isdir(full_path) or file == '..':
                    attr = curses.color_pair(3)
                else:
                    attr = curses.color_pair(4)
                
                # Przygotuj pełny wiersz
                line = f"{name} {size:>10} {mode} {mtime}"
                if len(line) > width-2:
                    line = line[:width-5] + '...'
                
                panel.addstr(idx+1, 1, line, attr)
                
            except (OSError, curses.error):
                # W przypadku błędu wyświetl tylko nazwę
                name = file[:width-5] + '...' if len(file) > width-5 else file
                panel.addstr(idx+1, 1, name, curses.color_pair(4))
        
        panel.refresh()

    def draw_status_bar(self, path, file):
        """Rysowanie paska statusu"""
        try:
            # Pobierz szerokość okna
            _, width = self.status_bar.getmaxyx()
            
            if file == '..':
                status = "Parent Directory"
            else:
                try:
                    full_path = os.path.join(path, file)
                    stats = os.stat(full_path)
                    size = self.format_size(stats.st_size)
                    mode = self.format_mode(stats.st_mode)
                    mtime = datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
                    status = f"{file} | {size} | {mode} | {mtime}"
                except:
                    status = "Error reading file info"
            
            # Upewnij się, że tekst nie przekracza szerokości okna
            if len(status) > width:
                status = status[:width-1]
            else:
                status = status.ljust(width-1)
                
            self.status_bar.addstr(0, 0, status, curses.color_pair(1))
            self.status_bar.refresh()
        except curses.error:
            pass  # Ignoruj błędy związane z rozmiarem okna

    def format_size(self, size):
        """Formatowanie rozmiaru pliku"""
        for unit in ['B', 'K', 'M', 'G', 'T']:
            if size < 1024:
                return f"{size:3.1f}{unit}"
            size /= 1024
        return f"{size:.1f}P"

    def format_mode(self, mode):
        """Formatowanie uprawnień pliku"""
        perms = '-'
        if stat.S_ISDIR(mode): perms = 'd'
        elif stat.S_ISLNK(mode): perms = 'l'
        
        for entity in ['USR', 'GRP', 'OTH']:
            for perm in ['R', 'W', 'X']:
                if mode & getattr(stat, f'S_I{perm}{entity}'):
                    perms += {'R':'r', 'W':'w', 'X':'x'}[perm]
                else:
                    perms += '-'
        return perms

    @lru_cache(maxsize=1000)
    def get_dir_size(self, path):
        """Oblicz rozmiar katalogu (z cache)"""
        try:
            total = 0
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_file():
                            total += entry.stat().st_size
                        elif entry.is_dir():
                            total += self.get_dir_size(entry.path)
                    except (PermissionError, FileNotFoundError):
                        continue
            return total
        except (PermissionError, FileNotFoundError):
            return 0

    @lru_cache(maxsize=1000)
    def get_file_info(self, path):
        """Cache dla informacji o plikach"""
        try:
            stats = os.stat(path)
            return {
                'size': self.format_size(stats.st_size),
                'mode': self.format_mode(stats.st_mode),
                'mtime': datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
            }
        except OSError:
            return None

    def draw_menu(self):
        """Rysowanie menu"""
        try:
            # Pobierz szerokość okna
            _, width = self.menu_bar.getmaxyx()
            menu = "F1 Help  F2 Menu  F3 View  F4 Edit  F5 Copy  F6 Move  F7 Mkdir  F8 Del  F10 Quit"
            
            # Upewnij się, że tekst nie przekracza szerokości okna
            if len(menu) > width:
                menu = menu[:width-1]
            else:
                menu = menu.ljust(width-1)
                
            self.menu_bar.addstr(0, 0, menu, curses.color_pair(5))
            self.menu_bar.refresh()
        except curses.error:
            pass  # Ignoruj błędy związane z rozmiarem okna

    def draw_screen(self):
        """Odświeżanie całego ekranu"""
        try:
            # Najpierw odśwież listy plików
            if not self.left_files:
                self.left_files = self.refresh_directory_content(self.left_dir)
            if not self.right_files:
                self.right_files = self.refresh_directory_content(self.right_dir)
            
            # Sprawdź czy listy nie są puste
            if not self.left_files:
                self.left_files = ['..']
            if not self.right_files:
                self.right_files = ['..']
                
            # Upewnij się, że indeksy są poprawne
            if self.left_selected >= len(self.left_files):
                self.left_selected = len(self.left_files) - 1
            if self.right_selected >= len(self.right_files):
                self.right_selected = len(self.right_files) - 1
            
            # Rysuj panele
            self.draw_panel(self.left_panel, self.left_files, self.left_selected, 
                        self.left_offset, self.active_pane == 'left')
            self.draw_panel(self.right_panel, self.right_files, self.right_selected, 
                        self.right_offset, self.active_pane == 'right')
            
            # Rysuj paski i inne elementy
            if self.active_pane == 'left':
                self.draw_status_bar(self.left_dir, self.left_files[self.left_selected])
            else:
                self.draw_status_bar(self.right_dir, self.right_files[self.right_selected])
            
            self.draw_command_line()  # Dodane rysowanie linii komend
            self.draw_menu()
            self.screen.refresh()
        except Exception as e:
            # W przypadku błędu, wyświetl informację w pasku statusu
            self.status_bar.clear()
            self.status_bar.addstr(0, 0, f"Error: {str(e)}", curses.color_pair(1))
            self.status_bar.refresh()

    def view_file(self):
        """Podgląd pliku w systemowym podglądzie"""
        if self.active_pane == 'left':
            selected_file = self.left_files[self.left_selected]
            current_dir = self.left_dir
        else:
            selected_file = self.right_files[self.right_selected]
            current_dir = self.right_dir
            
        if selected_file != '..' and not os.path.isdir(os.path.join(current_dir, selected_file)):
            file_path = os.path.join(current_dir, selected_file)
            try:
                # Zapisz aktualny stan terminala
                curses.def_prog_mode()
                curses.endwin()
                
                # Użyj systemowego podglądu (Quick Look na macOS)
                subprocess.run(['qlmanage', '-p', file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Przywróć terminal
                curses.reset_prog_mode()
                self.screen.refresh()
                self.draw_screen()
            except Exception as e:
                self.status_bar.clear()
                self.status_bar.addstr(0, 0, f"Error viewing file: {str(e)}", curses.color_pair(1))
                self.status_bar.refresh()

    def edit_file(self):
        """Edycja pliku w systemowym edytorze"""
        if self.active_pane == 'left':
            selected_file = self.left_files[self.left_selected]
            current_dir = self.left_dir
        else:
            selected_file = self.right_files[self.right_selected]
            current_dir = self.right_dir
            
        if selected_file != '..' and not os.path.isdir(os.path.join(current_dir, selected_file)):
            file_path = os.path.join(current_dir, selected_file)
            try:
                # Zapisz aktualny stan terminala
                curses.def_prog_mode()
                curses.endwin()
                
                # Otwórz plik używając systemowego polecenia 'open' (macOS)
                subprocess.run(['open', file_path])
                
                # Poczekaj chwilę przed przywróceniem interfejsu
                time.sleep(0.5)
                
                # Przywróć terminal
                curses.reset_prog_mode()
                self.screen.refresh()
                self.draw_screen()
            except Exception as e:
                self.status_bar.clear()
                self.status_bar.addstr(0, 0, f"Error editing file: {str(e)}", curses.color_pair(1))
                self.status_bar.refresh()

    def copy_item(self):
        """Kopiowanie pliku lub katalogu"""
        try:
            # Pobierz źródłowy plik/katalog
            if self.active_pane == 'left':
                src_file = self.left_files[self.left_selected]
                src_dir = self.left_dir
                dst_dir = self.right_dir
            else:
                src_file = self.right_files[self.right_selected]
                src_dir = self.right_dir
                dst_dir = self.left_dir
                
            if src_file == '..':
                return
                
            src_path = os.path.join(src_dir, src_file)
            dst_path = os.path.join(dst_dir, src_file)
            
            # Utwórz komunikat z podziałem na linie
            message = (
                "Czy chcesz skopiować?\n"
                f"{src_path}\n"
                "do\n"
                f"{dst_path}"
            )
            
            # Wyświetl okno dialogowe
            msgbox = MessageBox(
                self.screen,
                "Kopiowanie",
                message,
                ["Tak", "Nie", "Anuluj"]
            )
            
            result = msgbox.show()
            if result is True:  # Tak
                # Wykonaj kopiowanie
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_path, dst_path)
                # Odśwież listy plików
                if self.active_pane == 'left':
                    self.right_files = self.refresh_directory_content(self.right_dir)
                else:
                    self.left_files = self.refresh_directory_content(self.left_dir)
                
                # Pokaż komunikat o sukcesie
                self.status_bar.clear()
                self.status_bar.addstr(0, 0, "Kopiowanie zakończone pomyślnie", curses.color_pair(1))
                self.status_bar.refresh()
            elif result is None:  # Anuluj
                self.draw_screen()
                return
            
            self.draw_screen()
                
        except PermissionError:
            self.error_handler.show_error("Brak uprawnień do wykonania operacji")
        except FileExistsError:
            self.error_handler.show_error("Plik lub katalog już istnieje")
        except FileNotFoundError:
            self.error_handler.show_error("Plik lub katalog nie istnieje")
        except OSError as e:
            self.error_handler.show_error(f"Błąd systemu operacyjnego: {str(e)}")
        except Exception as e:
            self.error_handler.show_error(f"Nieoczekiwany błąd: {str(e)}")

    def quit_app(self):
        """Obsługa wyjścia z aplikacji"""
        try:
            msgbox = MessageBox(
                self.screen,
                "Wyjście",
                "Czy na pewno chcesz wyjść z programu? (t/n)"
            )
            
            if msgbox.show():
                exit(0)
            else:
                self.draw_screen()
                
        except Exception as e:
            self.status_bar.clear()
            self.status_bar.addstr(0, 0, f"Błąd: {str(e)}", curses.color_pair(1))
            self.status_bar.refresh()

    def handle_input(self):
        """Obsługa wejścia z klawiatury (mysz tymczasowo usunięta)"""
        try:
            key = self.screen.getch()
            current_time = time.time()
            
            # Obsługa ESC
            if key == 27:  # ESC
                self.escape_pressed = True
                self.escape_time = current_time
                return True
                
            # Obsługa sekwencji po ESC
            if self.escape_pressed and current_time - self.escape_time < 0.5:
                if key == ord('3'):
                    self.view_file()
                    self.escape_pressed = False
                    return True
                elif key == ord('4'):
                    self.edit_file()
                    self.escape_pressed = False
                    return True
                elif key == ord('5'):
                    self.copy_item()
                    self.escape_pressed = False
                    return True
                elif key == ord('0'):
                    self.quit_app()
                    self.escape_pressed = False
                    return True
            
            if current_time - self.escape_time > 0.5:
                self.escape_pressed = False

            # Usunięto obsługę myszy (KEY_MOUSE)
            # if key == curses.KEY_MOUSE:
            #     ...  # (Kod obsługi myszy usunięty)
            
            # Obsługa klawiszy specjalnych
            elif key == ord('\t'):
                self.active_pane = 'right' if self.active_pane == 'left' else 'left'
            elif key == curses.KEY_UP:
                self._handle_up_key()
            elif key == curses.KEY_DOWN:
                self._handle_down_key()
            elif key == ord('\n'):
                if self.command_line_content.strip():
                    self._execute_command(self.command_line_content)
                    self.command_line_content = ""
                else:
                    self.handle_enter()
            elif key == curses.KEY_F3:
                self.view_file()
            elif key == curses.KEY_F4:
                self.edit_file()
            elif key == curses.KEY_F5:
                self.copy_item()
            elif key == curses.KEY_F10:
                self.quit_app()
            elif key == curses.KEY_BACKSPACE or key == 127:
                self.command_line_content = self.command_line_content[:-1]
            elif 32 <= key <= 126:
                self.command_line_content += chr(key)
            
            self.draw_screen()
            return True
            
        except Exception as e:
            self.status_bar.clear()
            self.status_bar.addstr(0, 0, f"Input error: {str(e)}", curses.color_pair(1))
            self.status_bar.refresh()
            return True

    def _execute_command(self, command):
        """Wykonanie polecenia z linii komend z pełną obsługą shella"""
        try:
            # Zapisz stan terminala
            curses.def_prog_mode()
            curses.endwin()
            
            # Zmień katalog roboczy na katalog aktywnego panelu
            current_dir = self.left_dir if self.active_pane == 'left' else self.right_dir
            os.chdir(current_dir)
            
            # Wykonaj polecenie w shellu
            shell = os.environ.get('SHELL', '/bin/bash')
            process = subprocess.run([shell, '-c', command])
            
            # Czekaj na input użytkownika przed przywróceniem interfejsu
            print("\nNaciśnij Enter, aby kontynuować...")
            input()
            
            # Przywróć terminal
            curses.reset_prog_mode()
            self.screen.clear()
            self.screen.refresh()
            
            # Odśwież zawartość katalogów
            self.left_files = self.refresh_directory_content(self.left_dir)
            self.right_files = self.refresh_directory_content(self.right_dir)
            
            # Wyświetl status wykonania
            if process.returncode == 0:
                self.status_bar.addstr(0, 0, "Polecenie wykonane pomyślnie", curses.color_pair(1))
            else:
                self.status_bar.addstr(0, 0, f"Polecenie zakończone z błędem (kod: {process.returncode})", 
                                     curses.color_pair(1))
            
            self.status_bar.refresh()
            self.draw_screen()
            
        except FileNotFoundError:
            self.error_handler.show_error("Polecenie nie zostało znalezione")
        except PermissionError:
            self.error_handler.show_error("Brak uprawnień do wykonania polecenia")
        except Exception as e:
            # Przywróć terminal w przypadku błędu
            curses.reset_prog_mode()
            self.screen.clear()
            self.screen.refresh()
            self.status_bar.clear()
            self.status_bar.addstr(0, 0, f"Błąd wykonania polecenia: {str(e)}", curses.color_pair(1))
            self.status_bar.refresh()
            self.draw_screen()

    def _adjust_scroll(self, pane):
        """Dostosuj przewijanie dla danego panelu"""
        if pane == 'left':
            panel = self.left_panel
            selected = self.left_selected
            offset = self.left_offset
            files = self.left_files
        else:
            panel = self.right_panel
            selected = self.right_selected
            offset = self.right_offset
            files = self.right_files

        height = panel.getmaxyx()[0] - 2  # Odejmij 2 dla ramki
        
        # Przewiń w górę jeśli kursor jest powyżej widocznego obszaru
        if selected < offset:
            if pane == 'left':
                self.left_offset = selected
            else:
                self.right_offset = selected
        
        # Przewiń w dół jeśli kursor jest poniżej widocznego obszaru
        elif selected >= offset + height:
            if pane == 'left':
                self.left_offset = selected - height + 1
            else:
                self.right_offset = selected - height + 1

    def handle_enter(self):
        """Obsługa klawisza Enter"""
        if self.active_pane == 'left':
            selected_file = self.left_files[self.left_selected]
            current_dir = self.left_dir
        else:
            selected_file = self.right_files[self.right_selected]
            current_dir = self.right_dir
            
        if selected_file == '..':
            current_dir_name = os.path.basename(current_dir)
            new_dir = os.path.dirname(current_dir)
            
            if os.path.exists(new_dir):
                if self.active_pane == 'left':
                    self.left_dir = new_dir
                    self.left_files = self.refresh_directory_content(new_dir)  # Od razu załaduj zawartość
                    self.left_selected = self.left_files.index(current_dir_name) if current_dir_name in self.left_files else 0
                    self.left_offset = max(0, self.left_selected - (self.left_panel.getmaxyx()[0] - 3))
                else:
                    self.right_dir = new_dir
                    self.right_files = self.refresh_directory_content(new_dir)  # Od razu załaduj zawartość
                    self.right_selected = self.right_files.index(current_dir_name) if current_dir_name in self.right_files else 0
                    self.right_offset = max(0, self.right_selected - (self.right_panel.getmaxyx()[0] - 3))
        else:
            new_dir = os.path.join(current_dir, selected_file)
            if os.path.isdir(new_dir):
                if self.active_pane == 'left':
                    self.left_dir = new_dir
                    self.left_files = self.refresh_directory_content(new_dir)  # Od razu załaduj zawartość
                    self.left_selected = 0
                    self.left_offset = 0
                else:
                    self.right_dir = new_dir
                    self.right_files = self.refresh_directory_content(new_dir)  # Od razu załaduj zawartość
                    self.right_selected = 0
                    self.right_offset = 0

        # Odśwież ekran po wszystkich zmianach
        self.draw_screen()

    def handle_resize(self):
        """Obsługa zmiany rozmiaru terminala"""
        # Wyczyść ekran
        curses.update_lines_cols()
        self.screen.clear()
        self.screen.refresh()
        
        # Utwórz okna na nowo
        self.create_windows()
        
        # Dostosuj przesunięcia list plików
        height = self.left_panel.getmaxyx()[0] - 2
        
        # Dostosuj przesunięcie lewego panelu
        if self.left_selected - self.left_offset >= height:
            self.left_offset = max(0, self.left_selected - height + 1)
        
        # Dostosuj przesunięcie prawego panelu
        if self.right_selected - self.right_offset >= height:
            self.right_offset = max(0, self.right_selected - height + 1)

    def draw_command_line(self):
        """Rysowanie linii komend"""
        try:
            _, width = self.command_line.getmaxyx()
            # Użyj ścieżki z aktywnego panelu
            current_dir = self.left_dir if self.active_pane == 'left' else self.right_dir
            prompt = current_dir + " $ "  # Aktualny katalog jako prompt
            content = self.command_line_content
            
            # Upewnij się, że tekst nie przekracza szerokości okna
            available_width = width - len(prompt)
            if len(content) > available_width:
                visible_content = content[-available_width:]
            else:
                visible_content = content
                
            self.command_line.clear()
            self.command_line.addstr(0, 0, prompt, curses.color_pair(4))
            self.command_line.addstr(0, len(prompt), visible_content, curses.color_pair(4))
            self.command_line.refresh()
        except curses.error:
            pass

    def run(self):
        """Zoptymalizowana główna pętla programu"""
        self.create_windows()
        last_size = self.screen.getmaxyx()
        last_refresh = time.time()
        
        while True:
            current_time = time.time()
            if current_time - last_refresh > 0.1:  # Max 10 FPS
                current_size = self.screen.getmaxyx()
                if current_size != last_size:
                    self.handle_resize()
                    last_size = current_size
                self.draw_screen()
                last_refresh = current_time
                
            if not self.handle_input():
                break

    def _handle_up_key(self):
        """Obsługa klawisza strzałki w górę"""
        if self.active_pane == 'left':
            if self.left_selected > 0:
                self.left_selected -= 1
                self._adjust_scroll('left')
        else:
            if self.right_selected > 0:
                self.right_selected -= 1
                self._adjust_scroll('right')

    def _handle_down_key(self):
        """Obsługa klawisza strzałki w dół"""
        if self.active_pane == 'left':
            if self.left_selected < len(self.left_files) - 1:
                self.left_selected += 1
                self._adjust_scroll('left')
        else:
            if self.right_selected < len(self.right_files) - 1:
                self.right_selected += 1
                self._adjust_scroll('right')

    @contextmanager
    def error_handling(self, operation="Operacja"):
        """Kontekstowy manager obsługi błędów"""
        try:
            yield
        except PermissionError:
            self.error_handler.show_error(f"{operation}: Brak uprawnień")
        except FileNotFoundError:
            self.error_handler.show_error(f"{operation}: Plik nie istnieje")
        except Exception as e:
            self.error_handler.show_error(f"{operation}: {str(e)}")

class MessageBox:
    """Klasa obsługująca okna dialogowe"""
    def __init__(self, screen, title, message, buttons=None):
        self.screen = screen
        self.title = title
        self.message = message.split('\n')
        self.buttons = buttons or ["Tak", "Nie"]  # Domyślne przyciski
        self._create_window()
        
    def _create_window(self):
        """Tworzenie okna dialogowego"""
        screen_height, screen_width = self.screen.getmaxyx()
        
        # Oblicz rozmiary okna
        button_width = sum(len(btn) + 4 for btn in self.buttons) + len(self.buttons) - 1
        height = len(self.message) + 6  # +2 dla przycisków
        width = max(max(len(line) for line in self.message), 
                   len(self.title), 
                   button_width) + 4
        
        # Wyśrodkuj okno
        begin_y = (screen_height - height) // 2
        begin_x = (screen_width - width) // 2
        
        # Utwórz okno
        self.window = curses.newwin(height, width, begin_y, begin_x)
        self.window.bkgd(' ', curses.color_pair(1))
        self.window.box()
        
        # Włącz obsługę myszy dla okna
        self.window.keypad(1)
        
        # Wyświetl tytuł
        self.window.addstr(0, (width - len(self.title)) // 2, f" {self.title} ")
        
        # Wyświetl wiadomość
        for idx, line in enumerate(self.message):
            self.window.addstr(idx + 1, 2, line)
        
        # Wyświetl przyciski
        button_y = height - 3
        total_width = sum(len(btn) + 4 for btn in self.buttons) + len(self.buttons) - 1
        start_x = (width - total_width) // 2
        
        self.button_positions = []  # Zapamiętaj pozycje przycisków
        current_x = start_x
        
        for btn in self.buttons:
            btn_text = f"[ {btn} ]"
            self.button_positions.append((button_y, current_x, current_x + len(btn_text), btn))
            self.window.addstr(button_y, current_x, btn_text, curses.A_NORMAL)
            current_x += len(btn_text) + 1
            
    def _handle_mouse(self, y, x):
        """Obsługa kliknięcia myszy"""
        for btn_y, start_x, end_x, btn in self.button_positions:
            if y == btn_y and start_x <= x < end_x:
                if btn in ["Tak", "Yes"]:
                    return True
                elif btn in ["Nie", "No"]:
                    return False
                elif btn == "Anuluj":
                    return None
        return None
    
    def show(self):
        """Wyświetla okno i czeka na odpowiedź (mysz tymczasowo usunięta)"""
        try:
            self.window.refresh()
            
            while True:
                event = self.screen.getch()
                
                # Obsługa tylko klawiatury, bez myszy
                if event in [ord('t'), ord('T'), ord('y'), ord('Y')]:
                    return True
                elif event in [ord('n'), ord('N')]:
                    return False
                elif event in [27, ord('a'), ord('A')]:  # ESC lub "a" – traktuj jako anuluj
                    return None
        except Exception as e:
            return False

class MCError:
    """Klasa obsługująca błędy w programie"""
    def __init__(self, screen, status_bar):
        self.screen = screen
        self.status_bar = status_bar
        
    def show_error(self, message, error_type="Błąd"):
        """Wyświetla błąd w oknie dialogowym"""
        try:
            msgbox = MessageBox(
                self.screen,
                error_type,
                f"{message}\n\nNaciśnij dowolny klawisz...",
                ["OK"]
            )
            msgbox.show()
        except:
            # Fallback do paska statusu jeśli okno dialogowe zawiedzie
            self.status_bar.clear()
            self.status_bar.addstr(0, 0, f"{error_type}: {message}", curses.color_pair(1))
            self.status_bar.refresh()

def main():
    curses.wrapper(lambda stdscr: MidnightCommander(stdscr).run())

if __name__ == "__main__":
    main()