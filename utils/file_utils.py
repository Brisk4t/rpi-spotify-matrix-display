# Purpose: Safe file writing helpers.
import os


def write_atomic(path: str, text: str):
    """
    Writes text to path via a temporary file, so a power cut never leaves a half-written file.
    Keeps the existing file's owner and permissions, since the display usually runs as root.
    New files get the directory's owner, so they stay editable without sudo.
    """
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    try:
        st = os.stat(path)
        os.chmod(tmp_path, st.st_mode & 0o7777)
        if os.geteuid() == 0:
            os.chown(tmp_path, st.st_uid, st.st_gid)
    except FileNotFoundError:
        if os.geteuid() == 0:
            st = os.stat(os.path.dirname(os.path.abspath(path)))
            os.chown(tmp_path, st.st_uid, st.st_gid)

    os.replace(tmp_path, path)
