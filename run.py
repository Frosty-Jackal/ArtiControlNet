from Server.ControlNetServer import ControlNetServer

if __name__ == "__main__":
    # 可以在这里读取环境变量或命令行参数
    server = ControlNetServer()
    server.run(host="0.0.0.0", port=6006)

