"""应用入口只允许回环绑定，不提供公网监听参数。"""
import multiprocessing
import uvicorn
from .core import Settings


def main():
    multiprocessing.freeze_support()
    settings = Settings.from_env()
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=settings.port,
                access_log=False, server_header=False, log_level="info")


if __name__ == "__main__":
    main()
