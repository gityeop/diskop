import os
import subprocess
import shutil
import fnmatch
import threading
from queue import Queue
import readchar
import sys
import time
import mmap
from concurrent.futures import ThreadPoolExecutor
import stat
from functools import lru_cache
import platform

# 글로벌 캐시 및 큐 초기화
size_cache = {}
size_queue = Queue()
WORKER_THREADS = max(4, os.cpu_count())  # CPU 코어 수에 따른 최적 스레드 수 설정

# 계산 상태 및 진행 상황 관리
calculating = False
progress = {
    'total': 0,
    'processed': 0
}
current_paths_to_calculate = []
progress_lock = threading.Lock()

def reset_progress():
    """프로그레스와 계산 상태를 초기화합니다."""
    global calculating
    with progress_lock:
        progress['total'] = 0
        progress['processed'] = 0
        global current_paths_to_calculate
        current_paths_to_calculate = []
        calculating = False

@lru_cache(maxsize=10000)
def get_file_size(path):
    """저수준 시스템 호출을 사용하여 파일 크기를 빠르게 얻습니다."""
    try:
        return os.stat(path).st_size
    except (OSError, IOError):
        return 0

def quick_size(path):
    """최적화된 초기 디렉토리 크기 계산."""
    try:
        if os.path.isfile(path):
            return get_file_size(path)
        
        total = 0
        # 메모리 매핑된 디렉토리 스캔
        try:
            with os.scandir(path) as it:
                entries = list(it)  # 한 번에 모든 항목을 버퍼링
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):  # 심볼릭 링크 처리 최적화
                            total += entry.stat().st_size
                    except:
                        continue
        except:
            pass
        return total
    except:
        return 0

