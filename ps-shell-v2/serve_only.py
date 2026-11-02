# -*- coding: utf-8 -*-
"""仅启动本地 HTTP 服务（不创建原生窗口/不自动开浏览器）。

用法：python serve_only.py [端口]
  不给端口 = 随机端口（默认，多实例并行不冲突）；
  给了端口 = 固定端口（调试时页面地址稳定，重启后刷新即可，不必换链接）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import server  # noqa: E402

if __name__ == "__main__":
    _port = 0
    if len(sys.argv) > 1:
        try:
            _port = int(sys.argv[1])
        except ValueError:
            print(f"端口参数无效：{sys.argv[1]}（应为 1024-65535 的整数），改用随机端口。")
            _port = 0
    try:
        srv = server.start_server(_port)
    except OSError as e:
        print(f"启动失败（端口 {_port} 可能已被占用）：{e}")
        print("  换个端口：python serve_only.py 51889　或省略端口用随机端口：python serve_only.py")
        sys.exit(1)
    port = srv.server_address[1]
    print(f"SERVE_URL=http://127.0.0.1:{port}/launch.html")
    print(f"  VS 皮肤：http://127.0.0.1:{port}/vs.html")
    print(f"  向导版：http://127.0.0.1:{port}/index.html")
    print("  按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
