import json
import os
import threading


_json_write_lock = threading.RLock()


def load_json(path, default):
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            import shutil
            import time

            bak = path + f".bak_{int(time.time())}"
            try:
                shutil.copy2(path, bak)
                print(f"[警告] {path} JSON损坏，已备份到 {bak}，返回默认值")
            except Exception:
                pass
            return default
    return default


def save_json(path, data):
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with _json_write_lock:
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            print(f"[警告] 保存 {path} 失败: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False
