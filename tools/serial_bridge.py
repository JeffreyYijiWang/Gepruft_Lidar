"""After pip install -e ., this also runs as python tools/serial_bridge.py."""

from lms200.bridge import main

if __name__ == "__main__":
    main()
