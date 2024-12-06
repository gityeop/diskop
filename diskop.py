import os
import subprocess
import shutil
import fnmatch
from functools import lru_cache
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
calculating = False


def quick_size(path):
    """Quick size calculation for initial display"""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        else:
            # Only get immediate children sizes
            total = 0
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_file():
                            try:
                                total += entry.stat().st_size
                            except:
                                pass
            except:
                pass
            return total
    except:
        return 0


def calculate_sizes_async(paths):
    """Calculate directory sizes in background"""
    global calculating
    calculating = True
    
    def worker():
        global calculating
        while True:
            try:
                path = size_queue.get_nowait()
                if path is None:  # Sentinel value
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
    
    # Add paths to queue
    for path in paths:
        size_queue.put(path)
    size_queue.put(None)  # Sentinel value
    
    # Start worker thread
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def get_directory_size_in_bytes(path):
    """Returns the size of given directory or file in bytes"""
    # Check cache first
    if path in size_cache:
        return size_cache[path]
    
    # Use quick size for initial display
    size = quick_size(path)
    size_cache[path] = size
    return size


def convert_bytes_to_gb(size_in_bytes):
    """Converts bytes to GB"""
    return size_in_bytes / (1024**3)


def get_items_with_size(parent_dir):
    """Returns items in the given directory and their sizes"""
    items = []
    paths_to_calculate = []
    
    try:
        # First collect all items
        entries = []
        for entry in os.scandir(parent_dir):
            try:
                # Skip hidden files and system directories
                if entry.name.startswith('.') or entry.name in ['Library', 'System']:
                    continue
                if entry.is_symlink():
                    continue  # Skip symbolic links
                
                item_type = "DIR" if entry.is_dir(follow_symlinks=False) else "FILE"
                dir_full_path = os.path.join(parent_dir, entry.name)
                
                if item_type == "DIR":
                    paths_to_calculate.append(dir_full_path)
                
                size_in_bytes = get_directory_size_in_bytes(dir_full_path)
                entries.append((entry.name, dir_full_path, size_in_bytes, item_type))
            except Exception:
                continue  # Skip any items we can't access

        # Sort directories first, then files, and by size within each group
        dirs = sorted([(n, p, s, t) for n, p, s, t in entries if t == "DIR"],
                     key=lambda x: (-x[2], x[0].lower()))
        files = sorted([(n, p, s, t) for n, p, s, t in entries if t == "FILE"],
                      key=lambda x: (-x[2], x[0].lower()))
        items = dirs + files

        # Start background size calculation
        if paths_to_calculate and not calculating:
            calculate_sizes_async(paths_to_calculate)

    except Exception:
        pass  # Skip if we can't access the directory
    return items


