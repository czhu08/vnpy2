import multiprocessing
import signal
from time import sleep
from datetime import datetime, time
from logging import INFO

from vnpy.event import EventEngine
from vnpy.gateway.huobi import HuobiGateway
from vnpy.trader.setting import SETTINGS
from vnpy.trader.engine import MainEngine

# from vnpy.gateway.ctp import CtpGateway
from vnpy.app.cta_strategy import CtaStrategyApp
from vnpy.app.cta_strategy.base import EVENT_CTA_LOG
from vnpy.trader.utility import load_json

SETTINGS["log.active"] = True
SETTINGS["log.level"] = INFO
SETTINGS["log.console"] = True

terminate = False

def run_child():
    """
    Running in the child process.
    """
    SETTINGS["log.file"] = True

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    huobi = main_engine.add_gateway(HuobiGateway)
    cta_engine = main_engine.add_app(CtaStrategyApp)
    main_engine.write_log("主引擎创建成功")

    log_engine = main_engine.get_engine("log")
    event_engine.register(EVENT_CTA_LOG, log_engine.process_log_event)
    main_engine.write_log("注册日志事件监听")

    filename = f"connect_{huobi.gateway_name.lower()}.json"
    setting = load_json(filename)
    main_engine.connect(setting, huobi.gateway_name)
    main_engine.write_log("连接HUOBI接口")

    sleep(10)

    cta_engine.init_engine()
    main_engine.write_log("CTA策略初始化完成")

    cta_engine.init_all_strategies()
    sleep(10)   # Leave enough time to complete strategy initialization
    main_engine.write_log("CTA策略全部初始化")

    cta_engine.start_all_strategies()
    main_engine.write_log("CTA策略全部启动")

    while True:
        sleep(1)


def run_parent():
    """
    Running in the parent process.
    """
    print("启动CTA策略守护父进程")

    child_process = None
    signal.signal(signal.SIGINT, kill_handler)
    while not terminate:

        # Start child process in trading period
        if child_process is None:
            print("启动子进程")
            child_process = multiprocessing.Process(target=run_child)
            child_process.start()
            print("子进程启动成功")

        sleep(5)

    if child_process is not None:
        print("关闭子进程")
        child_process.terminate()
        child_process.join()
        child_process = None
        print("子进程关闭成功")

def kill_handler(signal_num, frame):
    global terminate
    terminate = True

if __name__ == "__main__":
    run_parent()
