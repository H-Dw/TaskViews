"""One host-wide OSWorld execution lease, inherited by serial child launchers."""
from contextlib import contextmanager
import os
from pathlib import Path


LOCK = Path(__file__).resolve().parents[3] / 'osworld_verified_setup/osworld1-eval.lock'
FD_ENV = 'UI_KOBE_VERIFIED_SERIAL_FD'


def process_identity(pid):
    try:
        fields = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] in ('Z', 'X'):
            return None
        return {'pid': int(pid), 'start_ticks': int(fields[19]),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, ValueError, IndexError):
        return None


def inherited_fds():
    value = os.environ.get(FD_ENV)
    return (int(value),) if value is not None else ()


@contextmanager
def serial_lock():
    import fcntl
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    inherited = os.environ.get(FD_ENV)
    if inherited is not None:
        fd = int(inherited)
        actual, expected = os.fstat(fd), LOCK.stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError('Inherited OSWorld lease does not identify the host lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
        return
    with LOCK.open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another local OSWorld execution or repair owns the host lease') from exc
        os.set_inheritable(handle.fileno(), True)
        os.environ[FD_ENV] = str(handle.fileno())
        try:
            yield handle.fileno()
        finally:
            os.environ.pop(FD_ENV, None)
            fcntl.flock(handle, fcntl.LOCK_UN)
