from time import sleep

import numpy as np

from datetime import datetime, time
from vnpy.trader.utility import round_to

from examples.util.util_wx_ft import sendWxMsg
from vnpy.app.cta_strategy import (
    CtaTemplate,
    TickData,
    TradeData,
    BarData,
    OrderData,
    StopOrder,
)
from vnpy.trader.constant import Status, Direction, Offset

'''
做市商策略：
本策略通过不断对 LTC190927.HUOBI 进行:
入场： 每次读 Tick ，分析过去 30 个 tick 的的总计，如果买量大于卖量，开多单 ；反之空单
买(卖)一价现价单开多(空)和卖(买)一价平多(空)仓来做市, 并以此赚取差价
'''

#  LTC190927.HUOBI
########################################################################
class MarketMakerStrategy(CtaTemplate):
    """基于Tick的交易策略"""

    author = u'czhu'

    # 策略参数
    input_ss = 2
    tickSize = 30

    # 策略变量
    posPrice = 0  # 持仓价格
    poss = 0  # 持仓数量

    # 参数列表，保存了参数的名称
    parameters = ['tickSize', 'input_ss']

    # 同步列表，保存了需要保存到数据库的变量名称
    variables = ['poss', 'posPrice']

    # ----------------------------------------------------------------------
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super(MarketMakerStrategy, self).__init__(
            cta_engine, strategy_name, vt_symbol, setting
        )

        # 创建Array队列
        self.tickArray = TickArrayManager(self.tickSize)

        self.entrust = 0
        self.min_diff = 0.001

        self.ask_price = 0
        self.bid_price = 0

    def on_init(self):
        self.write_log(u'%s策略初始化' % self.strategy_name)
        # tick级别交易，不需要过往历史数据
        self.load_tick(0)

    # ----------------------------------------------------------------------
    def on_start(self):
        self.entrust = 0
        self.write_log(u'%s策略启动' % self.strategy_name)

    # ----------------------------------------------------------------------
    def on_stop(self):
        self.write_log(u'%s策略停止' % self.strategy_name)

    # ----------------------------------------------------------------------
    def on_tick(self, tick: TickData):

        # 首先检查是否是实盘运行还是数据预处理阶段
        if not self.inited or not self.trading:
            return

        if self.entrust != 0:
            return

        if self.poss == 0:
            TA = self.tickArray
            TA.updateTick(tick)
            if not TA.inited:
                return

            # 如果空仓，分析过去30个对比，ask卖方多下空单，bid买方多下多单
            if TA.askBidVolumeDif() > 0:
                price = tick.ask_price_2
                self.bid_price = tick.bid_price_2
                ref = self.short(price, self.input_ss, False)
                self.write_log(u'开空单{},价:{}'.format(ref, price))

            elif TA.askBidVolumeDif() <= 0:
                price = tick.bid_price_2
                self.ask_price = tick.ask_price_2
                ref = self.buy(price, self.input_ss, False)
                self.write_log(u'开多单{},价:{}'.format(ref, price))

            self.entrust = 1

            # re-init TA
            TA.re_init()

    def on_order(self, order: OrderData):
        # if order.offset == Offset.OPEN:
        #     msg = u'{}{},{}张,价:{}'.format(order.offset.value, order.direction.value, order.volume, order.price)
        # else:
        #     if order.direction == Direction.LONG:
        #         direc = '空'
        #     else:
        #         direc = '多'
        #     msg = f'{order.offset.value}{direc},{order.volume}张,价:{order.price}'
        # self.write_log(f'\t报单更新,{order.orderid},{order.status.value},{msg}')

        if order.status == Status.SUBMITTING:
            self.entrust = 1
        elif order.status in [Status.NOTTRADED, Status.PARTTRADED]:
            # if order.offset == Offset.OPEN:
            #     sleep(20)
            #     self.write_log("取消开单")
            #     self.cancel_all()
            #     self.entrust = 0
            pass
        elif order.status == Status.ALLTRADED:
            if order.direction == Direction.LONG:
                self.poss += self.input_ss
            elif order.direction == Direction.SHORT:
                self.poss -= self.input_ss

            self.entrust = 0
            # sendWxMsg(order.symbol + msg, '')
        elif order.status == Status.CANCELLED:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            self.entrust = 0
            self.poss = 0
            sleep(10)  # 10s
        elif order.status == Status.REJECTED:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            # if order.offset == Offset.CLOSE:  # 平仓单异常
            #     self.write_log("取消多余的平仓单")
            #     self.cancel_all()
            sleep(10)  # 10s
        else:
            self.write_log(f'\t报单更新,{order.orderid},{order.status.value}')
            pass

        self.put_event()

    def on_trade(self, trade: TradeData):
        # 同步数据到数据库
        if self.entrust == 0:
            msg = u'{}{},{}张,成交价:{}'.format(trade.offset.value, trade.direction.value, trade.volume, trade.price)
            self.write_log(f'交易完成,{trade.orderid},{msg}')

            if trade.offset == Offset.OPEN:
                self.entrust = 1
                if trade.direction == Direction.LONG:
                    price = self.ask_price
                    price = round_to(price, self.min_diff)
                    ref = self.sell(price, self.input_ss, False)
                    self.write_log(u'平多单{},价:{}'.format(ref, price))
                elif trade.direction == Direction.SHORT:
                    price = self.bid_price
                    price = round_to(price, self.min_diff)
                    ref = self.cover(price, self.input_ss, False)
                    self.write_log(u'平空单{},价:{}'.format(ref, price))

        self.put_event()


