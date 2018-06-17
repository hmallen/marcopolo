import datetime
import logging
import os
import sys

from poloniex import Poloniex
from pymongo import MongoClient

mongo_ip = 'mongodb://192.168.1.129:27017/'

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class MarcoPolo:
    def __init__(self, config_path):
        import configparser

        config = configparser.ConfigParser()
        config.read(config_path)

        polo_api = config['poloniex']['api']
        polo_secret = config['poloniex']['secret']

        self.polo = Poloniex(polo_api, polo_secret)

        self.db = MongoClient(mongo_ip)


    def create_trade(self, market, buy_target, profit_level, stop_level, stop_price=None,
                     spend_proportion=0.01, price_tolerance=0.001, entry_timeout=5, taker_fee_ok=True):
        create_trade_result = True

        try:
            self.market = market
            logger.debug('self.market: ' + self.market)

            self.buy_target = buy_target
            logger.debug('self.buy_target: ' + str(self.buy_target))

            self.buy_max = self.buy_target * (1 + price_tolerance)

            self.profit_level = profit_level
            logger.debug('self.profit_level: ' + str(self.profit_level))

            self.sell_price = self.buy_target * (1 + self.profit_level)
            logger.debug('self.sell_price: ' + str(self.sell_price))

            self.stop_level = stop_level
            logger.debug('self.stop_level: ' + str(self.stop_level))

            if stop_price == None:
                self.stop_price = self.buy_target * (1 - self.stop_level)
                logger.debug('self.stop_price: ' + str(self.stop_price))

            else:
                if stop_price < self.buy_target:
                    self.stop_price = stop_price

                else:
                    logger.error('Invalid parameters. Stop price set equal to or greater than buy target.')

                    create_trade_result = False

            self.spend_proportion = spend_proportion
            logger.debug('self.spend_proportion: ' + str(self.spend_proportion))

            self.abort_time = datetime.datetime.now() + datetime.timedelta(minutes=entry_timeout)
            logger.debug('self.abort_time: ' + str(self.abort_time))

            fee_info = self.polo.returnFeeInfo()

            self.maker_fee = fee_info['makerFee']
            logger.debug('self.maker_fee: ' + str(self.maker_fee))

            self.taker_fee = fee_info['takerFee']
            logger.debug('self.taker_fee: ' + str(self.taker_fee))

            self.base_currency = self.market.split('_')[0]
            logger.debug('self.base_currency: ' + self.base_currency)

            self.trade_currency = self.market.split('_')[1]
            logger.debug('self.trade_currency: ' + self.trade_currency)

            trade_doc = dict(market=self.market, time=datetime.datetime.now(),
                             buy=dict(target=self.buy_target,
                                      max=xyz,
                                      actual=xyz,
                                      abort_time=xyz,
                                      complete=False),
                             sell=dict(target=self.sell_price,
                                       stop=self.stop_price,
                                       actual=None,
                                       complete=False),
                             fees=dict(maker=self.maker_fee, taker=self.taker_fee),
                             parameters=dict(market=market,
                                             buy_target=buy_target,
                                             profit_level=profit_level,
                                             stop_level=stop_level,
                                             stop_price=stop_price,
                                             spend_proportion=spend_proportion,
                                             price_tolerance=price_tolerance,
                                             entry_timeout=entry_timeout,
                                             taker_fee_ok=taker_fee_ok))

        except Exception as e:
            logger.exception('Exception in create_trade().')
            logger.exception(e)

            create_trade_result = False

        finally:
            return create_trade_result


    def exec_trade(self):
        try:
            balances = self.polo.returnAvailableBalances()

        except Exception as e:
            logger.exception('Exception in exec_trade().')
            logger.exception(e)


if __name__ == '__main__':
    # __init__(self, config_path)
    # create_trade(self, market, buy_target, profit_level, stop_level, stop_price=None, spend_proportion, price_tolerance=0.001, entry_timeout=5)
    polo = Poloniex()

    test_config_path = '../config/config_polo.ini'

    marcopolo = MarcoPolo(config_path=test_config_path)

    test_market = 'BTC_STR'
    logger.debug('test_market: ' + test_market)
    test_buy_target = polo.returnTicker()['BTC_STR']['last']
    logger.debug('test_buy_target: ' + str(test_buy_target))
    test_profit_level = 0.015
    logger.debug('test_profit_level: ' + str(test_profit_level))
    test_stop_level = 0.01
    logger.debug('test_stop_level: ' + str(test_stop_level))
    test_spend_proportion = 0.01
    logger.debug('test_spend_proportion: ' + str(test_spend_proportion))
    test_entry_timeout = 5
    logger.debug('test_entry_timeout: ' + str(test_entry_timmeout))

    create_trade_result = marcopolo.create_trade(market=test_market, buy_target=test_buy_target,
                                                 profit_level=test_profit_level, stop_level=test_stop_level,
                                                 spend_proportion=test_spend_proportion, entry_timeout=test_entry_timeout)
    logger.debug('create_trade_result: ' + str(create_trade_result))
