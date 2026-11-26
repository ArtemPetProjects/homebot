from homebot.api.main import *  # noqa: F401,F403  -- обратная совместимость путей
from homebot.api.main import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())