########################################################################
class TickArrayManager(object):
    """
    Tick序列管理工具，负责：
    1. Tick时间序列的维护
    2. 常用技术指标的计算
    """

    def __init__(self, size=10):
        """Constructor"""
        self.count = 0  # 缓存计数
        self.size = size  # 缓存大小
        self.inited = False  # True if count>=size

        self.Ticklast_priceArray = np.zeros(self.size)
        self.TickaskVolume1Array = np.zeros(self.size)
        self.TickbidVolume1Array = np.zeros(self.size)
        self.TickaskPrice1Array = np.zeros(self.size)
        self.TickbidPrice1Array = np.zeros(self.size)
        self.TickopenInterestArray = np.zeros(self.size)
        self.TickvolumeArray = np.zeros(self.size)

    def re_init(self):
        self.count = 0
        self.inited = False

    def updateTick(self, tick):
        """更新tick Array"""
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.Ticklast_priceArray[0:self.size - 1] = self.Ticklast_priceArray[1:self.size]
        self.TickaskVolume1Array[0:self.size - 1] = self.TickaskVolume1Array[1:self.size]
        self.TickbidVolume1Array[0:self.size - 1] = self.TickbidVolume1Array[1:self.size]
        self.TickaskPrice1Array[0:self.size - 1] = self.TickaskPrice1Array[1:self.size]
        self.TickbidPrice1Array[0:self.size - 1] = self.TickbidPrice1Array[1:self.size]
        self.TickopenInterestArray[0:self.size - 1] = self.TickopenInterestArray[1:self.size]
        self.TickvolumeArray[0:self.size - 1] = self.TickvolumeArray[1:self.size]

        self.Ticklast_priceArray[-1] = tick.last_price
        self.TickaskVolume1Array[-1] = tick.ask_volume_1
        self.TickbidVolume1Array[-1] = tick.bid_volume_1
        self.TickaskPrice1Array[-1] = tick.ask_price_1
        self.TickbidPrice1Array[-1] = tick.bid_price_1
        self.TickopenInterestArray[-1] = tick.open_interest
        self.TickvolumeArray[-1] = tick.volume

    def askBidVolumeDif(self):
        return self.TickaskVolume1Array.sum() - self.TickbidVolume1Array.sum()
