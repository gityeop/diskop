import os
import subprocess
import shutil
import fnmatch
import threading
from queue import Queue
import random
import time
import sys

try:
    import readchar
except ImportError:
    print("Installing required package: readchar")
    subprocess.run(["pip", "install", "readchar"], check=True)
    import readchar

# Global cache for directory sizes
size_cache = {}
size_queue = Queue()

# Calculation status
calculating = False
progress = {
    'total': 0,
    'processed': 0
}
progress_lock = threading.Lock()

def reset_progress():
    """Reset the progress and calculating status."""
    global calculating
    with progress_lock:
        progress['total'] = 0
        progress['processed'] = 0
    calculating = False

def quick_size(path):
    """Quick size calculation for initial display."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        else:
            # Only get immediate children sizes
            total = 0
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file():
                        try:
                            total += entry.stat().st_size
                        except:
                            pass
            return total
    except:
        return 0

def calculate_sizes_async(paths):
    """Calculate directory sizes in background."""
    global calculating
    calculating = True

    def worker():
        global calculating
        while True:
            try:
                path = size_queue.get_nowait()
                if path is None:  # Sentinel
                    break
                try:
                    result = subprocess.run(
                        ["du", "-sk", path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    if result.returncode == 0:
                        size_cache[path] = int(result.stdout.split()[0]) * 1024
                except:
                    pass
                with progress_lock:
                    progress['processed'] += 1
                size_queue.task_done()
            except:
                break
        calculating = False

    # Clear existing queue
    while not size_queue.empty():
        try:
            size_queue.get_nowait()
            size_queue.task_done()
        except:
            pass

    with progress_lock:
        progress['total'] = len(paths)
        progress['processed'] = 0

    for path in paths:
        size_queue.put(path)
    size_queue.put(None)  # Sentinel

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

def get_directory_size_in_bytes(path):
    """Returns the size of given directory or file in bytes."""
    if path in size_cache:
        return size_cache[path]
    size = quick_size(path)
    size_cache[path] = size
    return size

def convert_bytes_to_gb(size_in_bytes):
    """Converts bytes to GB."""
    return size_in_bytes / (1024**3)

def get_items_with_size(parent_dir):
    """Returns items in the given directory and their sizes."""
    items = []
    paths_to_calculate = []

    try:
        entries = []
        for entry in os.scandir(parent_dir):
            # Skip certain directories or symlinks
            if entry.name in ['System']:
                continue
            if entry.is_symlink():
                continue

            item_type = "DIR" if entry.is_dir(follow_symlinks=False) else "FILE"
            dir_full_path = os.path.join(parent_dir, entry.name)

            if item_type == "DIR":
                paths_to_calculate.append(dir_full_path)

            size_in_bytes = get_directory_size_in_bytes(dir_full_path)
            entries.append((entry.name, dir_full_path, size_in_bytes, item_type))

        dirs = sorted([(n, p, s, t) for n, p, s, t in entries if t == "DIR"],
                      key=lambda x: (-x[2], x[0].lower()))
        files = sorted([(n, p, s, t) for n, p, s, t in entries if t == "FILE"],
                       key=lambda x: (-x[2], x[0].lower()))
        items = dirs + files

        # If there are directories to calculate and not currently calculating, start a new calculation
        if paths_to_calculate and not calculating:
            calculate_sizes_async(paths_to_calculate)

    except Exception:
        pass
    return items

def display_progress_bar():
    """Displays a progress bar for size calculation."""
    with progress_lock:
        total = progress['total']
        processed = progress['processed']
    if total == 0:
        return

    bar_length = 40
    filled_length = int(round(bar_length * processed / float(total)))

    percents = round(100.0 * processed / float(total), 1)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)

    sys.stdout.write(f"\n\033[38;5;245m📊 Size Calculation Progress: |{bar}| {percents}% ({processed}/{total})\033[0m\n")
    sys.stdout.flush()

def display_items(items, selected_idx=0, scroll_pos=0):
    """Display items with their sizes."""
    os.system('clear')
    print("\n\033[1;36m📁 Directory Contents\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    headers = [
        "\033[1;37m#",
        "\033[1;37m📄 Name",
        "\033[1;37m💾 Size",
        "\033[1;37m📌 Type\033[0m"
    ]
    print(f"{headers[0]:<4} {headers[1]:<52} {headers[2]:>10} {headers[3]:>10}")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    if not items:
        print("\n\033[1;31m❌ No items found.\033[0m")
    else:
        ITEMS_PER_PAGE = 20
        start_idx = scroll_pos
        end_idx = min(start_idx + ITEMS_PER_PAGE, len(items))

        for i in range(start_idx, end_idx):
            name, path, size_bytes, item_type = items[i]
            if path in size_cache:
                size_bytes = size_cache[path]
            size_gb = convert_bytes_to_gb(size_bytes)

            if item_type == "DIR":
                icon = "📁"
                type_color = "\033[1;34m"
                display_name = name + "/"
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in ['.py', '.js', '.java', '.cpp']:
                    icon = "📜"
                elif ext in ['.txt', '.md', '.doc', '.pdf']:
                    icon = "📄"
                elif ext in ['.jpg', '.png', '.gif']:
                    icon = "🖼️ "
                elif ext in ['.mp3', '.wav']:
                    icon = "🎵"
                elif ext in ['.mp4', '.mov']:
                    icon = "🎬"
                else:
                    icon = "📄"
                type_color = "\033[0;37m"
                display_name = name

            if len(display_name) > 45:
                display_name = display_name[:42] + "..."

            if i == selected_idx:
                prefix = "\033[1;32m▶\033[0m "
                name_display = f"\033[1;32m{icon} {display_name}\033[0m"
                size_display = f"\033[1;32m{size_gb:>8.2f}GB\033[0m"
                type_display = f"\033[1;32m{item_type}\033[0m"
            else:
                prefix = "  "
                name_display = f"{type_color}{icon} {display_name}\033[0m"
                size_display = f"{size_gb:>8.2f}GB"
                type_display = f"{item_type}"

            print(f"{prefix}{i+1:<2} {name_display:<50} {size_display:>10} {type_display:>10}")

        print("\033[38;5;240m" + "─" * 82 + "\033[0m")

        if len(items) > ITEMS_PER_PAGE:
            print(f"\033[38;5;245m📌 Showing items {start_idx + 1} to {end_idx} of {len(items)}\033[0m")

    if calculating:
        display_progress_bar()

    print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [/] Search  [d] Delete  [q] Quit\033[0m")

def display_search_results(items, results, selected_idx=0, scroll_pos=0):
    """Display search results."""
    os.system('clear')
    print("\n\033[1;35m🔍 Search Results\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    headers = [
        "\033[1;37m#",
        "\033[1;37m📄 Name",
        "\033[1;37m💾 Size",
        "\033[1;37m📌 Type\033[0m"
    ]
    print(f"{headers[0]:<4} {headers[1]:<52} {headers[2]:>10} {headers[3]:>10}")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    if not results:
        print("\n\033[1;31m❌ No matching items found.\033[0m")
    else:
        ITEMS_PER_PAGE = 20
        start_idx = scroll_pos
        end_idx = min(start_idx + ITEMS_PER_PAGE, len(results))

        for i in range(start_idx, end_idx):
            idx = results[i]
            name, path, size_bytes, item_type = items[idx]
            if path in size_cache:
                size_bytes = size_cache[path]
            size_gb = convert_bytes_to_gb(size_bytes)

            if item_type == "DIR":
                icon = "📁"
                type_color = "\033[1;34m"
                display_name = name + "/"
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in ['.py', '.js', '.java', '.cpp']:
                    icon = "📜"
                elif ext in ['.txt', '.md', '.doc', '.pdf']:
                    icon = "📄"
                elif ext in ['.jpg', '.png', '.gif']:
                    icon = "🖼️ "
                elif ext in ['.mp3', '.wav']:
                    icon = "🎵"
                elif ext in ['.mp4', '.mov']:
                    icon = "🎬"
                else:
                    icon = "📄"
                type_color = "\033[0;37m"
                display_name = name

            if len(display_name) > 45:
                display_name = display_name[:42] + "..."

            if i == selected_idx:
                prefix = "\033[1;32m▶\033[0m "
                name_display = f"\033[1;32m{icon} {display_name}\033[0m"
                size_display = f"\033[1;32m{size_gb:>8.2f}GB\033[0m"
                type_display = f"\033[1;32m{item_type}\033[0m"
            else:
                prefix = "  "
                name_display = f"{type_color}{icon} {display_name}\033[0m"
                size_display = f"{size_gb:>8.2f}GB"
                type_display = f"{item_type}"

            print(f"{prefix}{i+1:<2} {name_display:<50} {size_display:>10} {type_display:>10}")

        print("\033[38;5;240m" + "─" * 82 + "\033[0m")

        if len(results) > ITEMS_PER_PAGE:
            print(f"\033[38;5;245m📌 Showing items {start_idx + 1} to {end_idx} of {len(results)}\033[0m")

    if calculating:
        display_progress_bar()

    print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [Esc] Back  [q] Quit\033[0m")

def delete_item(path):
    """Deletes a file or directory."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        if path in size_cache:
            del size_cache[path]
        return True
    except Exception as e:
        print(f"Error deleting {path}: {e}")
        return False