def process_directory(path):
    """단일 디렉토리 처리를 위한 워커 함수."""
    try:
        result = subprocess.run(
            ["du", "-sk", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5  # 타임아웃 설정
        )
        if result.returncode == 0:
            size = int(result.stdout.split()[0]) * 1024
            size_cache[path] = size
            return path, size
    except:
        pass
    return path, 0

def calculate_sizes_async(paths):
    """병렬 처리를 사용한 최적화된 디렉토리 크기 계산."""
    global calculating
    with progress_lock:
        calculating = True
        progress['total'] = len(paths)
        progress['processed'] = 0
        global current_paths_to_calculate
        current_paths_to_calculate = paths.copy()

    def worker():
        global calculating
        try:
            with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
                futures = [executor.submit(process_directory, path) for path in paths]
                for future in futures:
                    try:
                        path, size = future.result(timeout=10)
                        if size > 0:
                            size_cache[path] = size
                        with progress_lock:
                            if path in current_paths_to_calculate:
                                progress['processed'] += 1
                    except:
                        with progress_lock:
                            if path in current_paths_to_calculate:
                                progress['processed'] += 1
                        continue
        finally:
            with progress_lock:
                calculating = False
                progress['processed'] = progress['total']  # Ensure we mark as complete

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

def get_directory_size_in_bytes(path):
    """주어진 디렉토리 또는 파일의 크기를 바이트 단위로 반환합니다."""
    if path in size_cache:
        return size_cache[path]
    size = quick_size(path)
    size_cache[path] = size
    return size

def convert_bytes_to_gb(size_in_bytes):
    """바이트를 GB로 변환합니다."""
    return size_in_bytes / (1024**3)

def get_items_with_size(parent_dir):
    """주어진 디렉토리의 항목들과 그 크기를 반환합니다."""
    items = []
    paths_to_calculate = []

    try:
        entries = []
        for entry in os.scandir(parent_dir):
            # 특정 디렉토리나 심볼릭 링크는 건너뜁니다.
            if entry.name in ['System']:
                continue
            if entry.is_symlink():
                continue

            item_type = "DIR" if entry.is_dir(follow_symlinks=False) else "FILE"
            dir_full_path = os.path.join(parent_dir, entry.name)

            # 디렉토리이면서 캐시에 없으면 계산 대상에 추가
            if item_type == "DIR" and dir_full_path not in size_cache:
                paths_to_calculate.append(dir_full_path)

            size_in_bytes = get_directory_size_in_bytes(dir_full_path)
            entries.append((entry.name, dir_full_path, size_in_bytes, item_type))

        # 디렉토리와 파일을 크기별로 정렬
        dirs = sorted([(n, p, s, t) for n, p, s, t in entries if t == "DIR"],
                      key=lambda x: (-x[2], x[0].lower()))
        files = sorted([(n, p, s, t) for n, p, s, t in entries if t == "FILE"],
                       key=lambda x: (-x[2], x[0].lower()))
        items = dirs + files

        # 계산이 필요하고 현재 계산 중이 아니면 계산 시작
        with progress_lock:
            should_calculate = bool(paths_to_calculate) and not calculating

        if should_calculate:
            calculate_sizes_async(paths_to_calculate)

    except Exception:
        pass
    return items

def display_progress_bar():
    """크기 계산을 위한 프로그레스 바를 표시합니다."""
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
    """항목들과 그 크기를 표시합니다."""
    os.system('clear')
    print("\n\033[1;36m📁 Directory Contents\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    # 컬럼 헤더
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
                type_color = "\033[1;34m"  # 파란색
                display_name = name + "/"
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in ['.py', '.js', '.java', '.cpp']:
                    icon = "📜"  # 코드 파일
                elif ext in ['.txt', '.md', '.doc', '.pdf']:
                    icon = "📄"  # 문서 파일
                elif ext in ['.jpg', '.png', '.gif']:
                    icon = "🖼️ "  # 이미지 파일
                elif ext in ['.mp3', '.wav']:
                    icon = "🎵"  # 음악 파일
                elif ext in ['.mp4', '.mov']:
                    icon = "🎬"  # 동영상 파일
                else:
                    icon = "📄"  # 기본 파일 아이콘
                type_color = "\033[0;37m"  # 흰색
                display_name = name

            if len(display_name) > 45:
                display_name = display_name[:42] + "..."

            if i == selected_idx:
                prefix = "\033[1;32m▶\033[0m "  # 녹색 화살표
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

    with progress_lock:
        is_calculating = calculating
        current_calculating_paths = current_paths_to_calculate.copy()

    if is_calculating and current_calculating_paths:
        display_progress_bar()
        # 계산 중임을 사용자에게 알림
        print("\n\033[38;5;245m⏳ Calculating sizes, please wait...\033[0m\n")
    else:
        print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [o] Open  [/] Search  [d] Delete  [q] Quit\033[0m")

def display_search_results(items, results, selected_idx=0, scroll_pos=0):
    """검색 결과를 표시합니다."""
    os.system('clear')
    print("\n\033[1;35m🔍 Search Results\033[0m")
    print("\033[38;5;240m" + "─" * 82 + "\033[0m")

    # 컬럼 헤더
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
                type_color = "\033[1;34m"  # 파란색
                display_name = name + "/"
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in ['.py', '.js', '.java', '.cpp']:
                    icon = "📜"  # 코드 파일
                elif ext in ['.txt', '.md', '.doc', '.pdf']:
                    icon = "📄"  # 문서 파일
                elif ext in ['.jpg', '.png', '.gif']:
                    icon = "🖼️ "  # 이미지 파일
                elif ext in ['.mp3', '.wav']:
                    icon = "🎵"  # 음악 파일
                elif ext in ['.mp4', '.mov']:
                    icon = "🎬"  # 동영상 파일
                else:
                    icon = "📄"  # 기본 파일 아이콘
                type_color = "\033[0;37m"  # 흰색
                display_name = name

            if len(display_name) > 45:
                display_name = display_name[:42] + "..."

            if i == selected_idx:
                prefix = "\033[1;32m▶\033[0m "  # 녹색 화살표
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

    with progress_lock:
        is_calculating = calculating
        current_calculating_paths = current_paths_to_calculate.copy()

    if is_calculating and current_calculating_paths:
        display_progress_bar()
        # 계산 중임을 사용자에게 알림
        print("\n\033[38;5;245m⏳ Calculating sizes, please wait...\033[0m\n")
    else:
        print("\n\033[38;5;245m🔍 Navigation: [↑↓] Move  [Enter] Select  [o] Open  [Esc] Back  [q] Quit\033[0m")

def delete_item(path):
    """파일 또는 디렉토리를 삭제합니다."""
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
    """글로벌 패턴을 지원하는 이름으로 항목을 검색합니다."""
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

def open_path(path):
    """파일이나 디렉토리를 시스템 기본 앱으로 엽니다."""
    try:
        if platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', path])
        elif platform.system() == 'Windows':  # Windows
            os.startfile(path)
        elif platform.system() == 'Linux':  # Linux
            subprocess.run(['xdg-open', path])
        return True
    except Exception as e:
        print(f"\nError opening {path}: {e}")
        return False

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
            print("\n\033[38;5;245m(d: Delete, o: Open, Enter: Open Folder, /: Modify Search)\033[0m", end='', flush=True)
        else:
            display_items(items, selected_idx, scroll_pos)

        with progress_lock:
            is_calculating = calculating

        if is_calculating:
            time.sleep(0.5)
            continue

        try:
            key = readchar.readkey()
        except KeyboardInterrupt:
            break

        if search_mode:
            if key == '\\':
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
            elif key == 'o':  # 파일/디렉토리 열기
                if search_results:
                    orig_idx = search_results[selected_idx]
                    item_path = os.path.join(current_path, items[orig_idx][0])
                    open_path(item_path)
            elif key in (readchar.key.ENTER, '\r', '\n'):
                if search_results:
                    orig_idx = search_results[selected_idx]
                    if items[orig_idx][3] == "DIR":
                        history.append((current_path, selected_idx, scroll_pos))
                        current_path = os.path.join(current_path, items[orig_idx][0])
                        selected_idx = 0
                        scroll_pos = 0
                        exit_search_mode()
        else:
            if key in ('k', readchar.key.UP, '\x1b[A'):
                if selected_idx > 0:
                    selected_idx -= 1
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
            elif key in ('j', readchar.key.DOWN, '\x1b[B'):
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
            elif key == 'o':  # 파일/디렉토리 열기
                if showing_search_results:
                    orig_idx = search_results[selected_idx]
                    item_path = os.path.join(current_path, items[orig_idx][0])
                else:
                    item_path = os.path.join(current_path, items[selected_idx][0])
                open_path(item_path)
            elif key in (readchar.key.ENTER, '\r', '\n'):
                if showing_search_results:
                    orig_idx = search_results[selected_idx]
                    if items[orig_idx][3] == "DIR":
                        history.append((current_path, selected_idx, scroll_pos))
                        current_path = os.path.join(current_path, items[orig_idx][0])
                        selected_idx = 0
                        scroll_pos = 0
                        showing_search_results = False
                else:
                    if items[selected_idx][3] == "DIR":
                        history.append((current_path, selected_idx, scroll_pos))
                        current_path = os.path.join(current_path, items[selected_idx][0])
                        selected_idx = 0
                        scroll_pos = 0
            elif key == 'b':
                if history:
                    previous_path, previous_selected_idx, previous_scroll_pos = history.pop()
                    current_path = previous_path
                    selected_idx = previous_selected_idx
                    scroll_pos = previous_scroll_pos
                    if current_path in size_cache:
                        del size_cache[current_path]
                    reset_progress()
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
                                if current_path in size_cache:
                                    del size_cache[current_path]
                                reset_progress()
                            else:
                                print(f"\nFailed to delete: {item[0]}")
                        continue
                else:
                    if items and selected_idx < len(items):
                        item = items[selected_idx]
                        print(f"\nReally delete '{item[0]}'? (y/n): ", end='', flush=True)
                        confirm = readchar.readkey().lower()
                        if confirm == 'y':
                            if delete_item(item[1]):
                                print(f"\nDeleted: {item[0]}")
                                if current_path in size_cache:
                                    del size_cache[current_path]
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