def display_items(items, selected_idx=0, scroll_pos=0):
    """Display items with their sizes"""
    if not items:
        print("\n\033[1;31m⚠️  No items to display or permission denied.\033[0m")
        return

    ITEMS_PER_PAGE = 20
    
    # Clear screen and print header with style
    os.system('clear')
    print("\n\033[1;36m📁 Directory Contents\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Column headers with icons and colors
    headers = [
        "\033[1;37m#",
        "\033[1;37m📄 Name",
        "\033[1;37m💾 Size",
        "\033[1;37m📌 Type\033[0m"
    ]
    print(f"{headers[0]:<4} {headers[1]:<52} {headers[2]:>10} {headers[3]:>10}")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Calculate visible items range
    start_idx = scroll_pos
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(items))
    
    for i in range(start_idx, end_idx):
        name, path, size_bytes, item_type = items[i]
        # Get updated size from cache if available
        if path in size_cache:
            size_bytes = size_cache[path]
        size_gb = convert_bytes_to_gb(size_bytes)
        
        # Add icons and colors based on item type
        if item_type == "DIR":
            icon = "📁"
            type_color = "\033[1;34m"  # Blue for directories
            name = name + "/"
        else:
            # Choose icon based on file extension
            ext = os.path.splitext(name)[1].lower()
            if ext in ['.py', '.js', '.java', '.cpp']:
                icon = "📜"  # Code files
            elif ext in ['.txt', '.md', '.doc', '.pdf']:
                icon = "📄"  # Document files
            elif ext in ['.jpg', '.png', '.gif']:
                icon = "🖼️ "  # Image files
            elif ext in ['.mp3', '.wav']:
                icon = "🎵"  # Music files
            elif ext in ['.mp4', '.mov']:
                icon = "🎬"  # Video files
            else:
                icon = "📄"  # Default file icon
            type_color = "\033[0;37m"  # White for files
        
        if len(name) > 45:
            name = name[:42] + "..."
            
        # Highlight the selected item
        if i == selected_idx:
            prefix = "\033[1;32m▶\033[0m "  # Green arrow for selected item
            name_display = f"\033[1;32m{icon} {name}\033[0m"
            size_display = f"\033[1;32m{size_gb:>8.2f}GB\033[0m"
            type_display = f"\033[1;32m{item_type}\033[0m"
        else:
            prefix = "  "
            name_display = f"{type_color}{icon} {name}\033[0m"
            size_display = f"{size_gb:>8.2f}GB"
            type_display = f"{item_type}"
        
        print(f"{prefix}{i+1:<2} {name_display:<50} {size_display:>10} {type_display:>10}")
    
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Footer with navigation info and stats
    if len(items) > ITEMS_PER_PAGE:
        print(f"\033[38;5;245m📌 Showing items {start_idx + 1} to {end_idx} of {len(items)}\033[0m")
    
    # Help text
    print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [/] Search  [d] Delete  [q] Quit\033[0m")


def display_search_results(items, results, selected_idx=0, scroll_pos=0):
    """Display search results"""
    if not results:
        print("\n\033[1;31m❌ No matching items found.\033[0m")
        return

    ITEMS_PER_PAGE = 20
    
    # Clear screen and print header
    os.system('clear')
    print("\n\033[1;35m🔍 Search Results\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Column headers with icons
    headers = [
        "\033[1;37m#",
        "\033[1;37m📄 Name",
        "\033[1;37m💾 Size",
        "\033[1;37m📌 Type\033[0m"
    ]
    print(f"{headers[0]:<4} {headers[1]:<52} {headers[2]:>10} {headers[3]:>10}")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Calculate visible range
    start_idx = scroll_pos
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(results))
    
    for i in range(start_idx, end_idx):
        idx = results[i]
        name, path, size_bytes, item_type = items[idx]
        if path in size_cache:
            size_bytes = size_cache[path]
        size_gb = convert_bytes_to_gb(size_bytes)
        
        # Add icons and colors based on item type
        if item_type == "DIR":
            icon = "📁"
            type_color = "\033[1;34m"  # Blue for directories
            name = name + "/"
        else:
            # Choose icon based on file extension
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
        
        if len(name) > 45:
            name = name[:42] + "..."
            
        # Highlight selected item
        if i == selected_idx:
            prefix = "\033[1;32m▶\033[0m "
            name_display = f"\033[1;32m{icon} {name}\033[0m"
            size_display = f"\033[1;32m{size_gb:>8.2f}GB\033[0m"
            type_display = f"\033[1;32m{item_type}\033[0m"
        else:
            prefix = "  "
            name_display = f"{type_color}{icon} {name}\033[0m"
            size_display = f"{size_gb:>8.2f}GB"
            type_display = f"{item_type}"
        
        print(f"{prefix}{i+1:<2} {name_display:<50} {size_display:>10} {type_display:>10}")
    
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")
    
    # Footer
    if len(results) > ITEMS_PER_PAGE:
        print(f"\033[38;5;245m📌 Showing items {start_idx + 1} to {end_idx} of {len(results)}\033[0m")
    
    # Help text
    print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [Esc] Back  [q] Quit\033[0m")


def delete_item(path):
    """Deletes a file or directory"""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        # Clear the cache for this path
        if path in size_cache:
            del size_cache[path]
        return True
    except Exception as e:
        print(f"Error deleting {path}: {e}")
        return False


def matrix_rain():
    """Display Matrix-style digital rain effect"""
    # Clear screen and hide cursor
    os.system('clear')
    print('\033[?25l', end='')  # Hide cursor
    
    # Get terminal size
    terminal_width = os.get_terminal_size().columns
    terminal_height = os.get_terminal_size().lines
    
    # Matrix characters
    chars = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ1234567890"
    
    # Initialize drops with random starting positions
    drops = [-random.randint(0, terminal_height) for _ in range(terminal_width)]
    speeds = [random.uniform(0.2, 1.0) for _ in range(terminal_width)]
    
    # Matrix display buffer
    buffer = [[' ' for _ in range(terminal_width)] for _ in range(terminal_height)]
    
    # Colors and fade steps
    # 녹색 계열만 사용 (46: 밝은 녹색, 40-34: 점점 어두워지는 녹색)
    color_intensities = [f"\033[38;5;{i}m" for i in [82, 46, 40, 34, 28]]  # Pure green gradients
    bright_green = "\033[1;32m"
    reset = "\033[0m"
    
    frame = 0
    fade_start = 30  # When to start fading
    try:
        while frame < 80:  # Run for 100 frames
            # Clear buffer
            buffer = [[' ' for _ in range(terminal_width)] for _ in range(terminal_height)]
            
            # Calculate fade factor (0.0 to 1.0) for fade out
            fade_factor = max(0.0, min(1.0, (80 - frame) / (80 - fade_start))) if frame >= fade_start else 1.0
            
            # Update drops
            for i in range(terminal_width):
                if frame < fade_start:  # Normal update before fade
                    drops[i] += speeds[i]
                else:  # Slower update during fade
                    drops[i] += speeds[i] * fade_factor
                
                # If drop is on screen
                pos = int(drops[i])
                if 0 <= pos < terminal_height:
                    # Draw bright head
                    if random.random() < fade_factor:  # Chance to draw based on fade
                        buffer[pos][i] = bright_green + random.choice(chars) + reset
                    
                    # Draw fading tail
                    for j in range(1, 8):  # Tail length
                        trail_pos = pos - j
                        if 0 <= trail_pos < terminal_height:
                            if random.random() < fade_factor:  # Chance to draw based on fade
                                # Use color intensity based on position in tail and fade factor
                                color_idx = min(len(color_intensities)-1, 
                                             int(j * len(color_intensities) / 8))
                                color = color_intensities[color_idx]
                                buffer[trail_pos][i] = color + random.choice(chars) + reset
                
                # Reset drop if it's off screen
                if pos > terminal_height + 8:  # Include tail length
                    if frame < fade_start:  # Only reset before fade starts
                        drops[i] = -random.randint(1, 10)
            
            # Draw frame
            sys.stdout.write('\033[H')  # Move cursor to top
            for row in buffer:
                sys.stdout.write(''.join(row) + '\n')
            sys.stdout.flush()
            
            # Adjust sleep time during fade out (slow down slightly)
            sleep_time = 0.05 * (1 + (1 - fade_factor) * 0.5)
            time.sleep(sleep_time)
            frame += 1
    
    finally:
        # Show cursor and clear screen
        print('\033[?25h', end='')  # Show cursor
        os.system('clear')


def search_items(items, search_term):
    """Search items by name with glob pattern support"""
    if not search_term:
        return []
    
    # Check if it's a glob pattern
    is_glob = any(c in search_term for c in '*?[]!')
    
    results = []
    for i, item in enumerate(items):
        name = item[0]
        if is_glob:
            if fnmatch.fnmatch(name.lower(), search_term.lower()):
                results.append(i)  # Just append the index
        else:
            if search_term.lower() in name.lower():
                results.append(i)  # Just append the index
    return results


def main():
    # matrix_rain()
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
            print("\n\033[38;5;245m(백스페이스: 지우기, \\: 검색 결과로 전환, Enter: 폴더 열기)\033[0m", end='', flush=True)
        elif showing_search_results:
            search_results = search_items(items, last_search_term)
            display_search_results(items, search_results, selected_idx, scroll_pos)
            print(f"\n\033[1;35m🔍 검색어 '{last_search_term}' 결과\033[0m", end='')
            print("\n\033[38;5;245m(d: 삭제, Enter: 폴더 열기, /: 검색어 수정)\033[0m", end='', flush=True)
        else:
            display_items(items, selected_idx, scroll_pos)
        
        try:
            key = readchar.readkey()
        except KeyboardInterrupt:
            break
            
        if key == '/' and not search_mode:
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
            if key == '\\':  # 역슬래시로 검색 결과 모드로 전환
                if search_results:
                    exit_search_mode(keep_results=True)
                else:
                    exit_search_mode(keep_results=False)
            elif key in ('\x7f', '\x08'):  # Backspace
                if search_term:
                    # UTF-8 문자열에서 마지막 문자 제거
                    search_term = search_term.encode('utf-8')[:-1].decode('utf-8', 'ignore')
                    search_results = search_items(items, search_term)
                    selected_idx = 0
                    scroll_pos = 0
                else:
                    exit_search_mode()
            elif key in (readchar.key.ENTER, '\r', '\n'):
                if search_results:
                    orig_idx = search_results[selected_idx]
                    if items[orig_idx][3] == "DIR":
                        history.append(current_path)
                        current_path = items[orig_idx][1]
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
            else:  # 모든 문자 입력 허용 (한글 포함)
                try:
                    # 키 입력을 UTF-8로 디코딩
                    char = key.encode('utf-8').decode('utf-8')
                    search_term += char
                    search_results = search_items(items, search_term)
                    selected_idx = 0
                    scroll_pos = 0
                except UnicodeError:
                    # 유효하지 않은 UTF-8 시퀀스는 무시
                    pass
            continue
            
        # 일반 모드 (showing_search_results 포함)
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
            else:
                if items and selected_idx < len(items) and items[selected_idx][3] == "DIR":
                    history.append(current_path)
                    current_path = items[selected_idx][1]
                    selected_idx = 0
                    scroll_pos = 0
        elif key == 'b':
            if history:
                current_path = history.pop()
                selected_idx = 0
                scroll_pos = 0
        elif key == 'd':
            if showing_search_results:
                if search_results and selected_idx < len(search_results):
                    orig_idx = search_results[selected_idx]
                    item = items[orig_idx]
                    print(f"\nReally delete '{item[0]}'? (y/n): ", end='', flush=True)
                    confirm = readchar.readkey().lower()
                    if confirm == 'y':
                        if delete_item(item[1]):
                            print(f"\nDeleted: {item[0]}")
                            if item[1] in size_cache:
                                del size_cache[item[1]]
                            items = get_items_with_size(current_path)
                            search_results = search_items(items, last_search_term)
                            if not search_results:
                                showing_search_results = False
                                selected_idx = 0
                                scroll_pos = 0
                            else:
                                selected_idx = min(selected_idx, len(search_results) - 1)
                                scroll_pos = min(scroll_pos, max(0, len(search_results) - 20))
                        else:
                            print(f"\nFailed to delete: {item[0]}")
                        readchar.readkey()
            else:
                if items and selected_idx < len(items):
                    item = items[selected_idx]
                    print(f"\nReally delete '{item[0]}'? (y/n): ", end='', flush=True)
                    confirm = readchar.readkey().lower()
                    if confirm == 'y':
                        if delete_item(item[1]):
                            print(f"\nDeleted: {item[0]}")
                            if item[1] in size_cache:
                                del size_cache[item[1]]
                            if len(items) > 1:
                                selected_idx = min(selected_idx, len(items) - 2)
                                scroll_pos = min(scroll_pos, max(0, len(items) - 20))
                            else:
                                selected_idx = 0
                                scroll_pos = 0
                        else:
                            print(f"\nFailed to delete: {item[0]}")
                        readchar.readkey()
        elif key == 'q':
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