def search_items(items, search_term):
    """Search items by name with glob pattern support."""
    if not search_term:
        return []
    is_glob = any(c in search_term for c in '*?[]!')
    results = []
    for i, item in enumerate(items):
        name = item[0]
        if is_glob:
            if fnmatch.fnmatch(name.lower(), search_term.lower()):
                results.append(i)
        else:
            if search_term.lower() in name.lower():
                results.append(i)
    return results

def main():
    current_path = os.path.expanduser("~")
    history = []
    selected_idx = 0
    scroll_pos = 0
    search_mode = False
    search_term = ""
    search_results = []
    last_search_term = ""
    showing_search_results = False

    def exit_search_mode(keep_results=False):
        nonlocal search_mode, search_term, search_results, selected_idx, scroll_pos, last_search_term, showing_search_results
        search_mode = False
        if keep_results:
            last_search_term = search_term
            showing_search_results = True
        search_term = ""

    while True:
        items = get_items_with_size(current_path)

        if search_mode:
            display_search_results(items, search_results, selected_idx, scroll_pos)
            print(f"\n\033[1;35m🔍 Search:\033[0m {search_term}\033[K", end='')
            print("\n\033[38;5;245m(Backspace: Delete, \\: Enter Search Results, Enter: Open Folder)\033[0m", end='', flush=True)
        elif showing_search_results:
            search_results = search_items(items, last_search_term)
            display_search_results(items, search_results, selected_idx, scroll_pos)
            print(f"\n\033[1;35m🔍 Search Term '{last_search_term}' Results\033[0m", end='')
            print("\n\033[38;5;245m(d: Delete, Enter: Open Folder, /: Modify Search)\033[0m", end='', flush=True)
        else:
            display_items(items, selected_idx, scroll_pos)

        try:
            key = readchar.readkey()
        except KeyboardInterrupt:
            break

        if key == '/' and not search_mode:
            # Enter search mode
            search_mode = True
            if showing_search_results:
                search_term = last_search_term
                search_results = search_items(items, search_term)
            else:
                search_term = ""
                search_results = []
            selected_idx = 0
            scroll_pos = 0
            showing_search_results = False
            continue

        if search_mode:
            if key == '\\':
                # Switch to showing search results mode
                if search_results:
                    exit_search_mode(keep_results=True)
                else:
                    exit_search_mode(keep_results=False)
            elif key in ('\x7f', '\x08'):  # Backspace
                if search_term:
                    search_term = search_term[:-1]
                    search_results = search_items(items, search_term)
                    selected_idx = 0
                    scroll_pos = 0
                else:
                    exit_search_mode()
            elif key in (readchar.key.ENTER, '\r', '\n'):
                if search_results:
                    orig_idx = search_results[selected_idx]
                    if items[orig_idx][3] == "DIR":
                        # Change directory
                        history.append(current_path)
                        current_path = items[orig_idx][1]
                        # Reset progress and states
                        reset_progress()
                        showing_search_results = True
                        exit_search_mode(keep_results=True)
                else:
                    exit_search_mode()
            elif key in (readchar.key.UP, readchar.key.DOWN):
                if not search_results:
                    exit_search_mode()
                elif key == readchar.key.UP and selected_idx > 0:
                    selected_idx -= 1
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
                elif key == readchar.key.DOWN and selected_idx < len(search_results) - 1:
                    selected_idx += 1
                    if selected_idx >= scroll_pos + 20:
                        scroll_pos = selected_idx - 19
            else:
                try:
                    search_term += key
                    search_results = search_items(items, search_term)
                    selected_idx = 0
                    scroll_pos = 0
                except UnicodeError:
                    pass
            continue

        # General navigation
        if key == readchar.key.UP:
            if showing_search_results:
                if selected_idx > 0:
                    selected_idx -= 1
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
            else:
                if selected_idx > 0:
                    selected_idx -= 1
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
        elif key == readchar.key.DOWN:
            if showing_search_results:
                if selected_idx < len(search_results) - 1:
                    selected_idx += 1
                    if selected_idx >= scroll_pos + 20:
                        scroll_pos = selected_idx - 19
            else:
                if selected_idx < len(items) - 1:
                    selected_idx += 1
                    if selected_idx >= scroll_pos + 20:
                        scroll_pos = selected_idx - 19
        elif key in (readchar.key.ENTER, '\r', '\n'):
            if showing_search_results:
                if search_results and selected_idx < len(search_results):
                    orig_idx = search_results[selected_idx]
                    if items[orig_idx][3] == "DIR":
                        history.append(current_path)
                        current_path = items[orig_idx][1]
                        selected_idx = 0
                        scroll_pos = 0
                        # Reset and recalculate
                        reset_progress()
            else:
                if items and selected_idx < len(items) and items[selected_idx][3] == "DIR":
                    # Enter the selected directory
                    history.append(current_path)
                    current_path = items[selected_idx][1]
                    selected_idx = 0
                    scroll_pos = 0
                    # Reset and recalculate
                    reset_progress()
            continue
        elif key == 'b':
            # Go back if history is available
            if history:
                previous_path = history.pop()
                current_path = previous_path
                selected_idx = 0
                scroll_pos = 0
                reset_progress()
        elif key == 'd':
            # Delete the selected item
            if showing_search_results:
                if search_results and selected_idx < len(search_results):
                    orig_idx = search_results[selected_idx]
                    item = items[orig_idx]
                    print(f"\nReally delete '{item[0]}'? (y/n): ", end='', flush=True)
                    confirm = readchar.readkey().lower()
                    if confirm == 'y':
                        if delete_item(item[1]):
                            print(f"\nDeleted: {item[0]}")
                            # Refresh items
                            reset_progress()
                        else:
                            print(f"\nFailed to delete: {item[0]}")
                    # 바로 다음 루프로 넘어가며 새 목록 표시
                    continue
            else:
                if items and selected_idx < len(items):
                    item = items[selected_idx]
                    print(f"\nReally delete '{item[0]}'? (y/n): ", end='', flush=True)
                    confirm = readchar.readkey().lower()
                    if confirm == 'y':
                        if delete_item(item[1]):
                            print(f"\nDeleted: {item[0]}")
                            # Refresh items after deletion
                            reset_progress()
                        else:
                            print(f"\nFailed to delete: {item[0]}")
                    continue
        elif key == 'q':
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
