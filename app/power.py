_standby_prevent_count = 0
_wakepy_keep_running = None

def prevent_standby():
    """Prevents the system from going into standby mode."""
    global _standby_prevent_count, _wakepy_keep_running
    if _standby_prevent_count == 0:
        try:
            from wakepy import keep
            _wakepy_keep_running = keep.running()
            _wakepy_keep_running.__enter__()
        except Exception as e:
            print(f"Warning: Failed to prevent standby. Is wakepy installed? ({e})")
    _standby_prevent_count += 1

def allow_standby():
    """Allows the system to go into standby mode."""
    global _standby_prevent_count, _wakepy_keep_running
    _standby_prevent_count = max(0, _standby_prevent_count - 1)
    if _standby_prevent_count == 0 and _wakepy_keep_running is not None:
        try:
            _wakepy_keep_running.__exit__(None, None, None)
            _wakepy_keep_running = None
        except Exception as e:
            print(f"Warning: Failed to allow standby ({e})")
